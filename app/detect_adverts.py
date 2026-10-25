#!/usr/bin/env python3
"""
detect_adverts.py - Advert detection pipeline using Qwen / Ollama.

Two-Stage Architecture:
1. Stage 1 (Find): Fast macro-window scanning (120 blocks, step 90) using PROMPT_POD_ISOLATION.
   Gives the model complete view of the commercial break container and surrounding discussion,
   avoiding break truncation.
2. Stage 2 (Refine): Targeted boundary verification using PROMPT_BOUNDARY_VERIFICATION on each
   detected pod. Constrained to +/- 8 blocks margin to snap start and end boundaries down to
   the exact subtitle line while pruning false-positive candidate regions.
3. Stage 3 (Clean): Micro-gap bridging (<= 3 blocks) for music stingers/chimes within pods,
   topic-map reconstruction, and writing the final .ad file.
"""

import os
import sys
import time
import requests
import json
from datetime import datetime

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml

from app.power import prevent_standby, allow_standby
from app.prompts import PROMPT_POD_ISOLATION, PROMPT_BOUNDARY_VERIFICATION

# Windowing parameters
WINDOW_SIZE = 120
STEP_SIZE = 90
EDGE_MARGIN = 8
MICRO_GAP = 3


class _Tee:
    """Mirrors all writes to sys.stdout into a log file simultaneously."""
    def __init__(self, log_path):
        self._stdout = sys.stdout
        self._file = open(log_path, "w", encoding="utf-8", buffering=1)
        sys.stdout = self

    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        sys.stdout = self._stdout
        self._file.close()


# Global variables for Ollama
ollama_url = None
model_to_use = None


def start_ollama():
    """Initializes and pre-warms the Ollama model."""
    global ollama_url, model_to_use

    config = {}
    if os.path.exists("config.toml"):
        with open("config.toml", "rb") as f:
            config = toml.load(f)
    ollama_config = config.get("ollama", {})
    ollama_url = ollama_config.get("ollama_url", "http://localhost:11434/api/chat")

    force_cpu = config.get("processing", {}).get("force_cpu", False)
    import torch
    if torch.cuda.is_available() and not force_cpu:
        model_to_use = ollama_config.get("gpu_model", "qwen3.8-27b-iq3:latest")
        print(f"\n Using GPU model '{model_to_use}' for advert detection \n", flush=True)
    else:
        model_to_use = ollama_config.get("cpu_model", "qwen3:8b")
        print(f"\n Using CPU model '{model_to_use}' for advert detection \n", flush=True)

    print(f"Requesting Ollama to load: {model_to_use}", flush=True)
    try:
        response = requests.post(
            ollama_url,
            json={"model": model_to_use, "messages": []},
            timeout=120
        )
        if response.status_code == 200:
            print("Model loaded successfully", flush=True)
        else:
            print(f"Status code {response.status_code} loading model", flush=True)
    except Exception as e:
        print(f"Error loading model: {e}", flush=True)


def stop_ollama():
    """Unloads the Ollama model to free VRAM."""
    global ollama_url, model_to_use
    if ollama_url and model_to_use:
        try:
            requests.post(
                ollama_url.replace("/api/chat", "/api/generate"),
                json={"model": model_to_use, "keep_alive": 0},
                timeout=5
            )
        except Exception:
            pass


def parse_srt_time(time_str):
    """Converts an SRT time string (HH:MM:SS,mmm) to total seconds as a float."""
    time_str = time_str.strip()
    parts = time_str.split(":")
    hours = float(parts[0])
    minutes = float(parts[1])
    seconds_parts = parts[2].split(",")
    seconds = float(seconds_parts[0])
    milliseconds = float(seconds_parts[1]) if len(seconds_parts) > 1 else 0.0
    return hours * 3600 + minutes * 60 + seconds + (milliseconds / 1000.0)


