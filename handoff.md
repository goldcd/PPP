# PPP Ad-Detection Optimization - Handoff Notes

## Current State (as of 2026-09-26 ~02:00)

### Fixes applied to `tests/test_detect.py`
All 10 fixes are now in the file:
  - FIX-1  repr() removed from prompts
  - FIX-2  Pass-1 format: "[idx] text"
  - FIX-3  normalize_category: title-keyword override removed (Rule 13)
  - FIX-4  Confidence propagated through reconciliation
  - FIX-5  num_ctx raised 8192->12288
  - FIX-6  Boundary prompt Example 2 corrected
  - FIX-7  Sequential processing with previous_context forwarding
  - FIX-8  **NEW** Silent-failure guard: <50% coverage forces a retry
  - FIX-9  **NEW** Structured JSON previous_context (last 3 topics) replaces freeform text
  - FIX-10 **NEW** Rule 11 (metadata clue instructions) removed (~200 token saving)

### Test Run Status — INCOMPLETE (killed overnight to save power)
- Run was started fresh (all old `.test.ad` files deleted before starting)
- **103 of 122 episodes** completed before being stopped
- **19 episodes** still have no `.test.ad` file and need reprocessing

### Partial Score (103 episodes)
| Metric | Value |
|---|---|
| Test harness avg F1 | **0.839** |
| Previous run avg F1 | 0.759 |
| Prod baseline avg F1 | 0.734 |
| Delta vs previous | **+0.080** |
| Improved | 57 |
| Neutral | 23 |
| Regressed | 23 |

Well above the 0.80 merge threshold — looking very promising.

---

## Plan for Tomorrow

### Step 1 — Complete the test run (FIRST THING)
The script skips episodes that already have a `.test.ad`, so just re-run and it picks up the remaining 19:
```
python tests/test_detect.py
```
Should take ~1.5–2 hours.

### Step 2 — Score the full 122 episodes
```
python tests/test_detect.py --score-only
```

### Step 3 — Decide whether to merge to production
- If full avg F1 > 0.80: merge all 10 fixes into `app/detect_adverts.py`
- Key things to port: updated prompt (Rule 11 removed), structured JSON handoff logic, coverage guard, all other fixes
- The 0.839 partial will likely settle slightly lower once the harder remaining episodes are included (some have baseline F1 of 0.000, 0.408, 0.485), but 0.80+ still looks very achievable.

### Step 4 — (Optional) Regression analysis
If regressions are still clustered around the same patterns, consider further prompt tuning vs. just shipping FIX-1 through FIX-10.

---

## Notes / Gotchas
- The last episode being processed when killed was a ~1142-block film discussion show. It was mid-topic-mapping when cancelled and will NOT have a `.test.ad` — the re-run will reprocess it from scratch, which is fine.

---

## Future Direction — Decision Models (post-merge investigation)

The current approach uses a 14B generative LLM (Qwen3:14b) for what is fundamentally a classification task. This works well but is slow (minutes per episode).

**Ollaya** (https://ollaya.dev) is a local runtime for open "decision models" — small, purpose-built classifiers that return typed answers (choice, score, yes/no) with calibrated confidence scores in milliseconds. It's the local/open-source equivalent of TypeSafe's Jev model.

Models worth investigating for PPP:
- **`von`** — ModernBERT-large, **8k token context** (big enough for a 75-block chunk), zero-shot, ~20ms per request. Most promising starting point.
- **`nli`** — Zero-shot classifier, most accurate encoder in Ollaya's benchmarks, ~20ms.
- **`gliclass`** — Instruction-following zero-shot classifier, cost barely grows with number of label options, ~15ms.
- **`decider:2b`** — Decoder model (Qwen3.5 base), most accurate overall, ~190ms.

**Key caveat:** These models answer questions about text — they don't do segmentation. You'd still need chunking/boundary logic, but could replace the slow generative LLM call with a fast per-block or per-segment classifier. The 122 gold-standard episodes we now have would make a solid fine-tuning dataset if needed.

**Priority:** Low — complete the current test run and merge decision first.

