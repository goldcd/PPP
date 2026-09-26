# PPP Ad-Detection Optimization - Handoff Notes

## Current State (as of 2026-09-27)

### ✅ Test Run & Scoring Complete
- The full 122-episode gold standard test run completed.
- **Final avg F1:** **0.829** (vs baseline 0.734, +0.095 improvement).
- Regression analysis (see `regression_analysis.md`) identified 5 distinct failure patterns (most notably: Cancer Research UK embedded sponsor reads, programmatic broadcast ads, and long comedy-sketch ads).

### ✅ Production Merge Complete
- All 10 fixes have been successfully ported and verified in `app/detect_adverts.py` and `app/prompts.py`.
- **Key fixes merged:**
  - Removed `repr()` from prompts
  - "[idx] text" formatting
  - `normalize_category` title-keyword override removed
  - Confidence propagated through reconciliation
  - `num_ctx` raised 8192 -> 12288
  - Boundary prompt Example 2 corrected
  - Sequential processing with `chunk_size=75`, `overlap=40`
  - Coverage guard (<50% coverage forces a retry)
  - Structured JSON `previous_context` handoff
  - Rule 11 (metadata clue instructions) removed to save ~200 prompt tokens

---

## Plan for Tomorrow / Next Steps

### 1. Fix Remaining Edge Cases (FIX-11)
- The main regressions were the embedded Cancer Research UK sponsor reads (where they sound exactly like science content) and the Adam Buxton comedy sketch ad.
- Need to decide if we want to add a `previous_context` sponsor-name-persistence rule (i.e. if an earlier chunk identified a sponsor, and they keep talking about it, force `sponsor_read`) or leave it as is.

### 2. Ensemble Architecture Implementation (Quality-Booster)
- Based on our discussion, the most robust way to solve the remaining False Negatives (like the Adam Buxton sketch) is a **coarse-to-fine ensemble approach**.
- **The Workflow:**
  1. **Fast Scan (Zero-Shot):** Use a fast local decision model (like Ollaya's `von` or `nli`) with a rolling window (e.g. 15 blocks) to act as a "metal detector" looking for highly probable CTA phrases or sponsor names.
  2. **Generative Pass (Status Quo):** The 14B Qwen model does its regular chunking/topic-mapping.
  3. **Discrepancy Check:** Compare the 14B model's output against the fast scan's "hot blocks".
  4. **Targeted Re-Evaluation:** If the 14B model missed an anchor identified by the fast scan, pull a window around that block and use `ask_boundary_verification` to force the 14B model to re-evaluate it carefully.
- This uses the fast model to boost recall and provide anchors, while relying on the 14B model's reasoning to maintain high precision and perfect boundaries.

---

## Notes / Gotchas
- The production code now fully matches the test harness that scored 0.829. 
- The Python verification script (`scratch/verify_merge.py`) confirmed all 10 fixes are correctly implemented in production.
