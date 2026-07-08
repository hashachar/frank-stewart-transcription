#!/usr/bin/env python3
"""
batch_transcribe.py — Async batch transcription via OpenAI Batch API.

Workflow (run each stage in order):

  1. prepare  — upload images to Files API, build JSONL, save job state
  2. submit   — send JSONL to Batch API, record batch_id
  3. status   — check progress (run any time after submit)
  4. fetch    — download results → output folders; optionally run Phase 2
  5. retry    — resubmit only the failed requests from a completed batch

State between stages is persisted in batch_jobs/<job-name>.json.

Usage examples
--------------
# Full directory, medium effort, CI on (recommended config):
python batch_transcribe.py prepare --effort medium
python batch_transcribe.py submit  --job my-run
python batch_transcribe.py status  --job my-run
python batch_transcribe.py fetch   --job my-run --run-phase2

# If some requests failed, resubmit only those:
python batch_transcribe.py retry   --job my-run
python batch_transcribe.py status  --job my-run
python batch_transcribe.py fetch   --job my-run --run-phase2

# Single image test:
python batch_transcribe.py prepare --image FN-6-001-050-1 --effort medium --job test-single
python batch_transcribe.py submit  --job test-single
python batch_transcribe.py fetch   --job test-single --run-phase2

# First 5 images only (smoke test before committing the full set):
python batch_transcribe.py prepare --limit 5 --effort medium --job smoke5
"""

import os
import re
import sys
import json
import time
import argparse
import datetime
import subprocess
import importlib.util
import urllib.request
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# max_retries: the SDK retries transient failures (429 / 5xx / connection errors)
# with exponential backoff, so a blip doesn't abort a stage (#6).
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=1800.0, max_retries=5)

# Admin key powers the cost watchdog's live billed-cost / execution-count signals
# (the /v1/organization/usage endpoints). Absent → cost-based guardrails disable
# and the watchdog falls back to the lag-free failure-ratio check only.
ADMIN_KEY = os.getenv("OPENAI_ADMIN_API_KEY")

# Batch API hard limits (used for pre-flight checks in submit — #10)
BATCH_MAX_REQUESTS   = 50_000
BATCH_MAX_INPUT_MB   = 200

BASE        = Path(__file__).resolve().parent.parent
PROMPT_DIR  = BASE / "prompt"
SCANS_DIR   = BASE / "scans"
LOGS_DIR    = BASE / "logs"
JOBS_DIR    = BASE / "batch_jobs"

PHASE2_SCRIPT = Path(__file__).resolve().parent / "Phase 2 - Normalize Code.py"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".gif"}
MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Standard per-1M-token rates; batch = 50% off
MODEL_PRICING = {
    "gpt-5.5":     (5.00,  30.00),
    "gpt-5.4":     (2.50,  15.00),
    "gpt-5.4-pro": (2.50,  15.00),
    "gpt-4.1":     (2.00,   8.00),
}

# Pipeline default config, established 2026-07-03: gpt-5.5 / high effort / Phase 1e prompt.
DEFAULT_MODEL  = "gpt-5.5"
DEFAULT_EFFORT = "high"
DEFAULT_PROMPT = "Phase 1e"

# --- Pre-submit balance guard ------------------------------------------------
# A batch that runs out of credit mid-flight does NOT stop cheaply. Failed
# requests still burn (and are billed for) the reasoning + Code-Interpreter
# tokens they generate before failing, and the Batch API retries them — so a
# near-empty balance turns a ~$10 job into a ~$30 one (this happened 2026-07-03:
# 6 usable pages, ~$30 billed). The only real protection is to never submit
# unless the balance comfortably exceeds the worst case.
#
# OpenAI exposes no API to read the prepaid credit balance, so the guard
# estimates a deliberately conservative worst-case cost and makes the user
# confirm (via --balance or an interactive prompt) that their balance clears it.
WORST_CASE_TOKENS_PER_PAGE = (75_000, 32_000)   # (input, output) — heavy high-effort + CI page
RETRY_SAFETY_FACTOR        = 4                  # pad for the failed-request retry storm
MIN_REQUIRED_BUFFER        = 15.0               # never run a batch on a near-empty balance

# --- Batch cost watchdog -----------------------------------------------------
# The `watch` command live-monitors a running batch and auto-cancels on the
# earliest real storm signature. Deliberately conservative defaults, tuned from
# the 2026-07-03/04 incidents (see reports/); every value is overridable per-run
# via `watch` CLI flags. Rationale for the numbers lives in the plan/README.
WATCHDOG_DEFAULTS = {
    "per_page_expected":   0.60,   # generous vs. observed ~$0.30-0.53 batch/page
    # Failure-ratio relaxed 2026-07-06: Batch-API flakiness is expected on this
    # workload (failed scans just fall back to synchronous), so a handful of
    # failures should NOT cancel the batch. Storm prevention now rests on the
    # retry-multiplier + spend ceiling below, not the raw failure count.
    "fail_ratio":          0.35,   # trip if failed/total >= this ...
    "fail_min":            4,      # ... and failed >= this (tolerate up to 3 isolated failures)
    "fail_abs":            30,     # ... OR failed >= this regardless of ratio (large batches)
    "exec_multiplier":     1.5,    # trip if executions >= total * this (still catches the 1.6x storm) ...
    "exec_min_excess":     3,      # ... and executions - total >= this (tolerate light single-retries)
    "cost_per_page_mult":  4.0,    # trip if billed/completed >= this * per_page_expected
    "spend_mult":          2.0,    # auto ceiling = total * per_page_expected * this ...
    "spend_floor":         3.0,    # ... but never below this  (hard backstop, unchanged)
    "stall_minutes":       20,     # stall needs at least this elapsed (give slow batches room) ...
    "stall_cost_mult":     1.0,    # ... and billed >= total * per_page_expected * this, with 0 completed
    "interval_base":       60,     # seconds between polls when healthy
    "interval_risk":       20,     # seconds between polls once any risk signal appears
}
WATCHDOG_GUARDRAILS = ("failure-ratio", "storm", "cost-per-page", "spend", "stall")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_phase2():
    """Import process_file from the Phase 2 script (non-standard filename)."""
    spec = importlib.util.spec_from_file_location("stewart_normalize", PHASE2_SCRIPT)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.process_file


def _state_path(job_name: str) -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return JOBS_DIR / f"{job_name}.json"


def _load_state(job_name: str) -> dict:
    p = _state_path(job_name)
    if not p.exists():
        sys.exit(f"No job state found for '{job_name}'. Run prepare first.")
    return json.loads(p.read_text(encoding="utf-8"))


def _save_state(state: dict):
    p = _state_path(state["job_name"])
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _cost_line(input_tok, output_tok, reasoning_tok, model, batch=True):
    in_rate, out_rate = MODEL_PRICING.get(model, (5.00, 30.00))
    if batch:
        in_rate  /= 2
        out_rate /= 2
    in_cost  = (input_tok  / 1_000_000) * in_rate
    out_cost = (output_tok / 1_000_000) * out_rate
    visible  = output_tok - reasoning_tok
    return in_cost + out_cost, in_cost, out_cost, visible


def _resolve_prompt(query: str | None) -> Path:
    """Find the prompt .txt file matching `query` (filename stem/prefix, case-
    insensitive substring), or the first one found if query is None."""
    if query:
        q = query.lower()
        candidates = [f for f in PROMPT_DIR.glob("*.txt") if q in f.stem.lower()]
        if not candidates:
            sys.exit(f"No prompt file matching '{query}' in {PROMPT_DIR}")
        return sorted(candidates)[0]
    prompt_files = sorted(PROMPT_DIR.glob("*.txt"))
    if not prompt_files:
        sys.exit(f"No prompt .txt file found in {PROMPT_DIR}")
    return prompt_files[0]


def _auto_job_name(model, effort, use_ci):
    ci = "CI-on" if use_ci else "CI-off"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{model}_effort-{effort}_{ci}_{ts}"


def _output_dir(model, effort, use_ci):
    ci = "CI-on" if use_ci else "CI-off"
    return BASE / "outputs" / f"{model}_effort-{effort}_{ci}"


def _download_jsonl(file_id):
    """Download a Batch API result/error file and parse it line-by-line.

    Returns (records, n_bad) where n_bad counts lines that could not be parsed
    (they are skipped rather than aborting the whole download — fix #4).
    """
    raw = client.files.content(file_id)
    records, n_bad = [], 0
    for line in raw.text.strip().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            n_bad += 1
    return records, n_bad


def _failed_custom_ids(error_records):
    """custom_ids that errored or didn't complete, from a batch error file."""
    failed = set()
    for rec in error_records:
        response = rec.get("response") or {}
        status_code = response.get("status_code", 0)
        if status_code >= 400 or rec.get("error"):
            cid = rec.get("custom_id")
            if cid:
                failed.add(cid)
    return failed


def _error_message(rec):
    """Best-effort human-readable reason for a single failed request record.

    Handles both shapes: output-file records carry a top-level ``error`` object,
    while batch error-file records nest it under ``response.body.error``.
    """
    top = rec.get("error")
    if isinstance(top, dict) and top.get("message"):
        return top["message"]

    response = rec.get("response") or {}
    body     = response.get("body") or {}
    err      = body.get("error")
    if isinstance(err, dict) and err.get("message"):
        return err["message"]

    if top:
        return str(top)
    if response.get("status_code"):
        return f"HTTP {response['status_code']}"
    return "unknown error"