def parse_srt_blocks(srt_blocks_raw):
    """Parses raw SRT blocks into structured dictionaries."""
    parsed = []
    for raw in srt_blocks_raw:
        raw_clean = raw.strip()
        if not raw_clean:
            continue
        lines = raw_clean.split("\n")
        if len(lines) >= 3:
            try:
                idx = int(lines[0].strip())
            except ValueError:
                continue
            time_line = lines[1].strip()
            if "-->" not in time_line:
                continue
            times = time_line.split("-->")
            start_time = parse_srt_time(times[0])
            end_time = parse_srt_time(times[1])
            text = " ".join([l.strip() for l in lines[2:] if l.strip()])

            # Extract speaker if present
            spk = None
            if text.startswith("[") and "]" in text:
                header = text[1:text.index("]")]
                spk = header.split("|")[0].strip()

            parsed.append({
                "idx": idx,
                "start_time": start_time,
                "end_time": end_time,
                "text": text,
                "spk": spk,
                "raw": raw_clean
            })
    return parsed


def query_macro_window(url, model, blocks_subset, podcast_title=""):
    """Queries Ollama with PROMPT_POD_ISOLATION for a macro-window of blocks."""
    min_idx = blocks_subset[0]["idx"]
    max_idx = blocks_subset[-1]["idx"]
    transcript_text = "\n".join(f"[{b['idx']}] {b['text']}" for b in blocks_subset)

    user_msg = (
        f"CURRENT PODCAST TITLE: '{podcast_title}'\n\n"
        f"Transcript Segment (Blocks {min_idx} to {max_idx}):\n{transcript_text}\n\n"
        f"Identify all commercial break pods or trailers for other shows within Blocks {min_idx} to {max_idx}. "
        f"Include ALL consecutive adverts in the break until regular show content resumes. Output ONLY the requested JSON object."
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            r = requests.post(
                url,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": PROMPT_POD_ISOLATION},
                        {"role": "user", "content": user_msg}
                    ],
                    "format": "json",
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0.0 + (0.2 * attempt),
                        "num_ctx": 16384
                    }
                },
                timeout=120
            )
            if r.status_code == 200:
                content = r.json().get("message", {}).get("content", "").strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                data = json.loads(content)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"  [Window Error {min_idx}-{max_idx}]: {e}", flush=True)
            time.sleep(1)

    return {"analysis": "Error", "ad_pods": []}


def query_boundary(url, model, blocks_subset, podcast_title=""):
    """Queries Ollama with PROMPT_BOUNDARY_VERIFICATION to refine exact pod boundaries."""
    min_idx = blocks_subset[0]["idx"]
    max_idx = blocks_subset[-1]["idx"]
    transcript_text = "\n".join(f"[{b['idx']}] {b['text']}" for b in blocks_subset)
    user_msg = (
        f"CURRENT PODCAST TITLE: '{podcast_title}'\n\n"
        f"Transcript Segment (Blocks {min_idx} to {max_idx}):\n{transcript_text}\n\n"
        f"Determine the EXACT start_idx and end_idx of the commercial break / promotional segment "
        f"in this transcript. Output ONLY the requested JSON object."
    )
    for attempt in range(3):
        try:
            r = requests.post(
                url,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": PROMPT_BOUNDARY_VERIFICATION},
                        {"role": "user", "content": user_msg},
                    ],
                    "format": "json",
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.0 + (0.2 * attempt), "num_ctx": 8192},
                },
                timeout=120,
            )
            if r.status_code == 200:
                content = r.json().get("message", {}).get("content", "").strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                data = json.loads(content)
                if isinstance(data, dict) and "start_idx" in data and "end_idx" in data:
                    return int(data["start_idx"]), int(data["end_idx"]), data.get("analysis", "")
        except Exception as e:
            if attempt == 2:
                print(f"    [Boundary Error]: {e}", flush=True)
            time.sleep(1)
    return None


def merge_and_bridge(intervals, gap=MICRO_GAP):
    """Merges overlapping / contiguous intervals and bridges micro-gaps."""
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1] + 1 + gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [tuple(m) for m in merged]


