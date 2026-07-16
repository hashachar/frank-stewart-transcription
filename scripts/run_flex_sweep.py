#!/usr/bin/env python3
"""Flex-tier sweep driver: run transcribe.py --flex over a fixed list of scans,
with a hard spend ceiling and an hourly re-check when Flex has no capacity.

This is the outer loop around transcribe.py's inner 429 backoff burst:

  transcribe.py --flex   → 6 attempts, exp. backoff 15s→120s   (inner, ~4 min)
  run_flex_sweep.py      → re-check pending scans every hour, capped at 12h

Cost model (the reason this script exists):
  - A Flex 429 "resource unavailable" is rejected BEFORE the model runs: $0.
    Retrying it is free, so 429'd scans are re-checked hourly, forever-ish.
  - Anything else (5xx, timeout, 400) MAY have executed and been billed.
    Those are only re-run because the user explicitly approved it for this run,
    and only up to MAX_FAIL_ATTEMPTS times, and only while under the ceiling.
  - The ceiling is checked BEFORE issuing each request, using the worst per-scan
    cost seen so far, so we can't step over it mid-flight.

Scope is fixed at the scans passed on the command line. It never expands.

Usage:
  python3 run_flex_sweep.py --model gpt-5.6-sol --effort xhigh \
      --outdir gpt-5.6-sol_effort-xhigh_CI-on_Phase1e --prompt "Phase 1e" \
      --ceiling 12.00 --scans FN-0001 FN-0002 ...
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent
LOGS_DIR = BASE / "logs"

# Standard rates per 1M tokens; flex bills at 50%.
MODEL_PRICING = {
    "gpt-5.6-sol":   (5.00, 30.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-luna":  (1.00,  6.00),
    "gpt-5.5":       (5.00, 30.00),
}

MAX_FAIL_ATTEMPTS = 3       # non-429 failures per scan, then give up permanently
FALLBACK_EST = 0.75         # $/scan headroom assumed before we've measured one


def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scans", nargs="+", required=True)
    ap.add_argument("--model", default="gpt-5.6-sol")
    ap.add_argument("--effort", default="xhigh")
    ap.add_argument("--prompt", default="Phase 1e")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--ceiling", type=float, required=True,
                    help="Hard spend ceiling in USD; sweep stops before crossing it")
    ap.add_argument("--max-cycles", type=int, default=12,
                    help="Hourly re-check cycles for capacity-blocked scans (default 12 = 12h)")
    ap.add_argument("--cycle-sleep", type=int, default=3600)
    ap.add_argument("--flex-max-attempts", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=3600.0,
                    help="Per-request client timeout (s). Must exceed the slowest "
                         "plausible request: a timeout does not cancel the request "
                         "server-side, so we'd bill for output we never receive. "
                         "xhigh execution alone has been measured at ~24 min, and "
                         "Flex queueing adds to that.")
    return ap.parse_args()


def already_done(outdir: Path, stem: str) -> bool:
    return any(outdir.glob(f"{stem}_*.txt"))


def cost_from_log(log_path: Path, model: str):
    """Exact cost from the raw response JSON transcribe.py just wrote."""
    data = json.loads(log_path.read_text(encoding="utf-8"))
    usage = data.get("usage") or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
    in_price, out_price = MODEL_PRICING.get(model, (5.00, 30.00))
    if (data.get("service_tier") or "") == "flex":
        in_price /= 2
        out_price /= 2
    cost = (in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price
    return cost, in_tok, out_tok, reasoning, data.get("service_tier")


def run_one(stem, args):
    """Returns (status, cost, detail). status: ok | rate_limited | failed"""
    cmd = [
        sys.executable, str(SCRIPTS / "transcribe.py"),
        "--model", args.model,
        "--effort", args.effort,
        "--flex",
        "--flex-max-attempts", str(args.flex_max_attempts),
        "--timeout", str(args.timeout),
        "--prompt", args.prompt,
        "--outdir", args.outdir,
        "--image", stem,
    ]
    proc = subprocess.run(cmd, cwd=str(SCRIPTS), capture_output=True, text=True)
    out, err = proc.stdout, proc.stderr

    if proc.returncode == 0:
        m = re.search(r"^Log\s+→ (.+)$", out, re.M)
        if m:
            try:
                cost, i, o, r, tier = cost_from_log(Path(m.group(1).strip()), args.model)
                return "ok", cost, f"in={i:,} out={o:,} reasoning={r:,} tier={tier}"
            except Exception as exc:
                log(f"    (could not price log: {exc}; falling back to stdout)")
        m = re.search(r"Estimated cost\s+: \$([0-9.]+)", out)
        return "ok", float(m.group(1)) if m else 0.0, "priced from stdout"

    blob = err + out
    if "RateLimitError" in blob or "resource_unavailable" in blob or "429" in blob:
        return "rate_limited", 0.0, "flex has no capacity (not billed)"
    tail = "; ".join(l.strip() for l in err.strip().splitlines()[-3:]) or "unknown error"
    return "failed", 0.0, tail


def main():
    args = parse_args()
    outdir = BASE / "outputs" / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    total = 0.0
    worst = 0.0
    results = {}
    fails = {s: 0 for s in args.scans}
    pending = [s for s in args.scans if not already_done(outdir, s)]

    for s in args.scans:
        if s not in pending:
            log(f"SKIP {s} — output already exists")
            results[s] = "already-done"

    log(f"sweep start: {len(pending)} scans | {args.model} / {args.effort} / flex "
        f"| ceiling ${args.ceiling:.2f} | outdir {args.outdir}")

    stop_reason = None
    for cycle in range(1, args.max_cycles + 1):
        if not pending:
            break
        if cycle > 1:
            log(f"--- {len(pending)} scan(s) capacity-blocked; sleeping "
                f"{args.cycle_sleep//60} min, then cycle {cycle}/{args.max_cycles} "
                f"(every 429 so far cost $0) ---")
            time.sleep(args.cycle_sleep)

        log(f"=== cycle {cycle}/{args.max_cycles} | pending: {', '.join(pending)} "
            f"| spent so far ${total:.4f} ===")
        still = []
        for stem in pending:
            headroom = worst if worst > 0 else FALLBACK_EST
            if total + headroom > args.ceiling:
                stop_reason = (f"CEILING GUARD: ${total:.4f} spent; next scan could cost "
                               f"~${headroom:.4f}, which risks crossing ${args.ceiling:.2f}")
                log(stop_reason)
                still.extend(pending[pending.index(stem):])
                break

            log(f"  → {stem} (attempt {fails[stem] + 1})")
            t0 = time.time()
            status, cost, detail = run_one(stem, args)
            total += cost
            worst = max(worst, cost)
            mins = (time.time() - t0) / 60

            if status == "ok":
                log(f"  ✓ {stem} ${cost:.4f} in {mins:.1f} min | {detail} "
                    f"| running total ${total:.4f}")
                results[stem] = "ok"
            elif status == "rate_limited":
                log(f"  ⏸ {stem} no flex capacity after {args.flex_max_attempts} attempts "
                    f"($0) — re-check next cycle")
                still.append(stem)
            else:
                fails[stem] += 1
                log(f"  ✗ {stem} FAILED ({fails[stem]}/{MAX_FAIL_ATTEMPTS}) after "
                    f"{mins:.1f} min | {detail}")
                if fails[stem] < MAX_FAIL_ATTEMPTS:
                    still.append(stem)
                else:
                    log(f"  ✗ {stem} giving up after {MAX_FAIL_ATTEMPTS} attempts")
                    results[stem] = f"failed: {detail}"

        pending = still
        if stop_reason:
            break

    if pending and not stop_reason:
        stop_reason = f"{len(pending)} scan(s) still pending after {args.max_cycles} cycles"

    log("=" * 64)
    log(f"SWEEP DONE | total ${total:.4f} of ${args.ceiling:.2f} ceiling")
    ok = [s for s, v in results.items() if v == "ok"]
    log(f"completed : {len(ok)}/{len(args.scans)} — {', '.join(sorted(ok)) or 'none'}")
    for s in args.scans:
        if s in results and results[s] not in ("ok",):
            log(f"  {s}: {results[s]}")
    if pending:
        log(f"still pending: {', '.join(pending)}")
    if stop_reason:
        log(f"stop reason: {stop_reason}")
    if ok:
        log(f"avg ${total/len(ok):.4f}/scan over {len(ok)} completed")


if __name__ == "__main__":
    main()
