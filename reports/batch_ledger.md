# OpenAI Batch Ledger
_Generated 2026-07-16 02:14 — regenerated automatically; do not hand-edit._

## Totals
- **Batches:** 14
- **Requests:** 75 submitted · 12 completed · 42 failed
- **Model executions billed:** 109  (overhead 1.45× vs. submitted)
- **Tokens:** 5,901,900 in / 2,664,894 out
- **Batch API spend (sum of entries):** $54.73
- **Synchronous (non-batch) spend, from 108 run logs:** $63.00
- **Batch API spend (costs API, authoritative):** $28.05
- **Non-batch spend (costs API, authoritative):** $51.17
- **GRAND TOTAL (all API spend):** $79.22

> _Sum-of-entries batch spend ($54.73) exceeds the authoritative costs-API total ($28.05) by ~$26.68. That gap is OpenAI **refunds/credits** applied after the original billing._

## Per-scan index
_"How many times did FN-XXXX fail?" → read its row. **Output $** = spend that produced saved output; **Est. total $** = even share of each batch's full bill (includes shared retry-storm waste)._

| Scan | Attempts | Completed | Failed | Output $ | Est. total $ | History |
|---|---|---|---|---|---|---|
| FN-0001 | 2 | 2 | 0 | $0.93 | $0.93 | sync[high,flex]:✓$0.30 · sync[xhigh,flex]:✓$0.63 |
| FN-0002 | 2 | 2 | 0 | $1.17 | $1.17 | sync[high,flex]:✓$0.36 · sync[xhigh,flex]:✓$0.80 |
| FN-0003 | 2 | 2 | 0 | $0.96 | $0.96 | sync[high,flex]:✓$0.43 · sync[xhigh,flex]:✓$0.53 |
| FN-0004 | 2 | 2 | 0 | $1.15 | $1.15 | sync[high,flex]:✓$0.38 · sync[xhigh,flex]:✓$0.77 |
| FN-0005 | 2 | 2 | 0 | $1.00 | $1.00 | sync[high,flex]:✓$0.38 · sync[xhigh,flex]:✓$0.61 |
| FN-0006 | 6 | 3 | 3 | $1.61 | $5.57 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-6scans-0704:✗(There was an issue with your request. Please check your inputs and try again) · sync[high]:✓$0.79 · sync[high,flex]:✓$0.31 · sync[xhigh,flex]:✓$0.50 |
| FN-0007 | 3 | 3 | 0 | $1.28 | $1.46 | phase1e-0006-0025:✓$0.42 · sync[high,flex]:✓$0.34 · sync[xhigh,flex]:✓$0.52 |
| FN-0008 | 6 | 3 | 3 | $1.31 | $5.87 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-6scans-0704:✗(Our servers are currently overloaded. Please try again later.) · watchdog-test-5scans:✓$0.28 · sync[high,flex]:✓$0.45 · sync[xhigh,flex]:✓$0.58 |
| FN-0009 | 5 | 3 | 2 | $1.61 | $5.28 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-6scans-0704:✓$0.30 · sync[high,flex]:✓$0.54 · sync[xhigh,flex]:✓$0.77 |
| FN-0010 | 5 | 4 | 1 | $1.45 | $2.82 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✓$0.26 · rerun-fn0010:✓$0.36 · sync[high,flex]:✓$0.29 · sync[xhigh,flex]:✓$0.55 |
| FN-0011 | 2 | 2 | 0 | $0.45 | $0.84 | phase1e-0006-0025:✓$0.21 · sync[high,flex]:✓$0.24 |
| FN-0012 | 5 | 2 | 3 | $0.75 | $5.19 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-6scans-0704:✗(There was an issue with your request. Please check your inputs and try again) · watchdog-test-5scans:✓$0.39 · sync[high,flex]:✓$0.35 |
| FN-0013 | 4 | 2 | 2 | $0.80 | $4.48 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-6scans-0704:✓$0.28 · sync[high,flex]:✓$0.51 |
| FN-0014 | 3 | 2 | 1 | $0.75 | $2.14 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✓$0.29 · sync[high,flex]:✓$0.46 |
| FN-0015 | 7 | 2 | 5 | $1.24 | $6.85 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-6scans-0704:✗(There was an issue with your request. Please check your inputs and try again) · watchdog-test-5scans:✗(unknown error) · watchdog-finish-2scans:✗(There was an issue with your request. Please check your inputs and try again) · sync[high]:✓$0.82 · sync[high,flex]:✓$0.43 |
| FN-0016 | 6 | 2 | 4 | $1.45 | $4.77 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(There was an issue with your request. Please check your inputs and try again) · watchdog-test-5scans:✗(This request was not executed because the batch was cancelled.) · watchdog-finish-2scans:✗(This request was not executed because the batch was cancelled.) · sync[high]:✓$1.13 · sync[high,flex]:✓$0.33 |
| FN-0017 | 4 | 2 | 2 | $0.60 | $2.89 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · watchdog-test-5scans:✓$0.26 · sync[high,flex]:✓$0.34 |
| FN-0018 | 5 | 2 | 3 | $1.44 | $3.76 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(There was an issue with your request. Please check your inputs and try again) · batch-scans-18-26:✗(There was an issue with your request. Please check your inputs and try again) · sync[high]:✓$1.05 · sync[high,flex]:✓$0.40 |
| FN-0019 | 5 | 2 | 3 | $1.29 | $3.61 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · batch-scans-18-26:✗(This request was not executed because the batch was cancelled.) · sync[high]:✓$1.00 · sync[high,flex]:✓$0.29 |
| FN-0020 | 2 | 2 | 0 | $0.81 | $1.06 | phase1e-0006-0025:✓$0.35 · sync[high,flex]:✓$0.46 |
| FN-0021 | 5 | 2 | 3 | $1.48 | $3.79 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · batch-scans-18-26:✗(The server had an error processing your request. Sorry about that! You can retry your requ) · sync[high]:✓$1.15 · sync[high,flex]:✓$0.33 |
| FN-0022 | 3 | 2 | 1 | $0.56 | $1.98 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✓$0.26 · sync[high,flex]:✓$0.30 |
| FN-0023 | 5 | 2 | 3 | $1.31 | $3.63 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · batch-scans-18-26:✗(There was an issue with your request. Please check your inputs and try again) · sync[high]:✓$0.81 · sync[high,flex]:✓$0.50 |
| FN-0024 | 5 | 2 | 3 | $1.49 | $3.80 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · batch-scans-18-26:✗(This request was not executed because the batch was cancelled.) · sync[high]:✓$1.11 · sync[high,flex]:✓$0.38 |
| FN-0025 | 5 | 2 | 3 | $1.42 | $3.73 | phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · phase1e-0006-0025:✗(You exceeded your current quota, please check your plan and billing details. For more info) · batch-scans-18-26:✗(This request was not executed because the batch was cancelled.) · sync[high]:✓$1.03 · sync[high,flex]:✓$0.39 |
| FN-0026 | 3 | 2 | 1 | $1.60 | $2.23 | batch-scans-18-26:✗(This request was not executed because the batch was cancelled.) · sync[high]:✓$1.15 · sync[high,flex]:✓$0.44 |
| FN-0027 | 2 | 1 | 1 | $0.46 | $0.46 | batch_6a4d98d66e34:✗(unknown error) · sync[high,flex]:✓$0.46 |
| FN-0028 | 2 | 1 | 1 | $0.48 | $0.48 | batch_6a4d98d7efc4:✗(unknown error) · sync[high,flex]:✓$0.48 |
| FN-0029 | 1 | 1 | 0 | $0.41 | $0.41 | sync[high,flex]:✓$0.41 |
| FN-6-001-050-1 | 15 | 15 | 0 | $8.07 | $8.07 | sync[medium]:✓$0.51 · sync[high]:✓$0.50 · sync[medium]:✓$0.33 · sync[medium]:✓$0.44 · sync[high]:✓$0.66 · sync[low]:✓$0.11 · sync[medium]:✓$0.38 · sync[high]:✓$1.09 · sync[medium]:✓$0.17 · sync[medium]:✓$0.24 · sync[medium]:✓$0.28 · sync[medium]:✓$0.39 · sync[medium]:✓$0.60 · sync[high]:✓$1.20 · sync[high]:✓$1.20 |
| FN-6-001-050-2 | 17 | 17 | 0 | $12.02 | $12.02 | sync[high]:✓$1.18 · sync[medium]:✓$0.52 · sync[high]:✓$0.80 · sync[medium]:✓$0.32 · sync[medium]:✓$0.39 · sync[high]:✓$0.71 · sync[low]:✓$0.06 · sync[medium]:✓$0.51 · sync[high]:✓$1.22 · sync[medium]:✓$0.18 · sync[medium]:✓$0.20 · sync[medium]:✓$0.28 · sync[xhigh]:✓$2.01 · sync[medium]:✓$0.47 · sync[medium]:✓$0.56 · sync[high]:✓$1.32 · sync[high]:✓$1.29 |
| FN-6-001-050-3 | 14 | 9 | 5 | $4.84 | $4.84 | batch_6a4549480b90:✗(Our servers are currently overloaded. Please try again later.) · batch_6a455ac38db0:✗(Our servers are currently overloaded. Please try again later.) · batch_6a45658b3d18:✗(Our servers are currently overloaded. Please try again later.) · batch-test-3scans:✗(Our servers are currently overloaded. Please try again later.) · batch-test-3scans-high:✗(This request was not executed because the batch was cancelled.) · sync[medium]:✓$0.55 · sync[high]:✓$0.96 · sync[medium]:✓$0.22 · sync[medium]:✓$0.22 · sync[medium]:✓$0.26 · sync[medium]:✓$0.43 · sync[medium]:✓$0.46 · sync[high]:✓$0.69 · sync[high]:✓$1.04 |
| FN-6-001-050-4 | 14 | 9 | 5 | $5.24 | $5.24 | batch_6a4549480b90:✗(An error occurred while processing your request. You can retry your request, or contact us) · batch_6a455ac38db0:✗(This request was not executed because the batch was cancelled.) · batch_6a45658b3d18:✗(Our servers are currently overloaded. Please try again later.) · batch-test-3scans:✗(Our servers are currently overloaded. Please try again later.) · batch-test-3scans-high:✗(This request was not executed because the batch was cancelled.) · sync[medium]:✓$0.53 · sync[high]:✓$0.88 · sync[medium]:✓$0.25 · sync[medium]:✓$0.22 · sync[medium]:✓$0.26 · sync[medium]:✓$0.42 · sync[medium]:✓$0.57 · sync[high]:✓$0.94 · sync[high]:✓$1.17 |
| FN-6-001-050-5 | 14 | 9 | 5 | $5.26 | $5.26 | batch_6a4549480b90:✗(An error occurred while processing your request. You can retry your request, or contact us) · batch_6a455ac38db0:✗(Our servers are currently overloaded. Please try again later.) · batch_6a45658b3d18:✗(Our servers are currently overloaded. Please try again later.) · batch-test-3scans:✗(Our servers are currently overloaded. Please try again later.) · batch-test-3scans-high:✗(This request was not executed because the batch was cancelled.) · sync[medium]:✓$0.40 · sync[high]:✓$1.11 · sync[medium]:✓$0.18 · sync[medium]:✓$0.26 · sync[medium]:✓$0.27 · sync[medium]:✓$0.41 · sync[medium]:✓$0.42 · sync[high]:✓$1.06 · sync[high]:✓$1.15 |