def _print_batch_errors(batch):
    """Surface batch-level validation errors (populated when a batch fails outright)."""
    errs = getattr(batch, "errors", None)
    data = getattr(errs, "data", None) if errs else None
    if not data:
        return
    print("\nBatch-level errors:")
    for e in data:
        get = (lambda k: e.get(k)) if isinstance(e, dict) else (lambda k: getattr(e, k, None))
        loc = f" (line {get('line')})" if get("line") is not None else ""
        print(f"  [{get('code')}]{loc} {get('message')}")


def _worst_case_buffer(n_requests: int, model: str):
    """Conservative $ buffer that should be available before submitting a batch.

    Prices worst-case heavy pages at STANDARD (non-batch) rates — even though
    batch is 50% off — and multiplies by a retry safety factor, because a batch
    that hits a zero balance mid-run keeps burning (and being billed for) tokens
    on failed and auto-retried requests. Returns (required_usd, per_page_usd).
    """
    in_tok, out_tok   = WORST_CASE_TOKENS_PER_PAGE
    in_rate, out_rate = MODEL_PRICING.get(model, (5.00, 30.00))   # standard rates
    per_page = (in_tok / 1_000_000) * in_rate + (out_tok / 1_000_000) * out_rate
    required = max(MIN_REQUIRED_BUFFER, n_requests * per_page * RETRY_SAFETY_FACTOR)
    return required, per_page


def _preflight_balance_check(n_requests: int, model: str, args):
    """Block a batch submission unless the account balance clears a conservative
    worst-case buffer. Balance comes from --balance or an interactive prompt
    (OpenAI has no API to read the prepaid credit balance). Bypass with
    --skip-balance-check. Exits the process on an insufficient balance."""
    required, per_page = _worst_case_buffer(n_requests, model)
    likely_batch = n_requests * per_page / 2.0    # batch = 50% off, all succeed once, no retries

    print("\n" + "─" * 60)
    print("Pre-submit balance guard")
    print(f"  Requests                              : {n_requests}")
    print(f"  Likely cost (batch, all succeed once) : ~${likely_batch:.2f}")
    print(f"  REQUIRED balance buffer (worst case)  :  ${required:.2f}")
    print(f"    = {n_requests} req × ${per_page:.2f}/page (standard rate, heavy page) "
          f"× {RETRY_SAFETY_FACTOR} (retry-storm pad), min ${MIN_REQUIRED_BUFFER:.0f}")
    print( "  A batch that runs out of credit mid-run does NOT stop cheaply — failed")
    print( "  requests still burn tokens and get retried. Keep a comfortable buffer.")
    print("─" * 60)

    if getattr(args, "skip_balance_check", False):
        print("⚠  --skip-balance-check set — submitting WITHOUT verifying balance.\n")
        return

    balance = getattr(args, "balance", None)
    if balance is None:
        try:
            raw = input("Enter your CURRENT available balance in USD "
                        "(platform.openai.com → Settings → Billing): ").strip().lstrip("$")
        except EOFError:
            sys.exit("No balance provided (non-interactive session). Re-run with "
                     "--balance <USD>, or --skip-balance-check to bypass.")
        try:
            balance = float(raw)
        except ValueError:
            sys.exit(f"Could not read '{raw}' as a dollar amount. Aborting.")

    if balance + 1e-9 < required:
        sys.exit(
            f"\nABORTED — balance ${balance:.2f} is below the required buffer ${required:.2f}.\n"
            f"Add at least ${required - balance:.2f} more (aim comfortably above ${required:.2f}) "
            f"before submitting, or split into a smaller batch with --limit.")
    print(f"✓ Balance ${balance:.2f} clears the ${required:.2f} buffer — proceeding.\n")


# ---------------------------------------------------------------------------
# Cost watchdog helpers
# ---------------------------------------------------------------------------

def _admin_usage_since(created_at, end_at=None):
    """Billed (executions, input_tokens, output_tokens) for batch=True work in
    the window [``created_at``, ``end_at``] (unix seconds), from the Admin usage
    API. ``end_at=None`` means "up to now" (used live by the watchdog); a bounded
    ``end_at`` is used by the ledger to attribute a window to one batch.

    Returns None if the admin key is absent or the call fails — the caller then
    degrades to the lag-free failure-ratio guardrail. Attribution assumes at most
    one batch runs per window (true for this one-batch-at-a-time workflow); the
    usage endpoint cannot group by a single batch_id.
    """
    if not ADMIN_KEY:
        return None
    # Floor to the hour so the bucket covering the batch's creation minute is
    # captured in full (hourly usage buckets are hour-aligned).
    start = int(created_at) - (int(created_at) % 3600)
    params = {"start_time": start, "bucket_width": "1h", "limit": 168}
    if end_at:
        params["end_time"] = int(end_at) + 3600   # pad one hour to catch the final bucket
    q = urllib.parse.urlencode(params) + "&group_by=batch"
    url = "https://api.openai.com/v1/organization/usage/completions?" + q
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {ADMIN_KEY}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except Exception:
        return None
    execs = in_tok = out_tok = 0
    for bucket in data.get("data", []):
        for res in bucket.get("results", []):
            if res.get("batch") is True:
                execs   += res.get("num_model_requests", 0)
                in_tok  += res.get("input_tokens", 0)
                out_tok += res.get("output_tokens", 0)
    return execs, in_tok, out_tok


def _evaluate_guardrails(snap, cfg, enabled):
    """Pure guardrail check — no I/O, so it is unit-testable via `watch --selftest`.

    ``snap`` keys: total, completed, failed, execs (or None), live_cost (or None),
    elapsed_min. ``cfg`` = thresholds (a copy of WATCHDOG_DEFAULTS + overrides,
    optionally with an absolute ``max_spend``). ``enabled`` = set of guardrail
    names. Returns a list of (name, human_message) for every tripped guardrail.
    """
    trips = []
    total     = snap.get("total") or 0
    completed = snap.get("completed") or 0
    failed    = snap.get("failed") or 0
    execs     = snap.get("execs")
    cost      = snap.get("live_cost")
    elapsed   = snap.get("elapsed_min") or 0
    ppe       = cfg["per_page_expected"]

    # 1. Failure-ratio — instant, lag-free (from request_counts). Every failed
    #    request already exhausted its internal retries, i.e. money already burned.
    if "failure-ratio" in enabled and total:
        if (failed >= cfg["fail_min"] and failed / total >= cfg["fail_ratio"]) \
                or failed >= cfg["fail_abs"]:
            trips.append(("failure-ratio",
                f"{failed}/{total} requests failed ({failed/total:.0%}) — each already "
                f"burned its internal retries"))

    # 2. Retry-storm multiplier — executions billed vs. requests submitted.
    if "storm" in enabled and execs is not None and total:
        if execs >= total * cfg["exec_multiplier"] and (execs - total) >= cfg["exec_min_excess"]:
            trips.append(("storm",
                f"{execs} model executions for {total} submitted ({execs/total:.2f}x) — "
                f"internal retries in progress"))

    # 3. Cost-per-completed — am I paying too much per page I actually receive?
    if "cost-per-page" in enabled and cost is not None and completed >= 1:
        cpp   = cost / completed
        limit = cfg["cost_per_page_mult"] * ppe
        if cpp >= limit:
            trips.append(("cost-per-page",
                f"${cpp:.2f} billed per completed page (limit ${limit:.2f})"))

    # 4. Hard $ ceiling — absolute backstop.
    if "spend" in enabled and cost is not None:
        max_spend = cfg.get("max_spend")
        if max_spend is None:
            max_spend = max(cfg["spend_floor"], total * ppe * cfg["spend_mult"])
        if cost >= max_spend:
            trips.append(("spend", f"${cost:.2f} billed, at/over the ${max_spend:.2f} ceiling"))

    # 5. Stall / zero-output — time-gated so a slow-but-healthy batch is not nuked.
    if "stall" in enabled and cost is not None and completed == 0:
        if elapsed >= cfg["stall_minutes"] and cost >= total * ppe * cfg["stall_cost_mult"]:
            trips.append(("stall",
                f"${cost:.2f} billed, 0 completed after {elapsed:.0f} min — producing nothing"))

    return trips


def _notify(title, message, quiet=False):
    """Loud terminal banner, plus a macOS notification + sound unless --quiet."""
    print(f"\n{'!'*64}\n  {title}\n  {message}\n{'!'*64}")
    if quiet:
        return
    safe_t = title.replace('"', "'")
    safe_m = message.replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_m}" with title "{safe_t}" sound name "Sosumi"'],
            check=False, capture_output=True, timeout=5)
    except Exception:
        pass


