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
import sys
import json
import argparse
import datetime
import importlib.util
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# max_retries: the SDK retries transient failures (429 / 5xx / connection errors)
# with exponential backoff, so a blip doesn't abort a stage (#6).
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=1800.0, max_retries=5)

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
    prompt_files = list(PROMPT_DIR.glob("*.txt"))
    if not prompt_files:
        sys.exit(f"No prompt .txt file found in {PROMPT_DIR}")
    prompt_text = prompt_files[0].read_text(encoding="utf-8")
    print(f"Prompt      : {prompt_files[0].name}\n")

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

    # Expired batches still expose partial output — treat them as fetchable (fix #1)
    if batch.status in ("completed", "expired"):
        state["status"]         = batch.status
        state["completed_at"]   = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state["output_file_id"] = batch.output_file_id
        state["error_file_id"]  = batch.error_file_id
        _save_state(state)
        if batch.status == "expired":
            print(f"\nBatch expired before finishing. Partial results are available.")
        print(f"\nFetch results → python batch_transcribe.py fetch --job {args.job}")
    elif batch.status in ("failed", "cancelled"):
        state["status"] = batch.status
        _save_state(state)
        print(f"\nBatch ended with status: {batch.status}")
        if batch.status == "failed":
            _print_batch_errors(batch)              # surface validation errors (fix #3)
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

    # Accept 'completed' OR 'expired' — an expired batch still has partial output (fix #1)
    if state["status"] not in ("completed", "expired"):
        print("Checking batch status first...")
        batch = client.batches.retrieve(state["batch_id"])
        if batch.status not in ("completed", "expired"):
            print(f"Batch is '{batch.status}' — not ready to fetch yet.")
            if batch.status == "failed":
                _print_batch_errors(batch)          # surface validation errors (fix #3)
            counts = batch.request_counts
            if counts:
                print(f"Progress: {counts.completed}/{counts.total} completed, {counts.failed} failed")
            return
        if batch.status == "expired":
            print("Batch expired — harvesting the requests that completed before the deadline.")
        state["status"]         = batch.status
        state["output_file_id"] = batch.output_file_id
        state["error_file_id"]  = batch.error_file_id
        _save_state(state)

    if not state.get("output_file_id") and not state.get("error_file_id"):
        sys.exit("No output_file_id or error_file_id in state. Something went wrong with the batch.")

    _harvest_results(state, run_phase2=args.run_phase2)


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

    # Load prompt
    prompt_files = list(PROMPT_DIR.glob("*.txt"))
    if not prompt_files:
        sys.exit(f"No prompt .txt file found in {PROMPT_DIR}")
    prompt_text = prompt_files[0].read_text(encoding="utf-8")

    cfg    = state["config"]
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
    p_prep.add_argument("--model",        default="gpt-5.5",
                        help="Model (default: gpt-5.5)")
    p_prep.add_argument("--effort",       default="medium",
                        choices=["low", "medium", "high"],
                        help="Reasoning effort (default: medium)")
    p_prep.add_argument("--no-ci",        action="store_true",
                        help="Disable Code Interpreter")
    p_prep.add_argument("--scan-dir",     type=Path, default=None,
                        help="Directory of images (default: scans/)")
    p_prep.add_argument("--image",        type=str, default=None,
                        help="Single image filename/stem (overrides --scan-dir)")
    p_prep.add_argument("--limit",        type=int, default=None,
                        help="Max number of images to include (for test runs)")
    p_prep.add_argument("--job",          type=str, default=None,
                        help="Job name / state file stem (auto-generated if omitted)")
    p_prep.add_argument("--reuse-files",  action="store_true",
                        help="Skip re-uploading images already recorded in the state file")

    # ── submit ───────────────────────────────────────────────────────────────
    p_sub = sub.add_parser("submit", help="Upload JSONL and create batch")
    p_sub.add_argument("--job", required=True,
                       help="Job name (from prepare step)")

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
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