def _format_pod_title_and_category(p):
    """Derives a user-friendly category and title for a detected ad pod."""
    p_category = p.get("category")
    p_title = p.get("title")
    p_sponsors = p.get("sponsors", [])

    if not isinstance(p_sponsors, list):
        p_sponsors = [str(p_sponsors)] if p_sponsors else []

    clean_sponsors = [str(s).strip() for s in p_sponsors if str(s).strip()]
    s_combined = " / ".join(clean_sponsors)

    if not p_category:
        lower_text = (s_combined + " " + (p_title or "")).lower()
        if any(w in lower_text for w in ["promo", "trailer", "podcast", "cross-promo", "other show", "preview"]):
            p_category = "podcast_promotion"
        else:
            p_category = "sponsor_read"

    if not p_title:
        if s_combined:
            lower_s = s_combined.lower()
            if p_category == "podcast_promotion":
                if any(w in lower_s for w in ["promo", "trailer", "promotion"]):
                    p_title = s_combined
                else:
                    p_title = f"{s_combined} Promotion"
            else:
                if any(w in lower_s for w in ["sponsor", "ad", "read", "commercial"]):
                    p_title = s_combined
                else:
                    p_title = f"{s_combined} Sponsor Read"
        else:
            p_title = "Sponsor Read" if p_category == "sponsor_read" else "Podcast Promotion"

    return p_category, p_title