def _watchdog_selftest():
    """Replay the three real incidents (and healthy snapshots) through
    _evaluate_guardrails to prove the defaults trip on storms and NOT on healthy
    batches. No network, no spend."""
    cfg     = dict(WATCHDOG_DEFAULTS)
    enabled = set(WATCHDOG_GUARDRAILS)
    cases = [
        # name, snapshot, expect_trip
        # RELAXED 2026-07-06: a few failures no longer cancel (they fall back to sync).
        ("2 failures tolerated",   {"total":20,"completed":0, "failed":2, "execs":None,"live_cost":None, "elapsed_min":30},  False),
        ("3 fails + light retries",{"total":30,"completed":25,"failed":3, "execs":33,  "live_cost":15.0, "elapsed_min":90},  False),
        # Storms STILL caught (retry-multiplier / cost-per-page / spend):
        ("storm 1.6x (retries)",   {"total":5, "completed":3, "failed":0, "execs":8,   "live_cost":4.37, "elapsed_min":60},  True),
        ("Batch-3 storm 4.5x",     {"total":6, "completed":2, "failed":3, "execs":27,  "live_cost":13.71,"elapsed_min":80},  True),
        ("Batch-2 storm 2.2x",     {"total":17,"completed":3, "failed":14,"execs":37,  "live_cost":18.35,"elapsed_min":180}, True),
        # Systemic failure (most of the batch failing) still cancels:
        ("systemic failure 60%",   {"total":10,"completed":0, "failed":6, "execs":None,"live_cost":None, "elapsed_min":40},  True),
        ("Batch-1 17/20 failed",   {"total":20,"completed":3, "failed":17,"execs":25,  "live_cost":11.96,"elapsed_min":120}, True),
        # Healthy runs never trip:
        ("HEALTHY done",           {"total":20,"completed":20,"failed":0, "execs":21,  "live_cost":8.0,  "elapsed_min":90},  False),
        ("HEALTHY early slow",     {"total":50,"completed":0, "failed":0, "execs":2,   "live_cost":1.0,  "elapsed_min":5},   False),
    ]
    ok = True
    print("Watchdog guardrail self-test (defaults):\n")
    for name, snap, expect in cases:
        trips = _evaluate_guardrails(snap, cfg, enabled)
        got   = bool(trips)
        good  = (got == expect)
        ok    = ok and good
        names = ",".join(n for n, _ in trips) or "-"
        print(f"  [{'ok' if good else 'FAIL'}] {name:22} expect_trip={str(expect):5} got={str(got):5}  tripped: {names}")
    print("\nALL PASS" if ok else "\nSOME CASES FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Stage 1: prepare
# ---------------------------------------------------------------------------

def cmd_prepare(args):
    use_ci = not args.no_ci

    job_name = args.job or _auto_job_name(args.model, args.effort, use_ci)
    state_file = _state_path(job_name)

    # Load existing state if re-running prepare (to reuse file IDs)
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        print(f"Resuming existing job state: {job_name}")
    else:
        state = {
            "job_name":       job_name,
            "created_at":     datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "config": {
                "model":      args.model,
                "effort":     args.effort,
                "use_ci":     use_ci,
                "output_dir": str(_output_dir(args.model, args.effort, use_ci).relative_to(BASE)),
                "prompt_file": None,   # filled in below, once the prompt is resolved
            },
            "images":         {},
            "jsonl_path":     None,
            "jsonl_file_id":  None,
            "batch_id":       None,
            "status":         "preparing",
            "completed_at":   None,
            "output_file_id": None,
            "error_file_id":  None,
        }

    # Collect image files
    if args.image:
        stem = Path(args.image).stem
        matches = [f for f in SCANS_DIR.iterdir()
                   if f.stem == stem and f.suffix.lower() in IMAGE_EXTENSIONS]
        if not matches:
            sys.exit(f"Image '{args.image}' not found in {SCANS_DIR}")
        image_files = matches
    else:
        image_files = sorted(f for f in SCANS_DIR.iterdir()
                             if f.suffix.lower() in IMAGE_EXTENSIONS)
        if args.start:
            stems = [f.stem for f in image_files]
            start_stem = Path(args.start).stem
            if start_stem not in stems:
                sys.exit(f"--start image '{args.start}' not found in {SCANS_DIR}")
            image_files = image_files[stems.index(start_stem):]
    if args.limit:
        image_files = image_files[: args.limit]

    if not image_files:
        sys.exit(f"No images found in {SCANS_DIR}")

    # Guard against two files sharing a stem (e.g. FN-6-001.jpg + FN-6-001.png):
    # they map to the same state key and the same custom_id, so one would silently
    # overwrite the other and the Batch API would reject the duplicate custom_id (#8).
    seen_stems = {}
    for f in image_files:
        seen_stems.setdefault(f.stem, []).append(f.name)
    collisions = {s: names for s, names in seen_stems.items() if len(names) > 1}
    if collisions:
        detail = "; ".join(f"{s}: {', '.join(names)}" for s, names in collisions.items())
        sys.exit(f"Duplicate image stems would collide (rename or remove one of each): {detail}")

    print(f"\nJob         : {job_name}")
    print(f"Model       : {args.model}  |  effort: {args.effort}  |  CI: {'on' if use_ci else 'off'}")
    print(f"Images      : {len(image_files)}")
    print(f"State file  : {state_file}\n")

    # Load prompt
    prompt_file = _resolve_prompt(args.prompt)
    prompt_text = prompt_file.read_text(encoding="utf-8")
    state["config"]["prompt_file"] = prompt_file.name
    print(f"Prompt      : {prompt_file.name}\n")

    # Upload images (skip if file_id already recorded and --reuse-files)
    for img in image_files:
        stem = img.stem
        existing = state["images"].get(stem, {})

        if args.reuse_files and existing.get("file_id"):
            print(f"  [reuse]  {img.name}  →  {existing['file_id']}")
            continue

        print(f"  [upload] {img.name} ({img.stat().st_size / 1_048_576:.1f} MB)...", end=" ", flush=True)
        with img.open("rb") as fh:
            result = client.files.create(file=fh, purpose="vision")
        file_id = result.id
        print(file_id)

        state["images"][stem] = {
            "path":      str(img),
            "file_id":   file_id,
            "custom_id": f"req-{stem}",
        }
        _save_state(state)   # save after each upload — safe to interrupt and retry

    # Build JSONL
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = JOBS_DIR / f"{job_name}.jsonl"
    tools = [{"type": "code_interpreter", "container": {"type": "auto"}}] if use_ci else []

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for stem, info in state["images"].items():
            line = {
                "custom_id": info["custom_id"],
                "method":    "POST",
                "url":       "/v1/responses",
                "body": {
                    "model":     args.model,
                    "reasoning": {"effort": args.effort},
                    "tools":     tools,
                    "input": [{
                        "role": "user",
                        "content": [
                            {"type": "input_text",  "text": prompt_text},
                            {"type": "input_image", "file_id": info["file_id"], "detail": "high"},
                        ],
                    }],
                },
            }
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    jsonl_size_mb = jsonl_path.stat().st_size / 1_048_576
    state["jsonl_path"] = str(jsonl_path)
    # JSONL content just changed — drop any previously uploaded copy so submit
    # re-uploads the fresh file rather than reusing a stale file_id (#6).
    state["jsonl_file_id"] = None
    state["status"]     = "prepared"
    _save_state(state)

    print(f"\nJSONL built : {jsonl_path.name}  ({jsonl_size_mb:.2f} MB,  {len(state['images'])} requests)")
    print(f"\nNext step → python batch_transcribe.py submit --job {job_name}")


# ---------------------------------------------------------------------------
# Stage 2: submit
# ---------------------------------------------------------------------------

def cmd_submit(args):
    state = _load_state(args.job)

    if state["status"] == "submitted":
        print(f"Job '{args.job}' already submitted. Batch ID: {state['batch_id']}")
        print(f"Check status → python batch_transcribe.py status --job {args.job}")
        return

    jsonl_path = Path(state["jsonl_path"])
    if not jsonl_path.exists():
        sys.exit(f"JSONL file not found: {jsonl_path}\nRe-run prepare.")

    # Pre-flight against the Batch API's hard limits so we fail here with a clear
    # message instead of getting a rejected batch (#10).
    jsonl_size_mb = jsonl_path.stat().st_size / 1_048_576
    n_requests    = len(state["images"])
    if jsonl_size_mb > BATCH_MAX_INPUT_MB:
        sys.exit(f"JSONL is {jsonl_size_mb:.1f} MB, over the {BATCH_MAX_INPUT_MB} MB batch input limit. "
                 f"Split into smaller jobs (--limit).")
    if n_requests > BATCH_MAX_REQUESTS:
        sys.exit(f"{n_requests} requests exceeds the {BATCH_MAX_REQUESTS:,} per-batch limit. "
                 f"Split into smaller jobs (--limit).")

    # Refuse to submit on a balance that can't absorb the worst case (runs before
    # the upload so an abort never orphans a file).
    _preflight_balance_check(n_requests, state["config"]["model"], args)

    # Reuse an already-uploaded JSONL if a previous submit uploaded it but the
    # batch.create call didn't land — avoids orphaning a file on retry (#6).
    if state.get("jsonl_file_id"):
        upload_id = state["jsonl_file_id"]
        print(f"Reusing uploaded JSONL: {upload_id}")
    else:
        print(f"Uploading JSONL ({jsonl_size_mb:.2f} MB)...", end=" ", flush=True)
        with jsonl_path.open("rb") as fh:
            upload = client.files.create(file=fh, purpose="batch")
        print(upload.id)
        upload_id = upload.id
        state["jsonl_file_id"] = upload_id
        _save_state(state)

    print("Creating batch...", end=" ", flush=True)
    batch = client.batches.create(
        input_file_id=upload_id,
        endpoint="/v1/responses",
        completion_window="24h",
    )
    state["batch_id"] = batch.id
    state["status"]   = "submitted"
    _save_state(state)

    print(batch.id)
    print(f"\nBatch submitted. Completion window: 24h (usually faster).")
    print(f"Check status → python batch_transcribe.py status --job {args.job}")

    if getattr(args, "watch", False):
        print(f"\nLaunching cost watchdog (default guardrails)...\n")
        watch_args = build_parser().parse_args(["watch", "--job", args.job])
        cmd_watch(watch_args)


# ---------------------------------------------------------------------------
# Stage 3: status
# ---------------------------------------------------------------------------

def cmd_status(args):
    state = _load_state(args.job)

    if not state.get("batch_id"):
        sys.exit(f"No batch_id found. Run submit first.")

    batch = client.batches.retrieve(state["batch_id"])

    counts = batch.request_counts
    total     = counts.total     if counts else "?"
    completed = counts.completed if counts else "?"
    failed    = counts.failed    if counts else "?"

    print(f"Job         : {state['job_name']}")
    print(f"Batch ID    : {batch.id}")
    print(f"Status      : {batch.status}")
    print(f"Progress    : {completed}/{total} completed,  {failed} failed")
    if batch.expires_at:
        exp = datetime.datetime.fromtimestamp(batch.expires_at).strftime("%Y-%m-%d %H:%M")
        print(f"Expires     : {exp}")

    # Expired AND cancelled batches still expose partial output for the requests
    # that finished — treat them as fetchable (fix #1; cancelled added after the
    # 2026-07-04 storm, where cancelling mid-run left 2 completed pages to harvest).
    if batch.status in ("completed", "expired", "cancelled"):
        state["status"]         = batch.status
        state["completed_at"]   = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state["output_file_id"] = batch.output_file_id
        state["error_file_id"]  = batch.error_file_id
        _save_state(state)
        if batch.status in ("expired", "cancelled"):
            print(f"\nBatch {batch.status} before finishing. Partial results are available.")
        print(f"\nFetch results → python batch_transcribe.py fetch --job {args.job}")
    elif batch.status == "failed":
        state["status"] = batch.status
        _save_state(state)
        print(f"\nBatch ended with status: {batch.status}")
        _print_batch_errors(batch)                  # surface validation errors (fix #3)
    else:
        print(f"\nStill running. Check again later.")


# ---------------------------------------------------------------------------
# Stage 4: fetch
# ---------------------------------------------------------------------------

def _harvest_results(state, run_phase2=False, suggest_retry=True):
    """Download the output (+error) files, write transcriptions/logs, and reconcile
    against the requests we submitted.

    Safe to call for a 'completed' OR 'expired' batch — an expired batch still exposes
    an output file for the requests that finished before the deadline (fix #1). Failed
    and unfinished requests are read from the *error* file and reconciled against the
    submitted set so nothing goes missing silently (fix #2). Returns a summary dict.
    """
    cfg        = state["config"]
    model      = cfg["model"]
    effort     = cfg["effort"]
    use_ci     = cfg["use_ci"]
    output_dir = BASE / cfg["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    ci_label   = "on" if use_ci else "off"

    # Build reverse lookup: custom_id -> image stem
    custom_to_stem = {info["custom_id"]: stem for stem, info in state["images"].items()}
    expected       = set(custom_to_stem)

    phase2_fn   = _load_phase2() if run_phase2 else None
    ts_fetch    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    total_cost  = 0.0
    success     = 0
    seen        = set()
    bad_lines   = 0
    incomplete_custom_ids = set()   # completed-but-unusable responses (#5)

    # --- successful responses live in the output file ---
    if state.get("output_file_id"):
        print(f"Downloading output file {state['output_file_id']}...", end=" ", flush=True)
        records, bad_lines = _download_jsonl(state["output_file_id"])
        print(f"{len(records)} result lines\n")

        for record in records:
            # One malformed/unexpected record must not abort the whole harvest (fix #4)
            try:
                custom_id = record.get("custom_id")
                seen.add(custom_id)
                stem = custom_to_stem.get(custom_id, custom_id)

                if record.get("error"):
                    print(f"  [ERROR]  {stem}: {_error_message(record)}")
                    incomplete_custom_ids.add(custom_id)
                    continue

                response_obj = record.get("response", {}) or {}
                body         = response_obj.get("body", {}) or {}

                # Extract output text, and note any refusal parts (#5)
                output_text = ""
                refusal     = ""
                for item in body.get("output", []):
                    if item.get("type") == "message":
                        for part in item.get("content", []):
                            if part.get("type") == "output_text":
                                output_text += part.get("text", "")
                            elif part.get("type") == "refusal":
                                refusal += part.get("refusal", "")

                # A response that came back but is unusable — truncated (status
                # 'incomplete'), a refusal, or empty text — must not be saved as a
                # success; flag it so it can be retried (#5).
                resp_status = body.get("status")
                incomplete_details = body.get("incomplete_details") or {}
                if resp_status == "incomplete" or refusal or not output_text.strip():
                    if resp_status == "incomplete":
                        reason = f"incomplete ({incomplete_details.get('reason', 'unknown')})"
                    elif refusal:
                        reason = f"refusal — {refusal.strip()[:120]}"
                    else:
                        reason = "empty output text"
                    # Keep the raw record for inspection, but don't write a .txt.
                    log_path = LOGS_DIR / f"{stem}_{ts_fetch}_{effort}_CI-{ci_label}_batch_raw.json"
                    log_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str),
                                        encoding="utf-8")
                    print(f"  [INCOMPLETE] {stem}: {reason} — not saved as success")
                    incomplete_custom_ids.add(custom_id)
                    continue

                # Usage
                usage         = body.get("usage", {}) or {}
                input_tok     = usage.get("input_tokens", 0)
                output_tok    = usage.get("output_tokens", 0)
                out_details   = usage.get("output_tokens_details", {}) or {}
                reasoning_tok = out_details.get("reasoning_tokens", 0)
                in_details    = usage.get("input_tokens_details", {}) or {}
                cached_tok    = in_details.get("cached_tokens", 0)

                cost, in_cost, out_cost, visible_tok = _cost_line(
                    input_tok, output_tok, reasoning_tok, model, batch=True
                )
                total_cost += cost

                # Write output text
                out_path = output_dir / f"{stem}_{ts_fetch}.txt"
                out_path.write_text(output_text, encoding="utf-8")

                # Write raw log
                log_path = LOGS_DIR / f"{stem}_{ts_fetch}_{effort}_CI-{ci_label}_batch_raw.json"
                log_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str),
                                    encoding="utf-8")

                cached_note = f",  cached {cached_tok:,}" if cached_tok else ""
                print(f"  {stem}")
                print(f"    tokens  : {input_tok:,} in  /  {output_tok:,} out  "
                      f"(reasoning {reasoning_tok:,}  visible {visible_tok:,}{cached_note})")
                print(f"    cost    : ${cost:.4f} batch  (${in_cost:.4f} in + ${out_cost:.4f} out)")
                print(f"    saved   : {out_path.name}")

                # Phase 2 normalization
                if phase2_fn:
                    try:
                        report = phase2_fn(out_path)
                        n_flags = report["n_flags"]
                        out_names = [Path(o).name for o in report["outputs"]]
                        flag_note = f"  ⚠ {n_flags} flag(s)" if n_flags else ""
                        print(f"    phase2  : {', '.join(out_names)}{flag_note}")
                    except Exception as exc:
                        print(f"    phase2  : ERROR — {exc}")

                success += 1
            except Exception as exc:
                bad_lines += 1
                print(f"  [SKIP] could not process a result line: {exc}")

    # --- failed / unfinished requests live in the error file (fix #2) ---
    failed_custom_ids = set()
    if state.get("error_file_id"):
        print(f"\nDownloading error file {state['error_file_id']}...", end=" ", flush=True)
        err_records, err_bad = _download_jsonl(state["error_file_id"])
        print(f"{len(err_records)} records")
        bad_lines += err_bad
        failed_custom_ids = _failed_custom_ids(err_records)
        seen |= {r.get("custom_id") for r in err_records if r.get("custom_id")}
        for rec in err_records:
            stem = custom_to_stem.get(rec.get("custom_id"), rec.get("custom_id"))
            print(f"  [FAILED] {stem}: {_error_message(rec)}")

    # --- reconcile: requests we submitted but never got any record back for ---
    missing = expected - seen

    # Everything that needs resubmitting: hard failures, unusable responses, and
    # anything that never came back. Persisted so retry can act on it regardless of
    # whether it re-harvests (#5, fix #2).
    needs_retry = failed_custom_ids | incomplete_custom_ids | missing

    print(f"\n{'─'*60}")
    print(f"Results     : {success} success,  {len(failed_custom_ids)} failed,  "
          f"{len(incomplete_custom_ids)} incomplete,  {len(missing)} missing")
    if bad_lines:
        print(f"Skipped     : {bad_lines} unparseable/unprocessable line(s)")
    print(f"Total cost  : ${total_cost:.4f}  (batch rates, 50% off standard)")
    per_page    = total_cost / success if success else 0
    est_1200    = per_page * 1200
    print(f"Per page    : ${per_page:.4f}  →  est. ${est_1200:.0f} for 1,200 pages")
    print(f"Output dir  : {output_dir}")

    if missing:
        print(f"\n{len(missing)} request(s) had neither an output nor an error record:")
        for cid in sorted(missing):
            print(f"  {custom_to_stem.get(cid, cid)}")

    if suggest_retry and needs_retry:
        print(f"\n→ Resubmit the {len(needs_retry)} unfinished request(s): "
              f"python batch_transcribe.py retry --job {state['job_name']}")

    state["status"]      = "fetched"
    state["needs_retry"] = sorted(needs_retry)
    _save_state(state)

    return {
        "success":               success,
        "failed_custom_ids":     failed_custom_ids,
        "incomplete_custom_ids": incomplete_custom_ids,
        "missing_custom_ids":    missing,
        "needs_retry":           needs_retry,
        "total_cost":            total_cost,
    }


