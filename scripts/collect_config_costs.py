#!/usr/bin/env python3
"""Collect token usage + cost for each transcript in a config folder, by tracing
each output .txt back to the exact API response log that produced it.

Matching is by the timestamp embedded in the output filename
(<stem>_<YYYYmmdd>_<HHMMSS>.txt), which transcribe.py / batch fetch also embed in
the log filename — so we price the exact response behind the text being compared,
not a different attempt at the same scan.

Handles both log shapes:
  - sync  : logs/<stem>_<ts>_<effort>_CI-<on|off>_raw.json        → top-level usage
  - batch : logs/<stem>_<ts>_<effort>_CI-<on|off>_batch_raw.json  → response.body.usage

Note on tiers: cost is reported two ways —
  actual_cost : what the run really billed (batch=50%, flex=50%, default=100%)
  flex_cost   : every config repriced at flex rates, for apples-to-apples compare
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE / "logs"

MODEL_PRICING = {
    "gpt-5.6-sol":   (5.00, 30.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-luna":  (1.00,  6.00),
    "gpt-5.5":       (5.00, 30.00),
    "gpt-5.4":       (2.50, 15.00),
}

TS_RE = re.compile(r"_(\d{8}_\d{6})\.txt$")


def _base_model(model_id: str) -> str:
    """'gpt-5.5-2026-04-23' → 'gpt-5.5'"""
    if not model_id:
        return ""
    m = re.match(r"(gpt-5\.6-(?:sol|terra|luna)|gpt-5\.\d)", model_id)
    return m.group(1) if m else model_id


def find_log(ts: str):
    hits = sorted(LOGS_DIR.glob(f"*_{ts}_*raw.json"))
    return hits[0] if hits else None


def usage_from_log(log_path: Path):
    """→ (model, tier, in_tok, out_tok, reasoning, is_batch)"""
    data = json.loads(log_path.read_text(encoding="utf-8"))
    is_batch = log_path.name.endswith("_batch_raw.json")
    if is_batch:
        body = ((data.get("response") or {}).get("body")) or {}
    else:
        body = data
    usage = body.get("usage") or {}
    if not usage:
        return None
    return (
        _base_model(body.get("model") or ""),
        (body.get("service_tier") or "default"),
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
        is_batch,
    )


def price(model, in_tok, out_tok, tier, is_batch):
    in_p, out_p = MODEL_PRICING.get(model, (5.00, 30.00))
    actual_mult = 0.5 if (tier == "flex" or is_batch) else 1.0
    actual = ((in_tok / 1e6) * in_p + (out_tok / 1e6) * out_p) * actual_mult
    flex = ((in_tok / 1e6) * in_p + (out_tok / 1e6) * out_p) * 0.5
    return actual, flex


def collect(folder: Path, scans):
    """→ {stem: {...}} for the given scan stems, pricing the exact response used."""
    out = {}
    for stem in scans:
        cands = [p for p in folder.glob(f"{stem}_*.txt")
                 if ".literal" not in p.name and ".normalized" not in p.name]
        if not cands:
            continue
        txt = sorted(cands)[-1]
        m = TS_RE.search(txt.name)
        if not m:
            continue
        ts = m.group(1)
        log_path = find_log(ts)
        if not log_path:
            out[stem] = {"txt": txt, "error": f"no log for ts {ts}"}
            continue
        u = usage_from_log(log_path)
        if not u:
            out[stem] = {"txt": txt, "error": f"no usage in {log_path.name}"}
            continue
        model, tier, i, o, r, is_batch = u
        actual, flex = price(model, i, o, tier, is_batch)
        out[stem] = {
            "txt": txt, "log": log_path.name, "model": model,
            "tier": "batch" if is_batch else tier,
            "in": i, "out": o, "reasoning": r,
            "actual_cost": actual, "flex_cost": flex,
        }
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    scans = [f"FN-{i:04d}" for i in range(1, 11)]
    folder = BASE / "outputs" / sys.argv[1]
    data = collect(folder, scans)
    print(f"{'scan':9} {'model':12} {'tier':8} {'in':>8} {'out':>8} {'reason':>8} "
          f"{'actual$':>9} {'flex$':>8}")
    ta = tf = 0.0
    for s in scans:
        d = data.get(s)
        if not d:
            print(f"{s:9} (missing)")
            continue
        if "error" in d:
            print(f"{s:9} ERROR {d['error']}")
            continue
        ta += d["actual_cost"]; tf += d["flex_cost"]
        print(f"{s:9} {d['model']:12} {d['tier']:8} {d['in']:8,} {d['out']:8,} "
              f"{d['reasoning']:8,} {d['actual_cost']:9.4f} {d['flex_cost']:8.4f}")
    n = sum(1 for s in scans if data.get(s) and "error" not in data[s])
    if n:
        print(f"\nn={n}  actual=${ta:.4f}  flex=${tf:.4f}  "
              f"avg_flex=${tf/n:.4f}/scan  →1200 scans @flex ≈ ${tf/n*1200:,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
