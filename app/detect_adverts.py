#!/usr/bin/env python3
"""
detect_adverts.py - Advert detection pipeline using Qwen / Ollama.

Architecture:
1. Phase 0 Coarse Scan: Fast chunk scanning with PROMPT_SUSPICION and "think": False (~1.2s/chunk).
2. Phase 1 Pod Isolation: Direct commercial break isolation using PROMPT_POD_ISOLATION
   over focused sub-windows (<= 60 blocks, step 35) to prevent attention drift on large candidate zones.
3. Phase 2 Episode Sponsor Memory: Re-checks unflagged mentions of confirmed episode sponsors.
4. Micro-Gap Bridging: Bridges micro-gaps (<= 3 blocks) for music stingers/breathers within a pod.
"""

import os
import sys
import time
import requests
import json
import concurrent.futures
from collections import Counter
from datetime import datetime

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml

from app.power import prevent_standby, allow_standby
from app.prompts import PROMPT_SUSPICION, PROMPT_POD_ISOLATION


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
        model_to_use = ollama_config.get("gpu_model", "qwen3:14b")
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


def ask_pod_isolation(url, model, blocks_subset, podcast_title=""):
    """Queries Ollama with PROMPT_POD_ISOLATION for a targeted segment of blocks."""
    min_idx = blocks_subset[0]['idx']
    max_idx = blocks_subset[-1]['idx']
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
                        "num_ctx": 8192
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
                print(f"  [Pod Isolation Error]: {e}", flush=True)
            time.sleep(2)

    return {"analysis": "Error", "ad_pods": []}


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
        if any(w in lower_text for w in ["promo", "trailer", "podcast", "cross-promo", "other show", "preview", "observer"]):
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
    print(f"\nDetecting adverts for {srt_file}...", flush=True)

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

    # Robust podcast title resolution
    podcast_title = os.path.basename(os.path.dirname(raw_folder)).replace("-", " ").title()
    if podcast_title.lower() in ("data", "proto results", "local results", ""):
        for root, dirs, files in os.walk("data"):
            if srt_file in files:
                podcast_title = os.path.basename(os.path.dirname(root)).replace("-", " ").title()
                break
    print(f"Identified Podcast: '{podcast_title}' ({total} blocks)", flush=True)

    # --- SPEAKER STATISTICS ---
    spk_counts = Counter(b['spk'] for b in blocks if b['spk'] and b['spk'] != "MUSIC/NOISE")
    total_spk_blocks = sum(spk_counts.values()) or 1
    spk_share = {k: v / total_spk_blocks for k, v in spk_counts.items()}
    rare_speakers = {k for k, share in spk_share.items() if share < 0.05}

    # --- PHASE 0: COARSE "SUSPICION" PASS ---
    print("\n--- Phase 0: Coarse Suspicion Pass ---", flush=True)
    suspicion_scores = {}
    coarse_chunk_size = 50
    coarse_step = 30

    def process_coarse_chunk(i):
        chunk = blocks[i:i+coarse_chunk_size]
        if not chunk:
            return None
        text = "\n".join(f"[{b['idx']}] {b['text']}" for b in chunk)
        for attempt in range(3):
            try:
                r = requests.post(
                    ollama_url,
                    json={
                        "model": model_to_use,
                        "messages": [
                            {"role": "system", "content": PROMPT_SUSPICION},
                            {"role": "user", "content": f"Transcript chunk:\n{text}"}
                        ],
                        "format": "json",
                        "stream": False,
                        "think": False,
                        "options": {
                            "temperature": 0.0,
                            "num_ctx": 4096,
                            "num_predict": 200,
                            "stop": ["</s>", "<|im_end|>", "<|endoftext|>"]
                        }
                    },
                    timeout=120
                )
                if r.status_code == 200:
                    content = r.json().get("message", {}).get("content", "").strip()
                    data = json.loads(content)
                    return {
                        "chunk": chunk,
                        "score": data.get("suspicion_score", 1),
                        "reasoning": data.get("reasoning", "")
                    }
            except Exception:
                time.sleep(1)
        return {"chunk": chunk, "score": 1, "reasoning": "Error"}

    # Submit coarse chunks in parallel (max_workers=2 to prevent Ollama saturation)
    futures_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        for i in range(0, total, coarse_step):
            if not blocks[i:i+coarse_chunk_size]:
                break
            future = executor.submit(process_coarse_chunk, i)
            futures_map[future] = i

        for future in concurrent.futures.as_completed(futures_map):
            res = future.result()
            if not res or "error" in res:
                continue
            chunk = res["chunk"]
            score = res["score"]
            reasoning = res["reasoning"]
            c_start, c_end = chunk[0]['idx'], chunk[-1]['idx']
            if score >= 4:
                print(f"Scanning blocks {c_start} to {c_end}... SUSPICIOUS (Score: {score}) - {reasoning[:60]}...", flush=True)
                for b in chunk:
                    suspicion_scores[b["idx"]] = max(suspicion_scores.get(b["idx"], 0), score)

    # Pre-roll guard: always check blocks 1 to 40 if rare voice, music, or sponsor cue is present
    first_blocks = blocks[:20]
    has_cold_cue = any(
        b['spk'] in rare_speakers or
        b['spk'] == 'MUSIC/NOISE' or
        any(w in b['text'].lower() for w in ['presented by', 'brought to you', 'sponsor', 'partner'])
        for b in first_blocks
    )
    if has_cold_cue:
        for b in blocks[:40]:
            suspicion_scores[b['idx']] = max(suspicion_scores.get(b['idx'], 0), 6)

    # Post-roll guard: if last 25 blocks contain a rare voice or promo cues, flag for check
    if len(blocks) > 40:
        tail_blocks = blocks[-25:]
        has_tail_cue = any(b['spk'] in rare_speakers for b in tail_blocks)
        if has_tail_cue:
            for b in tail_blocks:
                suspicion_scores[b['idx']] = max(suspicion_scores.get(b['idx'], 0), 5)

    # Cluster suspicious blocks
    clusters = []
    if suspicion_scores:
        sorted_suspicious = sorted(list(suspicion_scores.keys()))
        curr = [sorted_suspicious[0]]
        for idx in sorted_suspicious[1:]:
            if idx <= curr[-1] + 25:
                curr.append(idx)
            else:
                clusters.append(curr)
                curr = [idx]
        clusters.append(curr)

    print(f"\nCoarse Pass identified {len(clusters)} suspicious region(s).", flush=True)

    # --- PHASE 1: DIRECT POD ISOLATION ---
    print("\n--- Phase 1: Direct Pod Isolation ---", flush=True)
    detected_ad_blocks = set()
    episode_sponsors = set()
    block_meta = {b['idx']: {'category': 'show_content', 'title': 'Show Content', 'is_flagged': False} for b in blocks}

    for c in clusters:
        c_min = c[0]
        c_max = c[-1]

        start_context = 1 if c_min <= 25 else max(1, c_min - 20)
        end_context = min(total, c_max + 25)

        # Sub-window sliding for candidate regions (keeps LLM within high-attention window)
        max_pod_window = 50
        pod_step = 25

        sub_windows = []
        if (end_context - start_context + 1) <= max_pod_window:
            sub_windows.append((start_context, end_context))
        else:
            if start_context == 1 and end_context > 40:
                sub_windows.append((1, min(total, 35)))
                w_start = 12
            else:
                w_start = start_context

            while w_start <= end_context:
                w_end = min(end_context, w_start + max_pod_window - 1)
                sub_windows.append((w_start, w_end))
                if w_end == end_context:
                    break
                w_start += pod_step

        for w_s, w_e in sub_windows:
            w_blocks = [blocks_map[i] for i in range(w_s, w_e + 1) if i in blocks_map]
            if not w_blocks:
                continue

            print(f"\nAnalyzing candidate window {w_s} to {w_e}...", flush=True)
            res = ask_pod_isolation(ollama_url, model_to_use, w_blocks, podcast_title)

            analysis = res.get("analysis", "")
            pods = res.get("ad_pods", [])

            print(f"  Analysis: {analysis[:120]}...", flush=True)
            if pods:
                for p in pods:
                    p_start = p.get("start_idx", -1)
                    p_end = p.get("end_idx", -1)
                    p_sponsors = p.get("sponsors", [])
                    if p_start != -1 and p_end != -1 and p_start <= p_end:
                        # Auto-correct dropped-digit typo (e.g. 57 -> 570 in window [561, 620])
                        if p_start < w_s and (p_start * 10) >= w_s and (p_start * 10) <= w_e:
                            p_start = p_start * 10
                        if p_end < w_s and (p_end * 10) >= w_s and (p_end * 10) <= w_e:
                            p_end = p_end * 10

                        # Strictly clamp returned pod indices to active candidate window
                        p_start = max(w_s, min(w_e, p_start))
                        p_end = max(w_s, min(w_e, p_end))
                        if p_start > p_end:
                            continue

                        print(f"  -> AD POD FOUND: Blocks {p_start} to {p_end} | Sponsors: {p_sponsors}", flush=True)
                        p_cat, p_title = _format_pod_title_and_category(p)
                        for idx in range(p_start, p_end + 1):
                            detected_ad_blocks.add(idx)
                            if idx not in block_meta or not block_meta[idx]['is_flagged']:
                                block_meta[idx] = {'category': p_cat, 'title': p_title, 'is_flagged': True}
                        for s in p_sponsors:
                            if isinstance(s, str) and len(s) > 2:
                                episode_sponsors.add(s.strip().lower())
            else:
                print("  -> No ad pod in this window (Show content confirmed).", flush=True)

    # --- PHASE 2: EPISODE-LEVEL SPONSOR RE-MENTION CHECK ---
    if episode_sponsors:
        print(f"\n--- Episode Sponsor Memory Check for: {list(episode_sponsors)} ---", flush=True)
        for sponsor in episode_sponsors:
            for b in blocks:
                if b['idx'] not in detected_ad_blocks and sponsor in b['text'].lower():
                    print(f"  Re-mention of '{sponsor}' at block {b['idx']}! Reviewing surrounding context...", flush=True)
                    recheck_start = max(1, b['idx'] - 15)
                    recheck_end = min(total, b['idx'] + 25)
                    recheck_blocks = [blocks_map[i] for i in range(recheck_start, recheck_end + 1) if i in blocks_map]
                    res = ask_pod_isolation(ollama_url, model_to_use, recheck_blocks, podcast_title)
                    for p in res.get("ad_pods", []):
                        p_start = p.get("start_idx", -1)
                        p_end = p.get("end_idx", -1)
                        if p_start != -1 and p_end != -1 and p_start <= p_end:
                            p_start = max(recheck_start, min(recheck_end, p_start))
                            p_end = max(recheck_start, min(recheck_end, p_end))
                            if p_start > p_end:
                                continue
                            print(f"  -> ADDED AD POD FROM RE-MENTION: Blocks {p_start} to {p_end}", flush=True)
                            p_cat, p_title = _format_pod_title_and_category(p)
                            for idx in range(p_start, p_end + 1):
                                detected_ad_blocks.add(idx)
                                if idx not in block_meta or not block_meta[idx]['is_flagged']:
                                    block_meta[idx] = {'category': p_cat, 'title': p_title, 'is_flagged': True}

    # --- MICRO-GAP BRIDGING ---
    # Bridge micro-gaps <= 3 blocks within an ad pod (music stingers, chimes, breathers)
    sorted_ads = sorted(list(detected_ad_blocks))
    final_ads = set()
    if sorted_ads:
        current = sorted_ads[0]
        final_ads.add(current)
        for idx in sorted_ads[1:]:
            if idx - current <= 4:  # <= 3 unflagged block gap
                for fill in range(current + 1, idx):
                    final_ads.add(fill)
                    if current in block_meta:
                        block_meta[fill] = dict(block_meta[current])
            final_ads.add(idx)
            current = idx

    # Ensure metadata consistency for all final_ads and unflagged blocks
    for idx in final_ads:
        if idx not in block_meta or not block_meta[idx]['is_flagged']:
            block_meta[idx] = {'category': 'sponsor_read', 'title': 'Sponsor Read', 'is_flagged': True}

    for b in blocks:
        idx = b['idx']
        if idx not in final_ads:
            block_meta[idx] = {'category': 'show_content', 'title': 'Show Content', 'is_flagged': False}

    # Rebuild contiguous clean_topics for topic map display
    clean_topics = []
    if blocks:
        first_idx = blocks[0]['idx']
        curr_meta = block_meta.get(first_idx, {'category': 'show_content', 'title': 'Show Content', 'is_flagged': False})
        current_cat = curr_meta['category']
        current_title = curr_meta['title']
        current_flagged = curr_meta['is_flagged']
        current_start = first_idx
        current_end = first_idx

        for b in blocks[1:]:
            idx = b['idx']
            m = block_meta.get(idx, {'category': 'show_content', 'title': 'Show Content', 'is_flagged': False})
            cat = m['category']
            title = m['title']
            flagged = m['is_flagged']

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
                current_cat = cat
                current_title = title
                current_flagged = flagged
                current_start = idx
                current_end = idx

        clean_topics.append({
            "start_idx": current_start,
            "end_idx": current_end,
            "category": current_cat,
            "title": current_title,
            "confidence": "certain",
            "is_flagged": current_flagged
        })

    # --- PRINT TOPIC MAP TABLE ---
    print("\n--- GENERATED TOPIC MAP ---", flush=True)
    print(f"{'Start':<6} | {'End':<6} | {'Duration':<8} | {'Category':<18} | {'Title'}", flush=True)
    print("-" * 100, flush=True)

    for t in clean_topics:
        duration = t["end_idx"] - t["start_idx"] + 1
        is_flagged = t["is_flagged"]
        confidence = t.get("confidence", "certain")

        flagged_str = " [FLAGGED]" if is_flagged else ""
        conf_str = f"[{confidence.upper()[:3]}]" if confidence != "certain" else "     "
        print(f"{t['start_idx']:<6} | {t['end_idx']:<6} | {duration:<8} | {t['category']:<18} | {conf_str} {t['title']}{flagged_str}", flush=True)

    print("-" * 100, flush=True)

    print(f"\nFinal detected advert blocks: {len(final_ads)}", flush=True)

    # Filter and write matching blocks to the .ad file
    ad_blocks = []
    for b in blocks:
        if b['idx'] in final_ads:
            ad_blocks.append(b['raw'])

    if ad_blocks:
        with open(ad_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(ad_blocks) + "\n\n")
        print(f"Saved {len(ad_blocks)} advertisement blocks to {ad_path}", flush=True)
    else:
        with open(ad_path, "w", encoding="utf-8") as f:
            pass
        print("No ads detected. Created empty .ad file.", flush=True)

    # Calculate removal statistics
    if blocks and len(blocks) > 0:
        total_podcast_time = blocks[-1]['end_time'] - blocks[0]['start_time']
        total_ad_time = 0.0

        ad_blocks_data = [b for b in blocks if b['idx'] in final_ads]
        if ad_blocks_data:
            current_start = ad_blocks_data[0]['start_time']
            current_end = ad_blocks_data[0]['end_time']
            last_idx = ad_blocks_data[0]['idx']

            for b in ad_blocks_data[1:]:
                if b['idx'] == last_idx + 1:
                    current_end = b['end_time']
                else:
                    total_ad_time += (current_end - current_start)
                    current_start = b['start_time']
                    current_end = b['end_time']
                last_idx = b['idx']

            total_ad_time += (current_end - current_start)

        if total_podcast_time > 0:
            percentage = (total_ad_time / total_podcast_time) * 100
            print(f"Percentage of podcast flagged for removal: {percentage:.1f}%\n", flush=True)
        else:
            print("Percentage of podcast flagged for removal: 0.0%\n", flush=True)


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