## Synchronous (non-batch) requests
_108 runs, $63.00 total — standard rate, except flex-tier runs at 50% off._

| Scan | Runs | Configs | Total $ |
|---|---|---|---|
| FN-0001 | 2 | high/CI/flex, xhigh/CI/flex | $0.93 |
| FN-0002 | 2 | high/CI/flex, xhigh/CI/flex | $1.17 |
| FN-0003 | 2 | high/CI/flex, xhigh/CI/flex | $0.96 |
| FN-0004 | 2 | high/CI/flex, xhigh/CI/flex | $1.15 |
| FN-0005 | 2 | high/CI/flex, xhigh/CI/flex | $1.00 |
| FN-0006 | 3 | high/CI, high/CI/flex, xhigh/CI/flex | $1.61 |
| FN-0007 | 2 | high/CI/flex, xhigh/CI/flex | $0.86 |
| FN-0008 | 2 | high/CI/flex, xhigh/CI/flex | $1.03 |
| FN-0009 | 2 | high/CI/flex, xhigh/CI/flex | $1.31 |
| FN-0010 | 2 | high/CI/flex, xhigh/CI/flex | $0.83 |
| FN-0011 | 1 | high/CI/flex | $0.24 |
| FN-0012 | 1 | high/CI/flex | $0.35 |
| FN-0013 | 1 | high/CI/flex | $0.51 |
| FN-0014 | 1 | high/CI/flex | $0.46 |
| FN-0015 | 2 | high/CI, high/CI/flex | $1.24 |
| FN-0016 | 2 | high/CI, high/CI/flex | $1.45 |
| FN-0017 | 1 | high/CI/flex | $0.34 |
| FN-0018 | 2 | high/CI, high/CI/flex | $1.44 |
| FN-0019 | 2 | high/CI, high/CI/flex | $1.29 |
| FN-0020 | 1 | high/CI/flex | $0.46 |
| FN-0021 | 2 | high/CI, high/CI/flex | $1.48 |
| FN-0022 | 1 | high/CI/flex | $0.30 |
| FN-0023 | 2 | high/CI, high/CI/flex | $1.31 |
| FN-0024 | 2 | high/CI, high/CI/flex | $1.49 |
| FN-0025 | 2 | high/CI, high/CI/flex | $1.42 |
| FN-0026 | 2 | high/CI, high/CI/flex | $1.60 |
| FN-0027 | 1 | high/CI/flex | $0.46 |
| FN-0028 | 1 | high/CI/flex | $0.48 |
| FN-0029 | 1 | high/CI/flex | $0.41 |
| FN-6-001-050-1 | 15 | high/CI, high/no-CI, low/CI, medium/CI, medium/no-CI | $8.07 |
| FN-6-001-050-2 | 17 | high/CI, high/no-CI, low/CI, medium/CI, medium/no-CI, xhigh/CI | $12.02 |
| FN-6-001-050-3 | 9 | high/CI, medium/CI | $4.84 |
| FN-6-001-050-4 | 9 | high/CI, medium/CI | $5.24 |
| FN-6-001-050-5 | 9 | high/CI, medium/CI | $5.26 |

