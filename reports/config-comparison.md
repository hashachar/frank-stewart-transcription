# Configuration Comparison — Frank Stewart Bedouin Transcription
**Last updated:** 2026-07-02  
**Scans tested:** FN-6-001-050-1 through FN-6-001-050-5 (5 scans)  
**Models tested:** gpt-5.5, gpt-5.4  
**Effort levels tested:** low, medium, high; max_tool_calls cap: 5, 10, 25  
**Vision detail:** high | **Phase 2 normalization:** applied to all runs

> **Note on prompt versions:** Sections marked *(original prompt)* used the initial prompt (2 scans, FN-6-001-050-1 & 2). Sections marked *(revised prompt)* used the updated prompt run on all 5 scans.

---

## All Configurations Tested

### Cost — revised prompt, 5 scans (FN-6-001-050-1 through 5)

| Config | S1 | S2 | S3 | S4 | S5 | Avg/page | Batch/page | 1,200 standard | 1,200 batch |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.5 medium + CI on | $0.379 | $0.514 | $0.549 | $0.529 | $0.403 | $0.475 | $0.237 | $570 | **$285** |
| gpt-5.5 high + CI on   | $1.085 | $1.221 | $0.964 | $0.879 | $1.114 | $1.053 | $0.526 | $1,263 | **$632** |

### Cost — original prompt, 2 scans (FN-6-001-050-1 & 2, for reference)

| Config | Scan 1 | Scan 2 | Avg/page | Batch/page | 1,200 standard | 1,200 batch |
|---|---|---|---|---|---|---|
| gpt-5.5  **low**    + CI on  | $0.106 | $0.063 | $0.084 | $0.042 | $101 | **$51** |
| gpt-5.5  medium + CI off | $0.326 | $0.318 | $0.322 | $0.161 | $386 | **$193** |
| gpt-5.4  medium + CI on  | $0.439 | $0.394 | $0.417 | $0.208 | $500 | **$250** |
| gpt-5.5  medium + CI on  | $0.512 | $0.519 | $0.516 | $0.258 | $619 | **$310** |
| gpt-5.5  high   + CI off | $0.496 | $0.802 | $0.649 | $0.325 | $779 | **$390** |
| gpt-5.4  high   + CI on  | $0.658 | $0.709 | $0.684 | $0.342 | $820 | **$410** |
| gpt-5.5  high   + CI on  | $0.964 | $1.181 | $1.073 | $0.536 | $1,287 | **$644** |

Batch API = 50% off all token costs (async, non-time-sensitive workloads).

### Cost — gpt-5.4 medium + CI on with max_tool_calls cap (5 scans)

`max_tool_calls` caps how many Code Interpreter calls the model may make per request. The model hits the cap and stops zooming in further.

| Config | S1 | S2 | S3 | S4 | S5 | Avg/page | Batch/page | 1,200 standard | 1,200 batch |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.4 medium + CI on, max-calls-5  | $0.171 | $0.182 | $0.222 | $0.246 | $0.181 | $0.201 | $0.100 | $241 | **$120** |
| gpt-5.4 medium + CI on, max-calls-10 | $0.236 | $0.198 | $0.220 | $0.221 | $0.256 | $0.226 | $0.113 | $272 | **$136** |
| gpt-5.4 medium + CI on, max-calls-25 | $0.281 | $0.275 | $0.265 | $0.264 | $0.273 | $0.272 | $0.136 | $326 | **$163** |

Average CI calls actually made: 6 (max-5), 11 (max-10), 26 (max-25). The cap stops the model from making more — CI call counts closely track the cap.

### Revised vs. original prompt — cost comparison

| Config | Original avg/page | Revised avg/page | Change | Revised 1,200 batch |
|---|---|---|---|---|
| gpt-5.5 medium + CI on | $0.516 | $0.475 | −8% | **$285** (was $310) |
| gpt-5.5 high + CI on   | $1.073 | $1.053 | −2% | **$632** (was $644) |

The revised prompt is marginally more token-efficient. The $285 batch estimate for medium is now based on 5 scans and is the more reliable figure.

---

### Accuracy — Diacritical marks detected per scan

#### 5-scan comparison — revised prompt (FN-6-001-050-1 through 5)

