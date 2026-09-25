# PPP Ad-Detection Optimization - Handoff Notes

## Current State
- The test_detect.py harness has been fully updated with the 7 critical fixes:
  1. repr() removed from prompts (real newlines now sent to the model)
  2. Transcript input format fixed to [{idx}] {text} to match the prompt's instructions
  3. normalize_category title-keyword override removed (protects meta-discussion, Rule 13)
  4. Confidence scores are now propagated correctly during chunk reconciliation
  5. num_ctx raised to 12288 to prevent truncation
  6. Boundary prompt Example 2 corrected (break announcements = show_content per Rule 1)
  7. Parallel execution removed in favor of sequential chunking with previous_context forwarding.
- A new scoring framework is built directly into test_detect.py.
- The prompts are now defined inline in test_detect.py.

## Full Run Results (122 episodes)
- Test harness avg F1:  **0.759**
- Baseline (prod) avg F1: **0.734**
- Delta: **+0.026** (improved=51, neutral=28, regressed=43)

Full per-episode table is in the most recent log: `logs/test_detect_20260924_212301.log`

## Regression Analysis
A full analysis of the 43 regressions was done and is saved at:
`C:\Users\james\.gemini\antigravity-ide\brain\cf87d5d1-e25f-4bc0-a09a-99c8f2b188dc\regression_analysis.md`

**Root cause summary:**
- The problem is overwhelmingly **recall** (missed ads), not precision.
- 26/43 regressions are under-detection; only 5 are over-detection.
- Three patterns account for almost all regressions:
  1. Long sponsor reads where the START is missed but the END is found — caused by the freeform `previous_context` summary failing to convey "we are still inside an ad" to the next chunk.
  2. Complete misses of obvious mid-roll breaks — likely silent truncation/context-overflow failures in specific chunks.
  3. Minor 1-3 block boundary errors (normal LLM imprecision).

## Plan for Tomorrow

### Step 1 — Fix the `previous_context` handoff (HIGHEST PRIORITY)
**Problem:** The current handoff between chunks is a freeform LLM-written text summary. The model sometimes fails to convey "we are mid-sponsor-read" clearly enough for the next chunk.
**Fix:** Replace the freeform summary with a **structured JSON block** of the last 2-3 topic objects from chunk N. If the final topic in chunk N was `sponsor_read`, the next chunk's model has an unambiguous machine-readable signal.
- In `ask_phase1_topics()`: instead of appending `previous_context` as raw text, format it as:
  ```
  CONTEXT FROM PREVIOUS CHUNK (last topics):
  [{"title": "...", "start_idx": X, "end_idx": Y, "category": "sponsor_read"}, ...]
  The final topic may be ongoing — if the first blocks of THIS chunk are a continuation, extend it.
  ```
- This is a simplification (removes LLM creativity from the handoff path).

### Step 2 — Remove Rule 11 (Vol/CPS/Brightness metadata guidance) from the prompt
**Problem:** Rule 11 is ~200 tokens of prompt explaining how to use audio metadata. Analysis of regressions shows zero cases where metadata misinterpretation caused the failure — all failures are chunking/structural.
**Fix:** Delete Rule 11 from `PROMPT_V18_DIARIZED_MASTER`. The metadata is still in the transcript text; the model can still use it, but we don't need to spend prompt budget on instructions for it. Shorter prompt = more context window for actual transcript.

### Step 3 — Add a silent-failure detection guard
**Problem:** Several "0 detection" regressions suggest the model silently dropped topics for the latter half of a chunk (returned some topics but far fewer than expected).
**Fix:** After `ask_phase1_topics()` returns, check if the returned topics cover at least 50% of the chunk's block range. If not, log a warning and force a retry (the retry logic already exists, it just isn't catching this case).

### Step 4 — Re-run the full 122-episode test after Steps 1-3
- Command: `python tests/test_detect.py` (will process files that don't yet have a `.test.ad`)
- Note: Need to DELETE existing `.test.ad` files first to force a fresh rerun, OR modify the script to accept a `--reprocess` flag.
- Then score: `python tests/test_detect.py --score-only`

### Step 5 — Decide whether to merge to production
- If new avg F1 > 0.80, merge the prompt fixes into `app/detect_adverts.py`.
- If still ~0.76, consider whether the chunking logic needs a bigger rethink vs. just shipping the prompt-only fixes (FIX-1 to FIX-6) which were the original improvement.