## Per-batch detail
### 2026-07-08 00:24 · (no job) · `batch_6a4d98d7efc48190ae20f35683f6eee0`
- status **completed** | gpt-5.5 ? no-CI | finished 2026-07-08 02:26
- 1 submitted · 0 completed · 1 failed
- **0 executions** (0.00×) · 0 in / 0 out · **$0.00** billed (unavailable)
- scans: FN-0028 ✗(unknown error)

### 2026-07-08 00:24 · (no job) · `batch_6a4d98d66e348190ada4a4ffe93f171e`
- status **completed** | gpt-5.5 ? no-CI | finished 2026-07-08 02:29
- 1 submitted · 0 completed · 1 failed
- **0 executions** (0.00×) · 0 in / 0 out · **$0.00** billed (unavailable)
- scans: FN-0027 ✗(unknown error)

### 2026-07-07 02:12 · rerun-fn0010 · `batch_6a4c6094c90c8190a9f9eb30b08a3afa`
- status **completed** | gpt-5.5 high CI | finished 2026-07-07 03:14
- 1 submitted · 1 completed · 0 failed
- **0 executions** (0.00×) · 0 in / 20,489 out · **$0.31** billed (frozen)
- scans: FN-0010 ✓$0.36

### 2026-07-06 04:28 · batch-scans-18-26 · `batch_6a4b2edbc56c819092cd1ca72f05a5e5`
- status **cancelled** | gpt-5.5 high CI | finished 2026-07-06 06:05
- 7 submitted · 0 completed · 2 failed
- **9 executions** (1.29×) · 478,626 in / 216,648 out · **$4.45** billed (frozen)
- scans: FN-0018 ✗(There was an issue with your request. Please check your inputs and try again) | FN-0019 ✗(This request was not executed because the batch was cancelled.) | FN-0021 ✗(The server had an error processing your request. Sorry about that! You can retry your requ) | FN-0023 ✗(There was an issue with your request. Please check your inputs and try again) | FN-0024 ✗(This request was not executed because the batch was cancelled.) | FN-0025 ✗(This request was not executed because the batch was cancelled.) | FN-0026 ✗(This request was not executed because the batch was cancelled.)

