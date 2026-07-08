#!/usr/bin/env python3
"""One-off overnight orchestrator (2026-07-05), manually triggered by the user.

Waits for the cancelled 7-scan batch to finalize, then:
  - runs the GENUINELY-failed scans synchronously (reliable path),
  - re-submits the watchdog-CANCELLED scans as a new batch,
  - runs the cost watchdog on that new batch (auto-cancel/harvest).

Launched under `caffeinate -i nohup ... &` so it survives terminal close and
prevents idle sleep for the whole run. No heartbeats. Logs to logs/overnight.log.
"""
import time, json, subprocess, urllib.request, datetime, sys
from pathlib import Path
from dotenv import dotenv_values

SCRIPTS  = Path("/Users/Yair/Documents/My Documents/Frank Stewart - Bedouin Transcription/Yair's Workflow/OpenAI_API/scripts")
PY       = "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
KEY      = dotenv_values(SCRIPTS / ".env")["OPENAI_API_KEY"]
OLD_BATCH = "batch_6a4b2edbc56c819092cd1ca72f05a5e5"
NEWJOB   = "batch-scans-18-26-retry"
PROMPT   = "Phase 1e"
OUTDIR   = "gpt-5.5_effort-high_CI-on"
BALANCE  = "75"        # >= the guard's requirement for the re-batch
TERM     = {"completed", "failed", "expired", "cancelled"}

def log(m): print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {m}", flush=True)
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": f"Bearer {KEY}"}), timeout=60))
def content(fid): return urllib.request.urlopen(urllib.request.Request(f"https://api.openai.com/v1/files/{fid}/content", headers={"Authorization": f"Bearer {KEY}"}), timeout=60).read().decode()
def stem_of(cid): return cid[4:] if cid and cid.startswith("req-") else cid
def run(args):
    log("RUN " + " ".join(args))
    rc = subprocess.run([PY] + args, cwd=str(SCRIPTS)).returncode
    log(f"   -> exit {rc}")
    return rc

# 1) Wait for the old batch to finalize.
log(f"waiting for {OLD_BATCH} to reach a terminal state...")
b = None
for _ in range(180):                      # up to 3h
    try:
        b = get(f"https://api.openai.com/v1/batches/{OLD_BATCH}")
    except Exception as e:
        log(f"poll error: {e}"); time.sleep(60); continue
    log(f"  status={b['status']}  counts={b['request_counts']}")
    if b["status"] in TERM:
        break
    time.sleep(60)
if not b or b["status"] not in TERM:
    log("old batch never finalized — aborting."); sys.exit(1)

# 2) Classify each scan: completed / genuinely-failed / watchdog-cancelled.
completed, real_failed, cancelled = set(), [], []
if b.get("output_file_id"):
    for line in content(b["output_file_id"]).strip().splitlines():
        completed.add(stem_of(json.loads(line).get("custom_id", "")))
if b.get("error_file_id"):
    for line in content(b["error_file_id"]).strip().splitlines():
        r = json.loads(line); stem = stem_of(r.get("custom_id", ""))
        body = (r.get("response") or {}).get("body") or {}
        msg = ((body.get("error") or {}).get("message") or "") if isinstance(body, dict) else ""
        (cancelled if "cancel" in msg.lower() else real_failed).append(stem)
log(f"completed={sorted(completed)}  real_failed={real_failed}  cancelled={cancelled}")

# 3) Synchronously run the genuinely-failed scans (reliable, no retry storm).
for stem in real_failed:
    run(["transcribe.py", "--image", stem, "--prompt", PROMPT, "--outdir", OUTDIR])

# 4) Re-batch the watchdog-cancelled scans under the cost watchdog.
if cancelled:
    for stem in cancelled:
        run(["batch_transcribe.py", "prepare", "--image", stem, "--job", NEWJOB])
    if run(["batch_transcribe.py", "submit", "--job", NEWJOB, "--balance", BALANCE]) == 0:
        # Foreground watch — auto-cancel on storm/stall + auto-harvest + ledger.
        # (caffeinate wraps THIS process, so sleep stays off for the whole watch.)
        run(["batch_transcribe.py", "watch", "--job", NEWJOB])
    else:
        log("submit failed (balance guard?) — NOT watching; check balance.")
else:
    log("no watchdog-cancelled scans to re-batch.")

# 5) Refresh the ledger and finish.
run(["batch_transcribe.py", "ledger"])
log("overnight orchestrator DONE.")
