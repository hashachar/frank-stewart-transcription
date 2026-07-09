# Frank Stewart Fieldnotes Transcription Pipeline

Scripts for transcribing scanned Bedouin fieldnotes (handwritten by Frank
Stewart) into Unicode text using the OpenAI API, then normalizing and
exporting the results.

## Pipeline overview

```
scans/*.jpg,png,...                       (page images)
        │
        ▼
PDF to PNG.py            (only needed if source pages start out as PDFs)
        │
        ▼
transcribe.py             ── Step 1: single-image transcription (Responses API)
batch_transcribe.py        ── Step 1 alt: many images at once (Batch API, 50% cheaper)
        │  writes interim-notation .txt to outputs/<config>/
        ▼
Phase 2 - Normalize Code.py  ── Step 2: interim notation → literal + normalized Unicode
        │  writes <stem>.<config>.literal.txt, .normalized.txt, .report.json
        ▼
Export MD and PDF.py      ── optional Step 3: .txt → .md / .pdf / .docx
        │
count_diacritics.py       ── QA: compares diacritic-detection counts across configs
                               (run on Step 1 output, any time before/after Step 2)
```

Everything is keyed off a `BASE` directory (the parent of `scripts/`), which
contains:

- `scans/` — source page images (or PDFs, for `PDF to PNG.py`)
- `prompt/` — the `.txt` prompt(s) sent to the model for Step 1
- `outputs/<config>/` — Step 1 transcriptions, auto-named by model/effort/CI
  settings (e.g. `gpt-5.5_effort-high_CI-on/`); Step 2 and Step 3 outputs are
  written alongside the Step 1 file they were derived from
- `logs/` — raw JSON API responses (one per request), for debugging/auditing
- `batch_jobs/` — job state (`<job-name>.json`) and JSONL request/response
  files for `batch_transcribe.py`

## Scripts

### `transcribe.py` — Step 1, single image

Sends one scan image + the prompt to the OpenAI Responses API and writes the
model's interim-notation transcription to `outputs/<config>/`. Interim
notation encodes every diacritic as a token like `a{macron}`, `t{dotbelow}`,
`{apostrophe-ayn}` — see the header of `Phase 2 - Normalize Code.py` for the
full table.

Also writes the raw API response JSON to `logs/` and prints token usage and
estimated cost.

```bash
python3 transcribe.py --image FN-6-001-050-1 --model gpt-5.5 --effort high
```

Key flags: `--model`, `--effort` (`none|low|medium|high|xhigh`), `--no-ci`
(disable Code Interpreter), `--image`, `--prompt`, `--outdir`,
`--max-tool-calls`.

### `batch_transcribe.py` — Step 1, batch of images

Same Step 1 transcription, but for many images at once via the OpenAI Batch
API (results within 24h, ~50% cheaper than `transcribe.py`). Runs as a
five-stage pipeline; state is persisted to `batch_jobs/<job-name>.json` so
each stage can be run independently and re-run safely.

**Fan-out model.** A job owns *many* independent OpenAI batches, not one.
`prepare` chunks the job's requests into groups of `--batch-size` and `submit`
creates one standalone batch per group, each with its own `batch_id`, files and
lifecycle. The default `--batch-size` is **1 — one request per batch** — for
maximum fault isolation: a failure or retry storm in one request can never touch
the others. OpenAI has no notion of "grouped" batches, so the association lives
only in the job state file (`state["batches"]`, a list of member batches). Every
later stage operates across the whole fleet.

1. `prepare` — upload images to the Files API, chunk into member batches
   (`--batch-size N`, default 1), build one JSONL per member, save job state
2. `submit` — create one OpenAI batch per member (fans out); resume-safe, and
   paces creation to stay under OpenAI's ~2,000-batches/hour cap
3. `status` — aggregate progress across the fleet (safe to run repeatedly)
4. `fetch` — download results from every finished member into
   `outputs/<config>/`; optionally chain into Step 2 normalization with
   `--run-phase2` (imports `process_file` from `Phase 2 - Normalize Code.py`)
5. `retry` — resubmit each member's failed / incomplete (truncated/refused/
   empty) / missing requests as fresh batches, capped at 3 attempts per request
   (`MAX_SCAN_ATTEMPTS`); requests past the cap are reported for the synchronous
   `transcribe.py` fallback instead of looping