### 2026-07-05 20:09 · watchdog-finish-2scans · `batch_6a4ab9e08a74819093e4e2b35f2e508f`
- status **cancelled** | gpt-5.5 high CI | finished 2026-07-05 22:09
- 2 submitted · 0 completed · 1 failed
- **3 executions** (1.50×) · 169,799 in / 73,628 out · **$1.53** billed (frozen)
- scans: FN-0015 ✗(There was an issue with your request. Please check your inputs and try again) | FN-0016 ✗(This request was not executed because the batch was cancelled.)

### 2026-07-05 16:39 · watchdog-test-5scans · `batch_6a4a88b1fe808190932d7f6118aff131`
- status **cancelled** | gpt-5.5 high CI | finished 2026-07-05 19:01
- 5 submitted · 3 completed · 0 failed
- **8 executions** (1.60×) · 442,875 in / 217,752 out · **$4.37** billed (seed)
- scans: FN-0008 ✓$0.28 | FN-0012 ✓$0.39 | FN-0015 ✗(unknown error) | FN-0016 ✗(This request was not executed because the batch was cancelled.) | FN-0017 ✓$0.26

### 2026-07-04 06:11 · phase1e-6scans-0704 · `batch_6a48a41f79348190a4b9921d50adad51`
- status **cancelled** | gpt-5.5 high CI | finished 2026-07-04 13:10
- 6 submitted · 2 completed · 3 failed
- **27 executions** (4.50×) · 1,454,322 in / 671,733 out · **$13.71** billed (seed)
- scans: FN-0006 ✗(There was an issue with your request. Please check your inputs and try again) | FN-0008 ✗(Our servers are currently overloaded. Please try again later.) | FN-0009 ✓$0.30 | FN-0012 ✗(There was an issue with your request. Please check your inputs and try again) | FN-0013 ✓$0.28 | FN-0015 ✗(There was an issue with your request. Please check your inputs and try again)