def detect_adverts(srt_file, raw_folder):
    """Detects commercial advertising and promotional breaks in a single transcript."""
    global ollama_url, model_to_use
    if not ollama_url or not model_to_use:
        start_ollama()

    srt_path = os.path.join(raw_folder, srt_file)
    ad_path = srt_path.replace(".srt", ".ad")
    print(f"\nDetecting adverts for {srt_file} using {model_to_use}...", flush=True)

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            raw_srt_content = f.read()
    except Exception as e:
        print(f"Error reading SRT file: {e}", flush=True)
        return

    raw_blocks_list = raw_srt_content.replace("\r\n", "\n").strip().split("\n\n")
    if not raw_blocks_list or not raw_blocks_list[0]:
        print("No blocks found in SRT file.", flush=True)
        return

    blocks = parse_srt_blocks(raw_blocks_list)
    if not blocks:
        print("Failed to parse SRT blocks.", flush=True)
        return

    total = len(blocks)
    blocks_map = {b['idx']: b for b in blocks}
    first_idx, last_idx = blocks[0]['idx'], blocks[-1]['idx']

    # Podcast title resolution
    podcast_title = os.path.basename(os.path.dirname(raw_folder)).replace("-", " ").title()
    if podcast_title.lower() in ("data", "proto results", "local results", ""):
        for root, dirs, files in os.walk("data"):
            if srt_file in files:
                podcast_title = os.path.basename(os.path.dirname(root)).replace("-", " ").title()
                break
    print(f"Identified Podcast: '{podcast_title}' ({total} blocks)", flush=True)

    block_meta = {b['idx']: {'category': 'show_content', 'title': 'Show Content', 'is_flagged': False} for b in blocks}

    # --- STAGE 1: MACRO-WINDOW SCAN ---
    num_windows = (total + STEP_SIZE - 1) // STEP_SIZE
    print(f"\n--- Stage 1: Macro-Window Scan ({total} blocks in ~{num_windows} windows) ---", flush=True)
    t0 = time.time()
    raw_intervals = []
    pod_meta = {}  # (clamped_s, clamped_e) -> list of sponsors

    for i in range(0, total, STEP_SIZE):
        sub_blocks = blocks[i:i + WINDOW_SIZE]
        if not sub_blocks:
            break

        min_b = sub_blocks[0]["idx"]
        max_b = sub_blocks[-1]["idx"]
        print(f"  -> Window {min_b} to {max_b} ({len(sub_blocks)} blocks)...", end=" ", flush=True)

        w_t0 = time.time()
        res = query_macro_window(ollama_url, model_to_use, sub_blocks, podcast_title)
        w_elapsed = time.time() - w_t0

        pods = res.get("ad_pods", [])
        if pods:
            found_str = ", ".join(f"[{p.get('start_idx')}-{p.get('end_idx')}: {p.get('sponsors', [])}]" for p in pods)
            print(f"FOUND AD ({w_elapsed:.1f}s): {found_str}", flush=True)
            for p in pods:
                s = p.get("start_idx")
                e = p.get("end_idx")
                sponsors = p.get("sponsors", [])
                if isinstance(s, int) and isinstance(e, int) and s > 0 and e >= s:
                    clamped_s = max(s, min_b)
                    clamped_e = min(e, max_b)
                    raw_intervals.append((clamped_s, clamped_e))
                    pod_meta[(clamped_s, clamped_e)] = sponsors
        else:
            print(f"Clean ({w_elapsed:.1f}s)", flush=True)

    stage1_elapsed = time.time() - t0
    initial_pods = merge_and_bridge(raw_intervals)
    print(f"Stage 1 completed in {stage1_elapsed:.1f}s. Identified {len(initial_pods)} candidate pod(s): {initial_pods}", flush=True)

    if not initial_pods:
        print("No ads detected. Writing empty .ad file.", flush=True)
        with open(ad_path, "w", encoding="utf-8") as f:
            pass
        return

    # --- STAGE 2: BOUNDARY VERIFICATION REFINEMENT ---
    print(f"\n--- Stage 2: Boundary Verification Refinement (+/- {EDGE_MARGIN} blocks) ---", flush=True)
    t1 = time.time()
    refined_pods = []

    for s, e in initial_pods:
        lo = max(first_idx, s - EDGE_MARGIN)
        hi = min(last_idx, e + EDGE_MARGIN)
        sub_blocks = [blocks_map[i] for i in range(lo, hi + 1) if i in blocks_map]
        res = query_boundary(ollama_url, model_to_use, sub_blocks, podcast_title)

        if res is None:
            print(f"  Pod {s}-{e}: Refinement call failed -> keeping original boundary", flush=True)
            refined_pods.append((s, e))
            continue

        rs, re_, analysis = res
        if rs == -1 or re_ == -1:
            # Check if this candidate had confirmed external sponsors or was an ambiguous false positive
            sponsors = []
            for (ps, pe), sps in pod_meta.items():
                if ps <= e and pe >= s:
                    sponsors.extend(sps)
            clean_sponsors = [str(sp).strip() for sp in sponsors if str(sp).strip()]
            if clean_sponsors:
                print(f"  Pod {s}-{e}: Verifier suggested no ad, but external sponsors {clean_sponsors} found -> keeping", flush=True)
                refined_pods.append((s, e))
            else:
                print(f"  Pod {s}-{e}: Verifier pruned false-positive pod (no sponsors) | {analysis[:90]}", flush=True)
            continue

        # Clamp refined boundaries to safety margins around the initial detection
        rs = max(lo, min(s + EDGE_MARGIN, rs))
        re_ = min(hi, max(e - EDGE_MARGIN, re_))

        if rs > re_ or re_ < s or rs > e:
            print(f"  Pod {s}-{e}: Refined {rs}-{re_} invalid -> keeping original", flush=True)
            refined_pods.append((s, e))
            continue

        tag = "unchanged" if (rs, re_) == (s, e) else f"start {rs - s:+d}, end {re_ - e:+d}"
        print(f"  Pod {s}-{e} -> {rs}-{re_} ({tag})", flush=True)
        refined_pods.append((rs, re_))

    stage2_elapsed = time.time() - t1
    print(f"Stage 2 completed in {stage2_elapsed:.1f}s.", flush=True)

    # --- STAGE 3: CLEANING, TOPIC MAP & OUTPUT ---
    final_pods = merge_and_bridge(refined_pods)
    final_ads = set()
    for s, e in final_pods:
        for idx in range(s, e + 1):
            if idx in blocks_map:
                final_ads.add(idx)
                block_meta[idx] = {'category': 'sponsor_read', 'title': 'Commercial Break', 'is_flagged': True}

    for b in blocks:
        if b['idx'] not in final_ads:
            block_meta[b['idx']] = {'category': 'show_content', 'title': 'Show Content', 'is_flagged': False}

    # Rebuild contiguous clean_topics for topic map display
    clean_topics = []
    if blocks:
        curr_meta = block_meta[blocks[0]['idx']]
        current_cat = curr_meta['category']
        current_title = curr_meta['title']
        current_flagged = curr_meta['is_flagged']
        current_start = blocks[0]['idx']
        current_end = blocks[0]['idx']

        for b in blocks[1:]:
            idx = b['idx']
            m = block_meta[idx]
            cat, title, flagged = m['category'], m['title'], m['is_flagged']

            if cat == current_cat and title == current_title and flagged == current_flagged and idx == current_end + 1:
                current_end = idx
            else:
                clean_topics.append({
                    "start_idx": current_start,
                    "end_idx": current_end,
                    "category": current_cat,
                    "title": current_title,
                    "confidence": "certain",
                    "is_flagged": current_flagged
                })
                current_cat, current_title, current_flagged = cat, title, flagged
                current_start = current_end = idx

        clean_topics.append({
            "start_idx": current_start,
            "end_idx": current_end,
            "category": current_cat,
            "title": current_title,
            "confidence": "certain",
            "is_flagged": current_flagged
        })

    # Print topic map
    print("\n--- GENERATED TOPIC MAP ---", flush=True)
    print(f"{'Start':<6} | {'End':<6} | {'Duration':<8} | {'Category':<18} | {'Title'}", flush=True)
    print("-" * 100, flush=True)
    for t in clean_topics:
        duration = t["end_idx"] - t["start_idx"] + 1
        flagged_str = " [FLAGGED]" if t["is_flagged"] else ""
        print(f"{t['start_idx']:<6} | {t['end_idx']:<6} | {duration:<8} | {t['category']:<18} |      {t['title']}{flagged_str}", flush=True)
    print("-" * 100, flush=True)

    print(f"\nFinal detected advert blocks: {len(final_ads)}", flush=True)

    # Write .ad file
    ad_blocks = [blocks_map[i]["raw"] for i in sorted(final_ads) if i in blocks_map]
    if ad_blocks:
        with open(ad_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(ad_blocks) + "\n\n")
        print(f"Saved {len(ad_blocks)} advertisement blocks to {ad_path}", flush=True)
    else:
        with open(ad_path, "w", encoding="utf-8") as f:
            pass
        print("No ads detected. Created empty .ad file.", flush=True)

    # Calculate removal statistics
    if blocks:
        total_time = blocks[-1]['end_time'] - blocks[0]['start_time']
        ad_time = 0.0
        if final_ads:
            sorted_ad_blocks = [blocks_map[i] for i in sorted(final_ads) if i in blocks_map]
            c_start = sorted_ad_blocks[0]['start_time']
            c_end = sorted_ad_blocks[0]['end_time']
            last_i = sorted_ad_blocks[0]['idx']
            for b in sorted_ad_blocks[1:]:
                if b['idx'] == last_i + 1:
                    c_end = b['end_time']
                else:
                    ad_time += (c_end - c_start)
                    c_start = b['start_time']
                    c_end = b['end_time']
                last_i = b['idx']
            ad_time += (c_end - c_start)

        pct = (ad_time / total_time * 100) if total_time > 0 else 0.0
        print(f"Percentage of podcast flagged for removal: {pct:.1f}%\n", flush=True)