The `watch` command is a **fleet cost watchdog**: it aggregates request counts
and billed cost across *all* of a job's batches and, on a runaway-cost /
retry-storm / systemic-failure signature, cancels every still-running batch.
The failure-ratio guardrail is meaningful only on the aggregate (it is
degenerate on any single one-request batch), which is why the watchdog watches
the fleet as one unit.

```bash
python3 batch_transcribe.py prepare --effort medium --job my-run   # 1 req/batch
python3 batch_transcribe.py prepare --effort medium --batch-size 25 --job my-run  # or chunks of 25
python3 batch_transcribe.py submit  --job my-run
python3 batch_transcribe.py status  --job my-run
python3 batch_transcribe.py fetch   --job my-run --run-phase2
python3 batch_transcribe.py retry   --job my-run   # if anything failed
python3 batch_transcribe.py watch   --job my-run   # optional live fleet watchdog
```

### `Phase 2 - Normalize Code.py` — Step 2, interim → Unicode

Converts a Step 1 `.txt` file (interim notation) into two parallel Unicode
versions, both derived from the same source so they stay aligned:

- **literal** — exactly what's physically on the page (line-over-d,
  s/S-acute, θ, original quote marks) — for eyeballing against the scan
- **normalized** — the scholarly form per the project's guideline PDFs
  (line-under-d → ḏ, s/S-acute → š/Š, θ → ṯ, ʿ/ʾ for ayn/hamza)

Also writes a `.report.json` sidecar with flags (any interim token it
couldn't map — never silently dropped) and per-symbol counts. Every symbol
mapping lives in the `PROFILES`/`RENDER_ORDER` tables at the top of the file,
so extending the notation means editing data, not logic.

```bash
python3 "Phase 2 - Normalize Code.py" outputs/gpt-5.5_effort-high_CI-on/FN-6-001-050-1_*.txt
python3 "Phase 2 - Normalize Code.py" --selftest   # run the built-in conversion test suite
```

Called both directly and as a library — `batch_transcribe.py`'s `fetch
--run-phase2` imports `process_file` from this file at runtime (it has a
non-standard filename, so this is done via `importlib`, not a normal import).

### `Export MD and PDF.py` — optional Step 3, export

Takes a Step 2 output `.txt` (literal or normalized, with `**bold**`
headings) and exports it to any combination of Markdown, PDF, and/or Word,
preserving line breaks and bold headings.

```bash
python3 "Export MD and PDF.py" outputs/.../FN-6-001-050-1.gpt-5.5_effort-high_CI-on.normalized.txt --md --pdf
```

Requires: `pip install markdown weasyprint python-docx`.

### `count_diacritics.py` — QA / comparison tool

Counts interim-notation diacritic tokens (structural markers like `{LB}`,
`{HEADING}` excluded) in one or more Step 1 output files, to sanity-check
transcription thoroughness before committing to a model/effort/CI config for
a large batch run. A config detecting far fewer marks than another on the
same page is likely under-transcribing; far more may mean over-detection.

```bash
python3 count_diacritics.py outputs/gpt-5.5_effort-high_CI-on/
python3 count_diacritics.py --all-configs        # compare every config folder under outputs/
python3 count_diacritics.py file1.txt file2.txt --out report.txt
```

### `PDF to PNG.py` — scan prep utility

Renders PDF page(s) to PNG at a given DPI (default 480), for when source
scans arrive as PDF rather than image files. Single-page PDFs → `X.png`;
multi-page PDFs → `X-01.png`, `X-02.png`, ... Also accepts a folder of PDFs.
Not part of the main pipeline flow above — a pre-processing step to get
images into `scans/` in the first place.

```bash
python3 "PDF to PNG.py" scan.pdf --dpi 600
python3 "PDF to PNG.py" path/to/pdf-folder --outdir scans/
```

Requires: `pip install pymupdf`.

## Setup

```bash
pip install openai python-dotenv markdown weasyprint python-docx pymupdf
```

Create a `.env` file in this directory (gitignored) with:

```
OPENAI_API_KEY=sk-...
```