def cmd_fetch(args):
    state = _load_state(args.job)

    # Accept 'completed', 'expired', OR 'cancelled' — all three still expose the
    # partial output for requests that finished (fix #1; cancelled added 2026-07-04
    # so a batch cancelled to stop a retry storm still yields its completed pages).
    if state["status"] not in ("completed", "expired", "cancelled"):
        print("Checking batch status first...")
        batch = client.batches.retrieve(state["batch_id"])
        if batch.status not in ("completed", "expired", "cancelled"):
            print(f"Batch is '{batch.status}' — not ready to fetch yet.")
            if batch.status == "failed":
                _print_batch_errors(batch)          # surface validation errors (fix #3)
            counts = batch.request_counts
            if counts:
                print(f"Progress: {counts.completed}/{counts.total} completed, {counts.failed} failed")
            return
        if batch.status in ("expired", "cancelled"):
            print(f"Batch {batch.status} — harvesting the requests that completed before it stopped.")
        state["status"]         = batch.status
        state["output_file_id"] = batch.output_file_id
        state["error_file_id"]  = batch.error_file_id
        _save_state(state)

    if not state.get("output_file_id") and not state.get("error_file_id"):
        sys.exit("No output_file_id or error_file_id in state. Something went wrong with the batch.")

    _harvest_results(state, run_phase2=args.run_phase2)
    _safe_update_ledger(state.get("batch_id"))