### 2026-07-04 00:49 · phase1e-0006-0025 · `batch_6a4858b31da081909c6abab3c42a7e74`
- status **completed** | gpt-5.5 high CI | finished 2026-07-04 04:09
- 17 submitted · 3 completed · 14 failed
- **37 executions** (2.18×) · 2,082,425 in / 876,053 out · **$18.35** billed (seed)
- scans: FN-0006 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0008 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0009 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0010 ✓$0.26 | FN-0012 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0013 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0014 ✓$0.29 | FN-0015 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0016 ✗(There was an issue with your request. Please check your inputs and try again) | FN-0017 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0018 ✗(There was an issue with your request. Please check your inputs and try again) | FN-0019 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0021 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0022 ✓$0.26 | FN-0023 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0024 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0025 ✗(You exceeded your current quota, please check your plan and billing details. For more info)

### 2026-07-03 21:35 · phase1e-0006-0025 · `batch_6a482b22b14481909cb74e9a61327845`
- status **completed** | gpt-5.5 high CI | finished 2026-07-03 23:43
- 20 submitted · 3 completed · 17 failed
- **25 executions** (1.25×) · 1,273,853 in / 588,591 out · **$12.01** billed (seed)
- scans: FN-0006 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0007 ✓$0.42 | FN-0008 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0009 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0010 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0011 ✓$0.21 | FN-0012 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0013 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0014 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0015 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0016 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0017 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0018 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0019 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0020 ✓$0.35 | FN-0021 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0022 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0023 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0024 ✗(You exceeded your current quota, please check your plan and billing details. For more info) | FN-0025 ✗(You exceeded your current quota, please check your plan and billing details. For more info)