def detect_all_adverts():
    """Scans the data/ folder for all unprocessed .srt files and runs advert detection."""
    print("Detecting adverts")
    prevent_standby()

    os.makedirs("logs", exist_ok=True)
    log_filename = datetime.now().strftime("detect_adverts_%Y%m%d_%H%M%S.log")
    log_path = os.path.join("logs", log_filename)
    tee = _Tee(log_path)
    print(f"Logging to {log_path}")

    if not os.path.exists("data"):
        print("No data folder found. Add some podcasts and try again")
        allow_standby()
        tee.close()
        return

    srt_process_list = []
    for podcast_folder in os.listdir("data"):
        podcast_path = os.path.join("data", podcast_folder)
        if os.path.isdir(podcast_path):
            raw_folder = os.path.join(podcast_path, "raw")
            if os.path.exists(raw_folder):
                for srt_file in os.listdir(raw_folder):
                    if srt_file.endswith(".srt"):
                        advert_file = os.path.join(raw_folder, srt_file.replace(".srt", ".ad"))
                        if os.path.exists(advert_file):
                            continue
                        else:
                            srt_process_list.append((srt_file, raw_folder))

    if len(srt_process_list) > 0:
        print(f"\nFound {len(srt_process_list)} unprocessed .srt files\n")
        print("Starting Ollama LLM Engine\n")
        start_ollama()
        for srt_file, raw_folder in srt_process_list:
            detect_adverts(srt_file, raw_folder)
        print("\nStopping Ollama LLM Engine\n")
        stop_ollama()
        tee.close()
        print(f"Log saved to {log_path}")
        allow_standby()
    else:
        print("No unprocessed .srt files found")
        tee.close()
        allow_standby()


if __name__ == "__main__":
    if len(sys.argv) > 2:
        detect_adverts(sys.argv[1], sys.argv[2])
    else:
        detect_all_adverts()