| Config | S1 | S2 | S3 | S4 | S5 | Avg | Stacked marks |
|---|---|---|---|---|---|---|---|
| gpt-5.5 high + CI on   | 91 | **99** | 91 | 120 | 104 | **101.0** | 1 (scan 2) |
| gpt-5.5 medium + CI on | 90 | 85 | 90 | 122 | 103 | **98.0** | 1 (scan 4) |
| gpt-5.4 medium, max-calls-25 | 85 | 69 | 82 | 107 | 98 | 88.2 | 0 |
| gpt-5.4 medium, max-calls-5  | 80 | 74 | 83 | 108 | 96 | 88.2 | 0 |
| gpt-5.4 medium, max-calls-10 | 71 | 74 | 82 | 92 | 99 | 83.6 | 0 |

"Stacked marks" = `d{macron}{dotbelow}` (rule 4 character — line over d + dot under). Only gpt-5.5 detected these; base letter was **d** in both cases.

#### 2-scan results — original prompt (scans 1 & 2, for reference)

| Config | Scan 1 | Scan 2 | Assessment |
|---|---|---|---|
| gpt-5.5  medium + CI on  | 92 | **98** | matches high effort; **recommended baseline** |
| gpt-5.5  high   + CI on  | 90 | **98** | best accuracy; theta detected; no gain over medium |
| gpt-5.5  low    + CI on  | 85 | 81 | misses ~17 marks on scan 2; 1 malformed token flagged |
| gpt-5.5  high   + CI off | 93 | 83 | misses ~15 marks on scan 2 |
| gpt-5.5  medium + CI off | 94 | 81 | misses ~17 marks on scan 2 |
| gpt-5.4  high   + CI on  | 90 | 82 | 16 fewer marks than gpt-5.5 on scan 2 |
| gpt-5.4  medium + CI on  | 89 | 78 | 20 fewer marks than gpt-5.5 on scan 2 |

#### Mark-type breakdown (scan 2 — most discriminating)

| Config | `{dotbelow}` | `{macron}` | `{apostrophe-ayn}` | `{acute}` | Total |
|---|---|---|---|---|---|
| gpt-5.5 high + CI on   | 34 | 42 | 16 | 6 | **99** |
| gpt-5.5 medium + CI on | 28 | 34 | 16 | 6 | 85 |
| gpt-5.4 med, max-calls-25 | 20 | 26 | 17 | 5 | 69 |
| gpt-5.4 med, max-calls-5  | 19 | 29 | 19 | 6 | 74 |
| gpt-5.4 med, max-calls-10 | 20 | 32 | 16 | 6 | 74 |
| gpt-5.5 low + CI on    | 32 | 31 | 11 | 6 | 81 |
| gpt-5.4 high + CI on   | 21 | 38 | 16 | 6 | 82 |
| gpt-5.4 medium + CI on | 20 | 35 | 17 | 6 | 78 |
| gpt-5.5 high + CI off  | 24 | 37 | 16 | 6 | 83 |
| gpt-5.5 medium + CI off| 22 | 36 | 17 | 6 | 81 |

The `{dotbelow}` and `{macron}` marks are the most sensitive to effort level, model generation, and CI availability. They require zooming into fine details that a full-page view cannot reliably resolve.

---

## Key Findings

### 1. gpt-5.5 medium + CI on is the sweet spot
On both scans, medium effort with CI on matched high effort exactly (98 marks each on scan 2) at roughly half the cost. Increasing effort to high buys nothing measurable.

### 2. Low effort is dramatically cheaper but misses too many marks
`low` effort with CI on costs just $0.042/page at batch rates ($51 for 1,200 pages) — 6× cheaper than medium. However it drops to 81–85 marks detected vs 92–98 for medium/high, missing ~12–17 marks per page concentrated in `{macron}` and `{apostrophe-ayn}`. It also produced 1 malformed token on scan 2 (flagged by Phase 2). With `low` effort, the model makes very few CI crop calls (scan 2 used only 19 reasoning tokens — nearly zero deliberation), meaning it largely guesses from the full-page view alone. **Not recommended for this task.**

### 2. Removing Code Interpreter causes real accuracy loss
CI-off configs missed 15–17 marks on scan 2 vs CI-on, concentrated in `{dotbelow}` and `{macron}`. The model makes 20–34 crop calls per page (depending on effort level), zooming into ambiguous characters. Without this, it systematically misses fine diacritical marks.