# ---------------------------------------------------------------------------
# Stage 5: retry — resubmit only the failed requests
# ---------------------------------------------------------------------------

def cmd_retry(args):
    state = _load_state(args.job)

    if not state.get("batch_id"):
        sys.exit("No batch_id in state. Run submit first.")

    # Ensure we have current batch status
    batch = client.batches.retrieve(state["batch_id"])
    if batch.status not in ("completed", "failed", "expired", "cancelled"):
        print(f"Batch is still '{batch.status}' — wait for it to finish before retrying.")
        return

    if batch.status == "failed":
        _print_batch_errors(batch)                  # surface validation errors (fix #3)

    # Save any results that DID complete before we repoint the job to a new batch.
    # Otherwise the completed subset of an expired/partial batch is lost when we
    # null out output_file_id below (fix #1). Reuse the harvest to also identify
    # exactly which requests need resubmitting (fix #2).
    custom_to_stem = {info["custom_id"]: stem for stem, info in state["images"].items()}
    if state.get("status") != "fetched":
        state["output_file_id"] = batch.output_file_id
        state["error_file_id"]  = batch.error_file_id
        _save_state(state)
        if batch.output_file_id or batch.error_file_id:
            print("Saving results from the current batch before retrying...\n")
            _harvest_results(state, run_phase2=False, suggest_retry=False)
            print()

    # Harvest records exactly which requests need resubmitting (failed + incomplete
    # + missing) in state["needs_retry"]. Fall back to the error file only for state
    # files written before that key existed.
    if state.get("needs_retry") is not None:
        failed_custom_ids = set(state["needs_retry"])
    else:
        error_file_id = batch.error_file_id
        if not error_file_id:
            print("No error file on this batch — nothing to retry.")
            return
        print(f"Reading error file ({error_file_id})...", end=" ", flush=True)
        error_lines, _ = _download_jsonl(error_file_id)
        print(f"{len(error_lines)} records")
        failed_custom_ids = _failed_custom_ids(error_lines)

    if not failed_custom_ids:
        print("No unfinished requests to retry — nothing to do.")
        return

    # Map custom_id back to image stem
    failed_stems = [custom_to_stem[cid] for cid in failed_custom_ids if cid in custom_to_stem]

    print(f"\nRequests to resubmit ({len(failed_stems)}):")
    for stem in failed_stems:
        print(f"  {stem}")

    # Same guard as submit: a blind retry into a near-empty balance is exactly
    # what turned the 2026-07-03 run into a second retry storm.
    _preflight_balance_check(len(failed_stems), state["config"]["model"], args)

    # Load the same prompt the job was originally prepared with, so a retry
    # never silently switches prompts out from under an in-flight job (falls
    # back to first-found for state files predating the prompt_file key).
    cfg    = state["config"]
    prompt_file = (PROMPT_DIR / cfg["prompt_file"]) if cfg.get("prompt_file") else _resolve_prompt(None)
    prompt_text = prompt_file.read_text(encoding="utf-8")

    use_ci = cfg["use_ci"]
    tools  = [{"type": "code_interpreter", "container": {"type": "auto"}}] if use_ci else []

    # Build retry JSONL with only the failed requests
    retry_jsonl_path = JOBS_DIR / f"{args.job}_retry.jsonl"
    with retry_jsonl_path.open("w", encoding="utf-8") as fh:
        for stem in failed_stems:
            info = state["images"][stem]
            line = {
                "custom_id": info["custom_id"],
                "method":    "POST",
                "url":       "/v1/responses",
                "body": {
                    "model":     cfg["model"],
                    "reasoning": {"effort": cfg["effort"]},
                    "tools":     tools,
                    "input": [{
                        "role": "user",
                        "content": [
                            {"type": "input_text",  "text": prompt_text},
                            {"type": "input_image", "file_id": info["file_id"], "detail": "high"},
                        ],
                    }],
                },
            }
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    # Submit retry batch
    print(f"\nUploading retry JSONL ({len(failed_stems)} requests)...", end=" ", flush=True)
    with retry_jsonl_path.open("rb") as fh:
        upload = client.files.create(file=fh, purpose="batch")
    print(upload.id)

    print("Creating retry batch...", end=" ", flush=True)
    retry_batch = client.batches.create(
        input_file_id=upload.id,
        endpoint="/v1/responses",
        completion_window="24h",
    )
    print(retry_batch.id)

    # Update state: preserve previous batch history, point to new batch
    state.setdefault("previous_batches", [])
    state["previous_batches"].append({
        "batch_id":   state["batch_id"],
        "status":     batch.status,
        "n_retried":  len(failed_stems),
        "retried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    state["batch_id"]       = retry_batch.id
    state["jsonl_file_id"]  = upload.id
    state["status"]         = "submitted"
    state["output_file_id"] = None
    state["error_file_id"]  = None
    state["completed_at"]   = None
    state["needs_retry"]    = None   # belongs to the previous batch; clear it
    _save_state(state)

    print(f"\nRetry batch submitted with {len(failed_stems)} request(s).")
    print(f"Check status → python batch_transcribe.py status --job {args.job}")

    _safe_update_ledger()   # record the previous batch's harvested outcome


# ---------------------------------------------------------------------------
# Stage 6: watch — live cost watchdog
# ---------------------------------------------------------------------------

def cmd_watch(args):
    if getattr(args, "selftest", False):
        sys.exit(_watchdog_selftest())

    # Resolve batch_id + model, from a job state file or directly from CLI.
    state = None
    if args.job:
        state    = _load_state(args.job)
        batch_id = state.get("batch_id")
        if not batch_id:
            sys.exit(f"Job '{args.job}' has no batch_id yet — submit first.")
        model = state["config"]["model"]
        label = args.job
    elif args.batch_id:
        batch_id = args.batch_id
        model    = args.model or DEFAULT_MODEL
        label    = batch_id
    else:
        sys.exit("Provide --job, or --batch-id (+ --model) to watch an arbitrary batch.")

    # Build the threshold config from defaults + any per-run overrides.
    cfg = dict(WATCHDOG_DEFAULTS)
    for attr, key in [("per_page_expected","per_page_expected"), ("fail_ratio","fail_ratio"),
                      ("fail_min","fail_min"), ("fail_abs","fail_abs"),
                      ("exec_multiplier","exec_multiplier"), ("cost_per_page","cost_per_page_mult"),
                      ("stall_minutes","stall_minutes")]:
        val = getattr(args, attr, None)
        if val is not None:
            cfg[key] = val
    if args.max_spend is not None:
        cfg["max_spend"] = args.max_spend
    interval_base = args.interval or cfg["interval_base"]

    enabled = set(WATCHDOG_GUARDRAILS)
    if args.disable:
        enabled -= {t.strip() for t in args.disable.split(",") if t.strip()}

    # Cost-based guardrails need the admin key; degrade gracefully without it.
    if not ADMIN_KEY:
        dropped = enabled & {"storm", "cost-per-page", "spend", "stall"}
        enabled -= dropped
        if dropped:
            print("⚠  OPENAI_ADMIN_API_KEY not set — cost-based guardrails "
                  f"({', '.join(sorted(dropped))}) disabled; running failure-ratio only.\n")

    LOGS_DIR.mkdir(exist_ok=True)
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"watchdog_{label}_{ts}.log"
    def log(line):
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    print(f"Watchdog  : {label}  (batch {batch_id}, model {model})")
    print(f"Guardrails: {', '.join(sorted(enabled)) or 'NONE'}   on-trip: {args.on_trip}")
    print(f"Log       : {log_path}\n")
    log(f"# watchdog start {ts} batch={batch_id} model={model} "
        f"guardrails={sorted(enabled)} on_trip={args.on_trip} cfg={cfg}")

    TERMINAL = {"completed", "failed", "expired", "cancelled"}
    handled  = False          # already alerted/cancelled — stop re-evaluating
    cancelling = False
    batch = None

    while True:
        try:
            batch = client.batches.retrieve(batch_id)
        except Exception as exc:
            print(f"  [poll error] {exc}")
            time.sleep(interval_base)
            continue

        status  = batch.status
        counts  = batch.request_counts
        total     = counts.total     if counts else 0
        completed = counts.completed if counts else 0
        failed    = counts.failed    if counts else 0
        created   = batch.created_at
        now       = datetime.datetime.now(datetime.timezone.utc).timestamp()
        elapsed_min = (now - created) / 60 if created else 0

        # Lagging cost/execution signal — only when a risk cue is present (efficiency).
        execs = cost = None
        risk_cue = failed > 0 or completed > 0 or elapsed_min > 3
        if ADMIN_KEY and (enabled & {"storm","cost-per-page","spend","stall"}) and risk_cue:
            usage = _admin_usage_since(created)
            if usage:
                execs, in_tok, out_tok = usage
                cost, *_ = _cost_line(in_tok, out_tok, 0, model, batch=True)

        snap = {"total": total, "completed": completed, "failed": failed,
                "execs": execs, "live_cost": cost, "elapsed_min": elapsed_min}

        cost_s = f"${cost:.2f}" if cost is not None else "n/a"
        exec_s = str(execs) if execs is not None else "n/a"
        line = (f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {status:11} "
                f"{completed}/{total} done, {failed} failed | execs {exec_s} | "
                f"billed {cost_s} | {elapsed_min:.0f}m")
        print("  " + line); log(line)

        if status in TERMINAL:
            print(f"\nBatch reached terminal state: {status}")
            log(f"# terminal {status}")
            break

        # Evaluate guardrails until we've acted once.
        if not handled:
            trips = _evaluate_guardrails(snap, cfg, enabled)
            if trips:
                reason = "; ".join(f"[{n}] {m}" for n, m in trips)
                log(f"# TRIP {reason}")
                _notify("Batch watchdog TRIPPED", reason, quiet=args.quiet)

                if args.on_trip == "alert":
                    print("  → alert-only mode; NOT cancelling. You decide.")
                    handled = True
                else:
                    if args.on_trip == "grace":
                        print("  → cancelling in 60s unless you press Ctrl-C to abort...")
                        try:
                            time.sleep(60)
                        except KeyboardInterrupt:
                            print("  Cancel aborted — continuing to watch (guardrails muted).")
                            log("# grace cancel aborted by user")
                            handled = True
                            time.sleep(interval_base)
                            continue
                    print("  → CANCELLING batch to stop the burn.")
                    try:
                        client.batches.cancel(batch_id)
                        log("# cancel issued")
                        cancelling = True
                    except Exception as exc:
                        print(f"  cancel error: {exc}")
                        log(f"# cancel error {exc}")
                    handled = True

        if batch.expires_at and now > batch.expires_at:
            print("Batch past expiry — stopping watch.")
            break

        time.sleep(cfg["interval_risk"] if (risk_cue or cancelling) else interval_base)

    # Final billed cost.
    if ADMIN_KEY and batch is not None and batch.created_at:
        usage = _admin_usage_since(batch.created_at)
        if usage:
            execs, in_tok, out_tok = usage
            cost, *_ = _cost_line(in_tok, out_tok, 0, model, batch=True)
            print(f"\nFinal billed (batch rate): ${cost:.2f}  |  {execs} executions  |  "
                  f"{in_tok:,} in / {out_tok:,} out")
            log(f"# final ${cost:.2f} execs={execs} in={in_tok} out={out_tok}")

    # Harvest completed results (only possible with a job state file).
    if state is not None and not args.no_fetch and batch is not None \
            and batch.status in ("completed", "expired", "cancelled"):
        state["status"]         = batch.status
        state["output_file_id"] = batch.output_file_id
        state["error_file_id"]  = batch.error_file_id
        _save_state(state)
        print("\nHarvesting completed results...")
        _harvest_results(state, run_phase2=False, suggest_retry=False)
    elif state is None and not args.no_fetch:
        print("\n(no job state — skipping harvest; run `fetch --job <name>` to save results)")

    _safe_update_ledger(state.get("batch_id") if state else batch_id)


# ---------------------------------------------------------------------------
# Ledger — one durable record of every batch, its cost, executions, scan status
# ---------------------------------------------------------------------------
# The ledger is GENERATED from source-of-truth (the /v1/batches list, each batch's
# output/error files, the Admin usage/costs API, and local job state) — never
# hand-edited — so it can't drift. Each batch's billed figures are FROZEN once
# captured, because OpenAI's hourly usage granularity ages after ~a day. New
# batches are captured fresh (in-pipeline, at fetch/watch/retry) and frozen.
LEDGER_JSON = BASE / "reports" / "batch_ledger.json"
LEDGER_MD   = BASE / "reports" / "batch_ledger.md"

# Frozen billed figures for historical batches, captured while the Admin hourly
# usage data was still fresh (see reports/batch-overbilling-report_*). The five
# 2026-07-01/02 test batches incurred $0 (confirmed via the costs API).
LEDGER_SEED = {
    "batch_6a4549480b908190a5310197baa7bb34": {"execs": 0,  "in": 0,        "out": 0},
    "batch_6a455ac38db08190b3c8ed7310654098": {"execs": 0,  "in": 0,        "out": 0},
    "batch_6a45658b3d188190952a6b6b9680c68f": {"execs": 0,  "in": 0,        "out": 0},
    "batch_6a45f2ff21d4819085964983b5d5c697": {"execs": 0,  "in": 0,        "out": 0},
    "batch_6a45f30280c08190a9e293ce45ee865d": {"execs": 0,  "in": 0,        "out": 0},
    "batch_6a482b22b14481909cb74e9a61327845": {"execs": 25, "in": 1_273_853, "out": 588_591},
    "batch_6a4858b31da081909c6abab3c42a7e74": {"execs": 37, "in": 2_082_425, "out": 876_053},
    "batch_6a48a41f79348190a4b9921d50adad51": {"execs": 27, "in": 1_454_322, "out": 671_733},
    "batch_6a4a88b1fe808190932d7f6118aff131": {"execs": 8,  "in": 442_875,   "out": 217_752},
}
TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


def _pricing_key(model_str):
    """Map a dated model id ('gpt-5.5-2026-04-23') to a MODEL_PRICING key ('gpt-5.5')."""
    for k in MODEL_PRICING:
        if model_str and model_str.startswith(k):
            return k
    return "gpt-5.5"


# Synchronous (non-batch) runs from transcribe.py are logged as
# "<stem>_<date>_<time>_<effort>_CI-<on|off>_raw.json" (batch harvests use the
# distinct "..._batch_raw.json" suffix, excluded below).
_SYNC_LOG_RE = re.compile(
    r"^(?P<stem>.+?)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<effort>\w+)_CI-(?P<ci>on|off)_raw\.json$")


def _scan_sync_logs():
    """Per-request records of synchronous /v1/responses runs, parsed from the raw
    JSON logs. Priced at STANDARD (non-batch) rates. Durable + local."""
    out = []
    for p in sorted(LOGS_DIR.glob("*_raw.json")):
        if p.name.endswith("_batch_raw.json"):
            continue
        m = _SYNC_LOG_RE.match(p.name)
        if not m:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        u  = data.get("usage") or {}
        it = u.get("input_tokens", 0) or 0
        ot = u.get("output_tokens", 0) or 0
        rt = (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        pkey = _pricing_key(data.get("model", "") or "")
        cost, *_ = _cost_line(it, ot, rt, pkey, batch=False)   # synchronous = full standard rate
        out.append({"stem": m.group("stem"),
                    "when": f"{m.group('date')}_{m.group('time')}",
                    "effort": m.group("effort"), "ci": m.group("ci"), "model": pkey,
                    "in": it, "out": ot, "cost": round(cost, 4), "file": p.name})
    return out


def _batchid_meta():
    """Map every known batch_id (current + previous_batches) to its job metadata
    from the local state files, so the ledger can name batches and show config."""
    meta = {}
    for p in sorted(JOBS_DIR.glob("*.json")):
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        cfg = st.get("config", {}) or {}
        info = {"job": st.get("job_name", p.stem),
                "model": cfg.get("model"), "effort": cfg.get("effort"),
                "ci": cfg.get("use_ci")}
        if st.get("batch_id"):
            meta[st["batch_id"]] = info
        for prev in st.get("previous_batches", []) or []:
            if prev.get("batch_id"):
                meta[prev["batch_id"]] = info
    return meta


def _ledger_scan_status(batch):
    """Per-scan status for a batch from its output (completed, with tokens) and
    error (failed, with reason) files. Returns {stem: {...}}. Empty if the files
    are gone (they expire) — status then falls back to counts only."""
    scans = {}
    pkey  = _pricing_key(getattr(batch, "model", "") or "")
    if getattr(batch, "output_file_id", None):
        try:
            recs, _ = _download_jsonl(batch.output_file_id)
            for r in recs:
                cid  = r.get("custom_id") or ""
                stem = cid[4:] if cid.startswith("req-") else cid
                body = (r.get("response") or {}).get("body") or {}
                u    = body.get("usage") or {}
                it, ot = u.get("input_tokens", 0), u.get("output_tokens", 0)
                cost, *_ = _cost_line(it, ot, 0, pkey, batch=True)
                scans[stem] = {"status": "completed", "reason": "",
                               "in": it, "out": ot, "cost": round(cost, 4)}
        except Exception:
            pass
    if getattr(batch, "error_file_id", None):
        try:
            recs, _ = _download_jsonl(batch.error_file_id)
            for r in recs:
                cid  = r.get("custom_id") or ""
                stem = cid[4:] if cid.startswith("req-") else cid
                scans[stem] = {"status": "failed", "reason": _error_message(r)[:90],
                               "in": 0, "out": 0, "cost": 0.0}
        except Exception:
            pass
    return scans


def _batch_finished_ts(batch):
    for attr in ("completed_at", "cancelled_at", "expired_at", "failed_at"):
        v = getattr(batch, attr, None)
        if v:
            return v
    return None


def _build_batch_entry(batch, meta, stored):
    """Assemble one ledger entry. Billed source priority: seed > frozen stored >
    live bounded Admin query. Terminal batches with billing are marked frozen."""
    bid    = batch.id
    rc     = batch.request_counts
    info   = meta.get(bid, {})
    pkey   = _pricing_key(getattr(batch, "model", "") or info.get("model") or "")
    status = batch.status

    # Billed figures.
    if bid in LEDGER_SEED:
        s = LEDGER_SEED[bid]; execs, itok, otok, src = s["execs"], s["in"], s["out"], "seed"
    elif stored and stored.get("frozen"):
        execs, itok, otok, src = stored["execs"], stored["in"], stored["out"], "frozen"
    else:
        usage = _admin_usage_since(batch.created_at, _batch_finished_ts(batch))
        if usage:
            execs, itok, otok, src = usage[0], usage[1], usage[2], "live"
        else:
            execs = itok = otok = 0; src = "unavailable"
    billed, *_ = _cost_line(itok, otok, 0, pkey, batch=True)

    scans = _ledger_scan_status(batch)
    completed_cost = round(sum(v["cost"] for v in scans.values() if v["status"] == "completed"), 4)

    return {
        "batch_id":  bid,
        "job":       info.get("job", ""),
        "created":   batch.created_at,
        "finished":  _batch_finished_ts(batch),
        "status":    status,
        "model":     pkey,
        "effort":    info.get("effort"),
        "ci":        info.get("ci"),
        "submitted": rc.total if rc else 0,
        "completed": rc.completed if rc else 0,
        "failed":    rc.failed if rc else 0,
        "execs":     execs,
        "in":        itok,
        "out":       otok,
        "billed":    round(billed, 4),
        "billed_source": src,
        "completed_cost": completed_cost,
        "scans":     scans,
        "frozen":    status in TERMINAL_STATUSES and src in ("seed", "frozen", "live"),
    }


def _costs_totals():
    """(batch_total, nonbatch_total) $ from the durable Admin costs API, all history."""
    if not ADMIN_KEY:
        return None, None
    q = urllib.parse.urlencode({"start_time": 1777000000, "bucket_width": "1d",
                                "limit": 180}) + "&group_by=line_item"
    url = "https://api.openai.com/v1/organization/costs?" + q
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {ADMIN_KEY}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except Exception:
        return None, None
    batch_t = nonbatch_t = 0.0
    for bk in data.get("data", []):
        for res in bk.get("results", []):
            v  = float((res.get("amount") or {}).get("value", 0) or 0)
            li = res.get("line_item", "") or ""
            if li.startswith("batch"):
                batch_t += v
            else:
                nonbatch_t += v
    return round(batch_t, 2), round(nonbatch_t, 2)


def _render_ledger_md(ledger):
    entries = sorted(ledger["batches"].values(), key=lambda e: e["created"])
    def ts(t): return datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "—"

    tot_sub = sum(e["submitted"] for e in entries)
    tot_com = sum(e["completed"] for e in entries)
    tot_fail= sum(e["failed"]    for e in entries)
    tot_ex  = sum(e["execs"]     for e in entries)
    tot_in  = sum(e["in"]        for e in entries)
    tot_out = sum(e["out"]       for e in entries)
    tot_bill= round(sum(e["billed"] for e in entries), 2)
    batch_c, nonbatch_c = ledger.get("costs_batch"), ledger.get("costs_nonbatch")

    # Per-scan aggregation. Two honest cost views per scan:
    #   out_cost = spend that produced SAVED output (exact, from completed records)
    #   est_cost = an even share of each batch's FULL bill per submitted request
    #              (so collective retry-storm waste is shared, not dumped on the
    #              failed scans) — sums across all scans back to total spend.
    def _blank(): return {"attempts": 0, "completed": 0, "failed": 0,
                          "out_cost": 0.0, "est_cost": 0.0, "hist": []}
    idx = {}
    for e in entries:
        even  = e["billed"] / e["submitted"] if e["submitted"] else 0.0
        label = e["job"] or e["batch_id"][:18]
        for stem, s in e["scans"].items():
            d = idx.setdefault(stem, _blank())
            d["attempts"] += 1
            d["est_cost"] += even
            if s["status"] == "completed":
                d["completed"] += 1; d["out_cost"] += s["cost"]
                d["hist"].append(f"{label}:✓${s['cost']:.2f}")
            else:
                d["failed"] += 1
                d["hist"].append(f"{label}:✗({s['reason'] or 'failed'})")

    # Fold synchronous (non-batch) runs in — completed attempts at standard rates
    # (no storm overhead, so out_cost == est_cost == the run's own cost).
    sync = ledger.get("sync", [])
    sync_total = round(sum(s["cost"] for s in sync), 2)
    for s in sync:
        d = idx.setdefault(s["stem"], _blank())
        d["attempts"]  += 1
        d["completed"] += 1
        d["out_cost"]  += s["cost"]
        d["est_cost"]  += s["cost"]
        d["hist"].append(f"sync[{s['effort']}]:✓${s['cost']:.2f}")

    L = []
    L.append("# OpenAI Batch Ledger")
    L.append(f"_Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} — regenerated automatically; do not hand-edit._\n")
    L.append("## Totals")
    L.append(f"- **Batches:** {len(entries)}")
    L.append(f"- **Requests:** {tot_sub} submitted · {tot_com} completed · {tot_fail} failed")
    ratio = f"{tot_ex/tot_sub:.2f}×" if tot_sub else "—"
    L.append(f"- **Model executions billed:** {tot_ex}  (overhead {ratio} vs. submitted)")
    L.append(f"- **Tokens:** {tot_in:,} in / {tot_out:,} out")
    L.append(f"- **Batch API spend (sum of entries):** ${tot_bill:,.2f}")
    L.append(f"- **Synchronous (non-batch) spend, from {len(sync)} run logs:** ${sync_total:,.2f}")
    if batch_c is not None:
        L.append(f"- **Batch API spend (costs API, authoritative):** ${batch_c:,.2f}")
        L.append(f"- **Non-batch spend (costs API, authoritative):** ${nonbatch_c:,.2f}")
        L.append(f"- **GRAND TOTAL (all API spend):** ${batch_c + nonbatch_c:,.2f}")
        gap = tot_bill - batch_c
        if gap > 1.0:
            L.append(f"\n> _Sum-of-entries batch spend (${tot_bill:,.2f}) exceeds the authoritative "
                     f"costs-API total (${batch_c:,.2f}) by ~${gap:,.2f}. That gap is OpenAI "
                     f"**refunds/credits** applied after the original billing._")
    L.append("")

    L.append("## Per-scan index")
    L.append("_\"How many times did FN-XXXX fail?\" → read its row. **Output $** = spend that "
             "produced saved output; **Est. total $** = even share of each batch's full bill "
             "(includes shared retry-storm waste)._\n")
    L.append("| Scan | Attempts | Completed | Failed | Output $ | Est. total $ | History |")
    L.append("|---|---|---|---|---|---|---|")
    for stem in sorted(idx):
        d = idx[stem]
        L.append(f"| {stem} | {d['attempts']} | {d['completed']} | {d['failed']} | "
                 f"${d['out_cost']:.2f} | ${d['est_cost']:.2f} | {' · '.join(d['hist'])} |")
    L.append("")

    if sync:
        # Group synchronous runs by scan for a compact summary.
        by_scan = {}
        for s in sync:
            g = by_scan.setdefault(s["stem"], {"runs": 0, "cost": 0.0, "cfgs": set()})
            g["runs"] += 1; g["cost"] += s["cost"]
            g["cfgs"].add(f"{s['effort']}/{'CI' if s['ci']=='on' else 'no-CI'}")
        L.append("## Synchronous (non-batch) requests")
        L.append(f"_{len(sync)} runs, ${sync_total:,.2f} total — priced at full standard rates._\n")
        L.append("| Scan | Runs | Configs | Total $ |")
        L.append("|---|---|---|---|")
        for stem in sorted(by_scan):
            g = by_scan[stem]
            L.append(f"| {stem} | {g['runs']} | {', '.join(sorted(g['cfgs']))} | ${g['cost']:.2f} |")
        L.append("")

    L.append("## Per-batch detail")
    for e in sorted(entries, key=lambda x: x["created"], reverse=True):
        cfg = f"{e['model']} {e['effort'] or '?'} {'CI' if e['ci'] else 'no-CI'}"
        r   = f"{e['execs']/e['submitted']:.2f}×" if e["submitted"] else "—"
        L.append(f"### {ts(e['created'])} · {e['job'] or '(no job)'} · `{e['batch_id']}`")
        L.append(f"- status **{e['status']}** | {cfg} | finished {ts(e['finished'])}")
        L.append(f"- {e['submitted']} submitted · {e['completed']} completed · {e['failed']} failed")
        L.append(f"- **{e['execs']} executions** ({r}) · {e['in']:,} in / {e['out']:,} out · "
                 f"**${e['billed']:.2f}** billed ({e['billed_source']})")
        if e["scans"]:
            parts = []
            for stem in sorted(e["scans"]):
                s = e["scans"][stem]
                parts.append(f"{stem} ✓${s['cost']:.2f}" if s["status"] == "completed"
                             else f"{stem} ✗({s['reason'] or 'failed'})")
            L.append(f"- scans: {' | '.join(parts)}")
        L.append("")
    return "\n".join(L)


def _update_ledger(only_batch_id=None, full=False):
    """Refresh the ledger. `full` re-lists every batch (backfill); otherwise only
    `only_batch_id` is (re)captured. Always re-renders the Markdown from the full
    stored JSON. Returns the ledger dict."""
    LEDGER_JSON.parent.mkdir(parents=True, exist_ok=True)
    ledger = json.loads(LEDGER_JSON.read_text(encoding="utf-8")) if LEDGER_JSON.exists() \
             else {"batches": {}}
    meta = _batchid_meta()

    if full:
        batches = _list_all_batches()
    elif only_batch_id:
        try:
            batches = [client.batches.retrieve(only_batch_id)]
        except Exception:
            batches = []
    else:
        batches = []

    for b in batches:
        stored = ledger["batches"].get(b.id)
        # Keep a frozen terminal entry unless doing a full rebuild.
        if stored and stored.get("frozen") and not full and b.id not in LEDGER_SEED:
            continue
        ledger["batches"][b.id] = _build_batch_entry(b, meta, stored)

    ledger["sync"] = _scan_sync_logs()
    bc, nbc = _costs_totals()
    if bc is not None:
        ledger["costs_batch"], ledger["costs_nonbatch"] = bc, nbc
    ledger["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    LEDGER_JSON.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    LEDGER_MD.write_text(_render_ledger_md(ledger), encoding="utf-8")
    return ledger


def _list_all_batches():
    out, after = [], None
    while True:
        page = client.batches.list(limit=100, after=after) if after else client.batches.list(limit=100)
        out += list(page.data)
        if getattr(page, "has_more", False) and page.data:
            after = page.data[-1].id
        else:
            break
    return out


def _safe_update_ledger(batch_id=None, full=False):
    """Never let a ledger refresh break the calling pipeline stage."""
    try:
        _update_ledger(only_batch_id=batch_id, full=full)
    except Exception as exc:
        print(f"  [ledger] skipped ({exc})")


def cmd_ledger(args):
    print("Rebuilding batch ledger from OpenAI + local state...")
    ledger = _update_ledger(full=True)
    n = len(ledger["batches"])
    bc, nbc = ledger.get("costs_batch"), ledger.get("costs_nonbatch")
    print(f"  {n} batches recorded.")
    if bc is not None:
        print(f"  Batch spend ${bc:,.2f} + non-batch ${nbc:,.2f} = ${bc+nbc:,.2f} total.")
    print(f"  Markdown : {LEDGER_MD}")
    print(f"  JSON     : {LEDGER_JSON}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        description="Batch transcription via OpenAI Batch API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # ── prepare ──────────────────────────────────────────────────────────────
    p_prep = sub.add_parser("prepare", help="Upload images, build JSONL, save job state")
    p_prep.add_argument("--model",        default=DEFAULT_MODEL,
                        help=f"Model (default: {DEFAULT_MODEL})")
    p_prep.add_argument("--effort",       default=DEFAULT_EFFORT,
                        choices=["low", "medium", "high"],
                        help=f"Reasoning effort (default: {DEFAULT_EFFORT})")
    p_prep.add_argument("--prompt",       type=str, default=DEFAULT_PROMPT,
                        help=f"Prompt filename stem/prefix in the prompt folder (default: '{DEFAULT_PROMPT}')")
    p_prep.add_argument("--no-ci",        action="store_true",
                        help="Disable Code Interpreter")
    p_prep.add_argument("--scan-dir",     type=Path, default=None,
                        help="Directory of images (default: scans/)")
    p_prep.add_argument("--image",        type=str, default=None,
                        help="Single image filename/stem (overrides --scan-dir)")
    p_prep.add_argument("--start",        type=str, default=None,
                        help="Image filename/stem to start from, e.g. FN-0006 (ignored with --image)")
    p_prep.add_argument("--limit",        type=int, default=None,
                        help="Max number of images to include, counted from --start if given")
    p_prep.add_argument("--job",          type=str, default=None,
                        help="Job name / state file stem (auto-generated if omitted)")
    p_prep.add_argument("--reuse-files",  action="store_true",
                        help="Skip re-uploading images already recorded in the state file")

    # ── submit ───────────────────────────────────────────────────────────────
    p_sub = sub.add_parser("submit", help="Upload JSONL and create batch")
    p_sub.add_argument("--job", required=True,
                       help="Job name (from prepare step)")
    p_sub.add_argument("--balance", type=float, default=None,
                       help="Your current available balance in USD; submit is blocked "
                            "unless it clears a conservative worst-case buffer (prompted if omitted)")
    p_sub.add_argument("--skip-balance-check", action="store_true",
                       help="Bypass the pre-submit balance guard (not recommended)")
    p_sub.add_argument("--watch", action="store_true",
                       help="Immediately launch the cost watchdog (default guardrails) after submitting")

    # ── status ───────────────────────────────────────────────────────────────
    p_sta = sub.add_parser("status", help="Check batch progress")
    p_sta.add_argument("--job", required=True,
                       help="Job name")

    # ── fetch ────────────────────────────────────────────────────────────────
    p_fet = sub.add_parser("fetch", help="Download results and save to output folders")
    p_fet.add_argument("--job", required=True,
                       help="Job name")
    p_fet.add_argument("--run-phase2", action="store_true",
                       help="Run Phase 2 normalization on each output immediately after saving")

    # ── retry ────────────────────────────────────────────────────────────────
    p_ret = sub.add_parser("retry", help="Resubmit only the failed requests from a completed batch")
    p_ret.add_argument("--job", required=True,
                       help="Job name")
    p_ret.add_argument("--balance", type=float, default=None,
                       help="Your current available balance in USD; retry is blocked "
                            "unless it clears a conservative worst-case buffer (prompted if omitted)")
    p_ret.add_argument("--skip-balance-check", action="store_true",
                       help="Bypass the pre-submit balance guard (not recommended)")

    # ── watch ────────────────────────────────────────────────────────────────
    p_wat = sub.add_parser("watch", help="Live cost watchdog: poll a running batch and "
                                         "auto-cancel on a runaway-cost / retry-storm signature")
    p_wat.add_argument("--job", help="Job name (resolves batch_id + model from state)")
    p_wat.add_argument("--batch-id", help="Watch an arbitrary batch by id (with --model)")
    p_wat.add_argument("--model", default=None, help=f"Model for --batch-id (default: {DEFAULT_MODEL})")
    p_wat.add_argument("--on-trip", choices=["cancel", "grace", "alert"], default="cancel",
                       help="Action when a guardrail trips (default: cancel = auto-cancel)")
    p_wat.add_argument("--max-spend", type=float, default=None,
                       help="Hard $ ceiling (default: auto from request count)")
    p_wat.add_argument("--per-page-expected", type=float, default=None,
                       help=f"Expected batch $/page (default: {WATCHDOG_DEFAULTS['per_page_expected']})")
    p_wat.add_argument("--fail-ratio", type=float, default=None,
                       help=f"Failed/total trip ratio (default: {WATCHDOG_DEFAULTS['fail_ratio']})")
    p_wat.add_argument("--fail-min", type=int, default=None,
                       help=f"Min failures before ratio applies (default: {WATCHDOG_DEFAULTS['fail_min']})")
    p_wat.add_argument("--fail-abs", type=int, default=None,
                       help=f"Absolute failure count trip (default: {WATCHDOG_DEFAULTS['fail_abs']})")
    p_wat.add_argument("--exec-multiplier", type=float, default=None,
                       help=f"executions/total storm trip (default: {WATCHDOG_DEFAULTS['exec_multiplier']})")
    p_wat.add_argument("--cost-per-page", type=float, default=None,
                       help=f"cost/completed trip = this × per-page (default: {WATCHDOG_DEFAULTS['cost_per_page_mult']})")
    p_wat.add_argument("--stall-minutes", type=int, default=None,
                       help=f"Min elapsed for the stall guardrail (default: {WATCHDOG_DEFAULTS['stall_minutes']})")
    p_wat.add_argument("--interval", type=int, default=None,
                       help=f"Base poll seconds (default: {WATCHDOG_DEFAULTS['interval_base']})")
    p_wat.add_argument("--disable", default=None,
                       help="Comma-separated guardrails to disable: " + ",".join(WATCHDOG_GUARDRAILS))
    p_wat.add_argument("--no-fetch", action="store_true",
                       help="Do not auto-harvest completed results when the batch ends")
    p_wat.add_argument("--quiet", action="store_true", help="Suppress macOS notification/sound")
    p_wat.add_argument("--selftest", action="store_true",
                       help="Replay the historical incidents through the guardrails and exit (no network)")

    # ── ledger ───────────────────────────────────────────────────────────────
    sub.add_parser("ledger", help="Rebuild the single cost/execution/scan-status ledger "
                                   "for every batch + synchronous run (reports/batch_ledger.md)")

    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()

    # Override scan dir if provided
    global SCANS_DIR
    if hasattr(args, "scan_dir") and args.scan_dir:
        SCANS_DIR = args.scan_dir

    dispatch = {
        "prepare": cmd_prepare,
        "submit":  cmd_submit,
        "status":  cmd_status,
        "fetch":   cmd_fetch,
        "retry":   cmd_retry,
        "watch":   cmd_watch,
        "ledger":  cmd_ledger,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