### 2026-07-02 05:11 · batch-test-3scans-high · `batch_6a45f30280c08190a9e293ce45ee865d`
- status **cancelled** | gpt-5.5 high CI | finished 2026-07-02 18:20
- 3 submitted · 0 completed · 0 failed
- **0 executions** (0.00×) · 0 in / 0 out · **$0.00** billed (seed)
- scans: FN-6-001-050-3 ✗(This request was not executed because the batch was cancelled.) | FN-6-001-050-4 ✗(This request was not executed because the batch was cancelled.) | FN-6-001-050-5 ✗(This request was not executed because the batch was cancelled.)

### 2026-07-02 05:11 · batch-test-3scans · `batch_6a45f2ff21d4819085964983b5d5c697`
- status **expired** | gpt-5.5 medium CI | finished 2026-07-03 05:37
- 3 submitted · 0 completed · 0 failed
- **0 executions** (0.00×) · 0 in / 0 out · **$0.00** billed (seed)
- scans: FN-6-001-050-3 ✗(Our servers are currently overloaded. Please try again later.) | FN-6-001-050-4 ✗(Our servers are currently overloaded. Please try again later.) | FN-6-001-050-5 ✗(Our servers are currently overloaded. Please try again later.)

### 2026-07-01 19:07 · (no job) · `batch_6a45658b3d188190952a6b6b9680c68f`
- status **cancelled** | gpt-5.5 ? no-CI | finished 2026-07-02 05:31
- 3 submitted · 0 completed · 0 failed
- **0 executions** (0.00×) · 0 in / 0 out · **$0.00** billed (seed)
- scans: FN-6-001-050-3 ✗(Our servers are currently overloaded. Please try again later.) | FN-6-001-050-4 ✗(Our servers are currently overloaded. Please try again later.) | FN-6-001-050-5 ✗(Our servers are currently overloaded. Please try again later.)

### 2026-07-01 18:21 · (no job) · `batch_6a455ac38db08190b3c8ed7310654098`
- status **cancelled** | gpt-5.5 ? no-CI | finished 2026-07-02 05:31
- 3 submitted · 0 completed · 0 failed
- **0 executions** (0.00×) · 0 in / 0 out · **$0.00** billed (seed)
- scans: FN-6-001-050-3 ✗(Our servers are currently overloaded. Please try again later.) | FN-6-001-050-4 ✗(This request was not executed because the batch was cancelled.) | FN-6-001-050-5 ✗(Our servers are currently overloaded. Please try again later.)

### 2026-07-01 17:07 · (no job) · `batch_6a4549480b908190a5310197baa7bb34`
- status **completed** | gpt-5.5 ? no-CI | finished 2026-07-01 19:02
- 3 submitted · 0 completed · 3 failed
- **0 executions** (0.00×) · 0 in / 0 out · **$0.00** billed (seed)
- scans: FN-6-001-050-3 ✗(Our servers are currently overloaded. Please try again later.) | FN-6-001-050-4 ✗(An error occurred while processing your request. You can retry your request, or contact us) | FN-6-001-050-5 ✗(An error occurred while processing your request. You can retry your request, or contact us)