### 3. gpt-5.4 is not a viable substitute
gpt-5.4 drops 16–20 diacritical marks per page on complex scans vs gpt-5.5. High effort on gpt-5.4 recovers only 4 marks vs medium — not enough to close the gap. The model generation matters more than effort level or cost savings.

### 4. CI renders are the dominant input cost driver
All CI crop calls share one container per response. The renders are fed back into the model's context as input tokens (not returned to the caller — `outputs: null` in the JSON log), which is why input token counts are high in CI-on runs:

| Config | Input tokens | Of which: CI renders |
|---|---|---|
| gpt-5.5 high + CI on | ~64,700 | ~60,700 |
| gpt-5.5 medium + CI on | ~28,300 | ~24,300 |
| gpt-5.5 high + CI off | ~4,000 | 0 |
| gpt-5.4 high + CI on | ~78,300 | ~75,100 |
| gpt-5.4 medium + CI on | ~62,400 | ~59,200 |

gpt-5.4 makes more CI crop calls than gpt-5.5 at the same effort level — partially explaining why it's not cheaper despite lower per-token rates.

### 5. Reasoning tokens dominate output cost (86–94% of output)
Visible transcription output is stable at ~1,200–1,400 tokens regardless of config. All remaining output tokens are internal reasoning.

### 6. Cost breakdown — gpt-5.5 medium + CI on (best config)

| Component | $/page | % of cost |
|---|---|---|
| Output + reasoning (~12,476 tokens) | $0.374 | 72.5% |
| CI renders fed back as input (~24,287 tokens) | $0.121 | 23.5% |
| Image input (~2,841 tokens) | $0.014 | 2.8% |
| Prompt text (~1,200 tokens) | $0.006 | 1.2% |

### 7. max_tool_calls cap: dramatic cost savings, moderate accuracy drop

Capping Code Interpreter calls with `max_tool_calls` on gpt-5.4 medium substantially reduces cost but also lowers accuracy:

| Config | Avg marks | vs gpt-5.5 med | Avg CI calls | Batch/page | 1,200 batch |
|---|---|---|---|---|---|
| gpt-5.5 medium + CI on | 98.0 | — | ~25.2 | $0.237 | $285 |
| gpt-5.5 high + CI on   | 101.0 | +3%  | ~46.2 | $0.526 | $632 |
| gpt-5.4 medium, max-calls-25 | 88.2 | −10% | 26 | $0.136 | **$163** |
| gpt-5.4 medium, max-calls-5  | 88.2 | −10% | 6  | $0.100 | **$120** |
| gpt-5.4 medium, max-calls-10 | 83.6 | −15% | 11 | $0.113 | **$136** |

Key observations:
- max-calls-5 and max-calls-25 tie in average accuracy (88.2) but max-calls-5 is 40% cheaper ($120 vs $163). The model does most of its useful zooming in the first few CI calls.
- max-calls-10 underperforms max-calls-5 in accuracy despite using more calls (83.6 vs 88.2). Randomness in which regions the model explores matters more than the cap value.
- Even at max-calls-25, gpt-5.4 catches ~10% fewer marks than gpt-5.5 medium at similar CI call counts — the model generation gap dominates over call count.
- None of the gpt-5.4 + max-calls configs detected stacked marks (`d{macron}{dotbelow}`). Only gpt-5.5 found these rule-4 characters.
- **Verdict:** max-calls-5 on gpt-5.4 medium is the cheapest viable option at $120 for 1,200 pages, but misses ~10 marks/page vs the recommended config. Use for rough first-pass only; not suitable for final archival transcription.

### 8. Image resolution and file size do not affect cost

Both scans are ~4,000 × 6,800 px (27 megapixels), RGBA. OpenAI internally caps resolution before tokenizing. Despite scan 2 being 5.6× larger in file size (12 MB vs 2 MB), both cost ~2,800–2,900 image tokens.

**Image optimizations and their actual savings across 1,200 pages:**

| Optimization | Token saving | Total saving for 1,200 pages |
|---|---|---|
| RGBA → RGB or grayscale | ~0 | $0 |
| PNG compression / JPEG conversion | ~0 | $0 |
| Resize to 50% | ~2,130 | **$13** |
| Resize to 25% | ~2,656 | **$16** |
| Switch to `"low"` detail | ~2,756 | **$17** |

Image optimization is not a meaningful cost lever. Scan 2's 12 MB file is worth compressing for upload speed, not for cost.

### 9. Prompt caching saves ~$3 across 1,200 pages
The prompt is ~1,200 tokens — 1.2% of total cost in the best config. Not a meaningful lever.

---

## Pricing Reference (as of 2026-07-01)

### Token pricing

| Model | Standard input | Standard output | Batch input | Batch output |
|---|---|---|---|---|
| gpt-5.5 | $5.00 / 1M | $30.00 / 1M | $2.50 / 1M | $15.00 / 1M |
| gpt-5.4 | $2.50 / 1M | $15.00 / 1M | $1.25 / 1M | $7.50 / 1M |

Prompt caching: 10% of the applicable input rate (standard or batch).

### Code Interpreter (container sessions)

| Memory | Per 20-min session | Notes |
|---|---|---|
| 1 GB | $0.03 | Billed by the minute, 5-min minimum ($0.0075 min charge) |
| 4 GB | $0.12 | |
| 16 GB | $0.48 | |
| 64 GB | $1.92 | |

CI session cost: ~$9 total across 1,200 pages (one session per page, 5-min minimum). Negligible.

---

## Recommendation

**Use gpt-5.5, medium effort, CI on, via Batch API.**

- Accuracy: matches the most expensive config (98 marks on scan 2)
- Cost: $0.237/page batch → **$285 for 1,200 pages** *(revised prompt, 5-scan average — most reliable estimate)*
- No meaningful accuracy gain from: high effort, CI off, or switching to gpt-5.4

Configs to rule out for archival transcription:
- **low effort** — 6× cheaper ($51 batch) but misses ~17 marks/page; also produced a malformed token
- **CI off** — systematic miss of 15–17 diacritical marks per page regardless of effort
- **gpt-5.4** — 16–20 fewer marks per page on complex scans; not cost-effective given accuracy loss
- **high effort** — 3% more marks than medium on 5-scan avg; 2.2× the cost ($632 vs $285 batch)
- **gpt-5.4 + max-calls cap** — ~10% fewer marks than gpt-5.5 medium and never detects stacked marks; use only for cheap rough first-pass ($120–$163 batch for 1,200 pages)

Human review of the normalized outputs is recommended before committing to a full batch run, particularly to verify `{dotbelow}` and `{macron}` detections.

---

## Output Folder Structure

```
outputs/
  gpt-5.5_effort-medium_CI-on/              ← revised prompt, 5 scans — recommended config
  gpt-5.5_effort-high_CI-on/               ← revised prompt, 5 scans
  gpt-5.4_effort-medium_CI-on_max-calls-5/  ← max_tool_calls cap experiment, 5 scans
  gpt-5.4_effort-medium_CI-on_max-calls-10/ ← max_tool_calls cap experiment, 5 scans
  gpt-5.4_effort-medium_CI-on_max-calls-25/ ← max_tool_calls cap experiment, 5 scans
  Old experiments/
    gpt-5.5_effort-high_CI-on/              ← original prompt (2 scans)
    gpt-5.5_effort-medium_CI-on/            ← original prompt (2 scans)
    gpt-5.5_effort-low_CI-on/               ← original prompt (2 scans) — not recommended
    gpt-5.5_effort-high_CI-off/             ← original prompt (2 scans)
    gpt-5.5_effort-medium_CI-off/           ← original prompt (2 scans)
    gpt-5.4_effort-high_CI-on/              ← original prompt (2 scans)
    gpt-5.4_effort-medium_CI-on/            ← original prompt (2 scans)
```

All outputs: `.txt` (raw), `.literal.txt`, `.normalized.txt`, `.report.json`  
Merged docx (literal only): `outputs/gpt-5.5_effort-*_literal.docx`, `outputs/gpt-5.4_*_literal.docx`  
Accuracy + cost tables (PNG): `outputs/table_accuracy.png`, `outputs/table_cost_batch.png`  
Logs (raw JSON API responses): `logs/`  
Diacritic count script: `scripts/count_diacritics.py`  
Batch job state files: `batch_jobs/`
