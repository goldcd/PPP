import os
import sys
import time
import torch
import requests
import json
from collections import Counter

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml


# Global variables for Ollama (set when try to start it)
ollama_url = None   
model_topic = None 
model_refine = None


def detect_all_adverts():
    print("Detecting adverts")

    # If the data path doesn't exist, then tell the user they need to add some podcasts
    if not os.path.exists("data"):
        print("No data folder found. Add some podcasts and try again")
        return

    ##Doing it a bit differently to transcribing - maybe I'll go back and improve that later

    srt_process_list = []
    

    #Go on an adventure in the data folder and detect all of the podcasts that have an 
    for podcast_folder in os.listdir("data"):
        podcast_path = os.path.join("data", podcast_folder)
        if os.path.isdir(podcast_path):
            ##Now, within each podcast folder, we're looking for a raw folder with the rss.xml file in it
            raw_folder = os.path.join(podcast_path, "raw")
            if os.path.exists(raw_folder):
                ##Now within the raw folder, we're looking for .srt files, that do not have a corresponding .ad file
                ##The .ad file is actually going to be an SRT file, but just containing the segements that we think contain adverts.
                ##i.e. If we have a matching pair, we've done the scanning. Later we'll use the .ad to pull sections out of the original podcast file
                for srt_file in os.listdir(raw_folder):
                    if srt_file.endswith(".srt"):
                        advert_file = os.path.join(raw_folder, srt_file.replace(".srt", ".ad"))
                        if os.path.exists(advert_file):
                            continue
                        else:
                            ##Now we've found a file, add it to our list as a tuple
                            srt_process_list.append((srt_file, raw_folder))
                            
    if len(srt_process_list) > 0:
        print(f"\n Found {len(srt_process_list)} unprocessed .srt files \n")
        print("\nStarting Ollama LLM Engine\n")
        start_ollama()
        for srt_file, raw_folder in srt_process_list:
            detect_adverts(srt_file, raw_folder)
        print("\nStopping Ollama LLM Engine\n")
        stop_ollama()
    else:
        print("No unprocessed .srt files found")
        return

##Function to determine which ollama model to use and load it up
def start_ollama():
    global ollama_url, model_topic, model_refine
    
    config = {}
    if os.path.exists("config.toml"):
        with open("config.toml", "rb") as f:
            config = toml.load(f)
    ollama_config = config.get("ollama", {})
    ollama_url = ollama_config.get("ollama_url", "http://localhost:11434/api/chat")
    
    force_cpu = config.get("processing", {}).get("force_cpu", False)
    if torch.cuda.is_available() and not force_cpu:
        gpu_base = ollama_config.get("gpu_model", "gemma4:12b")
        model_topic = ollama_config.get("gpu_model_topic", "qwen2.5:14b")
        model_refine = ollama_config.get("gpu_model_refine", gpu_base)
        print(f"\n Using GPU model '{model_topic}' for topic mapping and '{model_refine}' for refinement \n")
    else:
        cpu_base = ollama_config.get("cpu_model", "gemma4:e2b")
        model_topic = ollama_config.get("cpu_model_topic", "qwen2.5:7b")
        model_refine = ollama_config.get("cpu_model_refine", cpu_base)
        print(f"\n Using CPU model '{model_topic}' for topic mapping and '{model_refine}' for refinement \n")
    
    # Pre-warm/load the models into memory
    for m in [model_topic, model_refine]:
        print(f"Requesting Ollama to load: {m}")
        try:
            response = requests.post(
                ollama_url,
                json={"model": m, "messages": [], "stream": False},
                timeout=10
            )
            if response.status_code == 404:
                print(f"Model '{m}' not found locally. Initiating download...")
                pull_url = ollama_url.replace("/api/chat", "/api/pull")
                pull_response = requests.post(
                    pull_url,
                    json={"name": m, "stream": False},
                    timeout=600  # Give it up to 10 minutes depending on speed
                )
                if pull_response.status_code == 200:
                    print(f"Successfully downloaded {m}!")
                    requests.post(ollama_url, json={"model": m, "messages": [], "stream": False})
                else:
                    print(f"Failed to download model: {pull_response.text}")
        except Exception as e:
            print(f"Failure to load model '{m}': {e}")

## Function to tidy up the model when we're done
def stop_ollama():
    global ollama_url, model_topic, model_refine
    for m in [model_topic, model_refine]:
        if ollama_url and m:
            print(f"Unloading {m} from memory...")
            try:
                requests.post(
                    ollama_url,
                    json={"model": m, "messages": [], "stream": False, "keep_alive": 0},
                    timeout=5
                )
            except Exception as e:
                print(f"Warning: Could not unload model '{m}': {e}")


def parse_srt_blocks(raw_blocks):
    blocks = []
    for rb in raw_blocks:
        lines = rb.strip().split("\n")
        if len(lines) >= 3:
            try:
                idx = int(lines[0].strip())
                text = " ".join(lines[2:]).strip()
                blocks.append({
                    "idx": idx,
                    "text": text,
                    "raw": rb.strip()
                })
            except Exception:
                pass
    return blocks


def ask_phase1_topics(url, model, blocks_subset):
    valid_indices = {b['idx'] for b in blocks_subset}
    min_idx = min(valid_indices)
    max_idx = max(valid_indices)
    transcript_text = " ".join(f"[{b['idx']}] {b['text']}" for b in blocks_subset)
    
    sys_msg = (
        "You are a podcast content segmenter and topic mapper.\n"
        "Your task is to analyze this segment of the transcript and partition it chronologically into distinct topics or segments covered in the show.\n"
        "Ensure every block index in the transcript segment is covered. The topics must be contiguous and cover all block indices from the start to the end.\n\n"
        "For each topic, identify:\n"
        "1. Short title\n"
        "2. Start block index and end block index (inclusive)\n"
        "3. Category: Choose exactly one of: 'show_content', 'sponsor_read', 'podcast_promotion', 'intro_outro', 'other'.\n\n"
        "Category Definitions:\n"
        "- 'show_content': Primary show conversation, stories, news, interviews, or banter.\n"
        "- 'sponsor_read': Commercial pitches for external products/services (e.g. NetSuite, Klaviyo, Odoo, Vanta, LinkedIn, etc.).\n"
        "- 'podcast_promotion': Promos/trailers/credits for other podcasts, channels, or shows (e.g. cross-promotions like 'Creator Destroy').\n"
        "- 'intro_outro': Standard show intro theme, greeting, outro wrap-up, or ending credits.\n"
        "- 'other': Any miscellaneous content that doesn't fit the above.\n\n"
        "You MUST return ONLY a valid JSON object in the following format:\n"
        "{\n"
        "  \"topics\": [\n"
        "    {\n"
        "      \"title\": \"Topic Title\",\n"
        "      \"start_idx\": 120,\n"
        "      \"end_idx\": 180,\n"
        "      \"category\": \"show_content\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    
    user_msg = f"Transcript Segment (Blocks {min_idx} to {max_idx}):\n{transcript_text}\n\nMap topics in JSON."
    
    try:
        r = requests.post(
            url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_ctx": 4096
                },
                "format": "json"
            },
            timeout=90,
        )
        if r.status_code == 200:
            raw = r.json().get("message", {}).get("content", "").strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                
            data = json.loads(raw)
            topics = data.get("topics", [])
            if not isinstance(topics, list):
                return None, "topics is not a list in JSON output"
                
            cleaned = []
            for t in topics:
                if not isinstance(t, dict):
                    continue
                title = t.get("title", "Unknown")
                category = t.get("category", "other")
                
                s_idx = t.get("start_idx") or t.get("start_index") or t.get("start_rx")
                e_idx = t.get("end_idx") or t.get("end_index") or t.get("end_rx")
                
                if s_idx is None or e_idx is None:
                    continue
                try:
                    s_val = int(s_idx)
                    e_val = int(e_idx)
                    
                    # Clamp indices to the valid range of current subset
                    s_val = max(min_idx, min(max_idx, s_val))
                    e_val = max(min_idx, min(max_idx, e_val))
                    
                    if s_val > e_val:
                        s_val, e_val = e_val, s_val
                        
                    cleaned.append({
                        "title": str(title),
                        "start_idx": s_val,
                        "end_idx": e_val,
                        "category": str(category).lower()
                    })
                except (ValueError, TypeError):
                    pass
            return cleaned, None
        else:
            return None, f"API Error: Status {r.status_code} - {r.text}"
    except Exception as e:
        return None, f"Request Error: {e}"


def score_topic(topic):
    score = 0
    cat = topic["category"].lower()
    title = topic["title"].lower()
    duration = topic["end_idx"] - topic["start_idx"] + 1
    
    # 1. Category Weighting
    if "sponsor" in cat or "ad" in cat or "advert" in cat:
        score += 10
    elif "promotion" in cat or "promo" in cat:
        score += 10
    # Note: intro_outro and show_content get 0 base category score to avoid flagging show outro/credits
    elif "other" in cat:
        score += 2
        
    # 2. Duration Weighting
    if duration <= 40:
        score += 4
    elif duration <= 60:
        score += 1
    elif duration > 70:
        score -= 8
        
    # 3. Keyword Check
    keywords = ["sponsor", "code", "discount", "website", "support for", "creator destroy", "promo", "advertisement", "advertise", "subscribe", "newsletter", "offer"]
    found_kw = False
    for kw in keywords:
        if kw in cat or kw in title:
            found_kw = True
            break
    if found_kw:
        score += 3
        
    return score


def ask_phase3_refine_start(url, model, blocks, start_rough, padding_before=20, padding_after=20, temperature=0.4):
    total = len(blocks)
    start_pad_idx = max(1, start_rough - padding_before)
    end_pad_idx = min(total, start_rough + padding_after)
    
    window = [b for b in blocks if start_pad_idx <= b['idx'] <= end_pad_idx]
    if not window:
        return None, "Empty window"
        
    valid_indices = {b['idx'] for b in window}
    transcript_text = " ".join(f"[{b['idx']}] {b['text']}" for b in window)
    
    sys_msg = (
        "You are identifying the exact start boundary of a podcast advertisement.\n"
        "Your task is to analyze the transcript window and identify the exact block index where the podcast switches from regular show content/conversation to a sponsor read/advertisement.\n"
        "Look for phrases like 'Support for this show comes from...', 'Thanks to our sponsor...', or the first sentence pitching a sponsor's product.\n"
        f"The advertisement roughly starts around index {start_rough}.\n"
        "Keep your internal thinking/reasoning extremely brief and concise (maximum 2 sentences).\n"
        "You MUST return ONLY a valid JSON object in the following format:\n"
        '{"start_idx": 123}'
    )
    
    user_msg = f"Transcript Window (Candidate Start: {start_rough}):\n{transcript_text}\n\nIdentify exact start block index in JSON."
    
    try:
        r = requests.post(
            url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": 4096
                },
                "format": "json"
            },
            timeout=90,
        )
        if r.status_code == 200:
            raw = r.json().get("message", {}).get("content", "").strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                
            data = json.loads(raw)
            s_idx = data.get("start_idx") or data.get("start_rx") or data.get("start_index")
            if s_idx is None:
                return None, "Missing start_idx in response JSON"
            s_idx = int(s_idx)
            if s_idx not in valid_indices:
                return None, f"Returned index {s_idx} is outside the valid window"
            return s_idx, None
        else:
            return None, f"API Error: Status {r.status_code} - {r.text}"
    except Exception as e:
        return None, f"Request Error: {e}"


def ask_phase3_refine_end(url, model, blocks, end_rough, padding_before=20, padding_after=20, temperature=0.4):
    total = len(blocks)
    start_pad_idx = max(1, end_rough - padding_before)
    end_pad_idx = min(total, end_rough + padding_after)
    
    window = [b for b in blocks if start_pad_idx <= b['idx'] <= end_pad_idx]
    if not window:
        return None, "Empty window"
        
    valid_indices = {b['idx'] for b in window}
    transcript_text = " ".join(f"[{b['idx']}] {b['text']}" for b in window)
    
    sys_msg = (
        "You are identifying the exact end boundary of a podcast advertisement.\n"
        "Your task is to analyze the transcript window and identify the exact block index where the podcast switches from a sponsor read/advertisement back to regular show content/conversation.\n"
        "Look for phrases like 'Scott, we're back', 'We'll be right back', or call-to-action endpoints like 'go to website.com and use code...'.\n"
        f"The advertisement roughly ends around index {end_rough}.\n"
        "Keep your internal thinking/reasoning extremely brief and concise (maximum 2 sentences).\n"
        "You MUST return ONLY a valid JSON object in the following format:\n"
        '{"end_idx": 123}'
    )
    
    user_msg = f"Transcript Window (Candidate End: {end_rough}):\n{transcript_text}\n\nIdentify exact end block index in JSON."
    
    try:
        r = requests.post(
            url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": 4096
                },
                "format": "json"
            },
            timeout=90,
        )
        if r.status_code == 200:
            raw = r.json().get("message", {}).get("content", "").strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                
            data = json.loads(raw)
            e_idx = data.get("end_idx") or data.get("end_rx") or data.get("end_index")
            if e_idx is None:
                return None, "Missing end_idx in response JSON"
            e_idx = int(e_idx)
            if e_idx not in valid_indices:
                return None, f"Returned index {e_idx} is outside the valid window"
            return e_idx, None
        else:
            return None, f"API Error: Status {r.status_code} - {r.text}"
    except Exception as e:
        return None, f"Request Error: {e}"


def get_flagged_ranges(flagged_indices, gap_threshold=20):
    if not flagged_indices:
        return []
    sorted_indices = sorted(list(flagged_indices))
    ranges = []
    start = sorted_indices[0]
    prev = start
    for idx in sorted_indices[1:]:
        if idx - prev <= gap_threshold + 1:
            prev = idx
        else:
            ranges.append((start, prev))
            start = idx
            prev = idx
    ranges.append((start, prev))
    return ranges


def get_median(lst):
    if not lst:
        return None
    sorted_lst = sorted(lst)
    return sorted_lst[len(sorted_lst) // 2]


def detect_adverts(srt_file, raw_folder):
    global ollama_url, model_topic, model_refine
    
    srt_path = os.path.join(raw_folder, srt_file)
    ad_path = srt_path.replace(".srt", ".ad")
    print(f"\nDetecting adverts for {srt_file}...")

    # Get the raw SRT
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            raw_srt_content = f.read()
    except Exception as e:
        print(f"Error reading SRT file: {e}")
        return

    # Split the raw SRT content into individual blocks
    raw_blocks_list = raw_srt_content.replace("\r\n", "\n").strip().split("\n\n")
    if not raw_blocks_list or not raw_blocks_list[0]:
        print("No blocks found in SRT file.")
        return

    blocks = parse_srt_blocks(raw_blocks_list)
    if not blocks:
        print("Failed to parse SRT blocks.")
        return
        
    total = len(blocks)
    chunk_size = 120
    overlap = 15

    # --- PASS 1: CHUNKED TOPIC MAPPING ---
    print("\n--- PASS 1: Chunked Topic Mapping & Classification ---")
    all_topics = []
    
    pos = 0
    while pos < total:
        end_pos = min(pos + chunk_size, total)
        chunk = blocks[pos:end_pos]
        if not chunk:
            break
            
        print(f"Mapping topics in blocks {chunk[0]['idx']} to {chunk[-1]['idx']} ({end_pos}/{total})...", end=" ", flush=True)
        
        max_retries = 3
        found = None
        for attempt in range(max_retries):
            res, err = ask_phase1_topics(ollama_url, model_topic, chunk)
            if res is not None:
                found = res
                break
            else:
                print(f"\n  [Retry {attempt+1}/{max_retries} due to: {err}]", end=" ", flush=True)
                time.sleep(3)
                
        if found is not None:
            print(f"Identified {len(found)} topic segments.")
            all_topics.extend(found)
        else:
            print("Failed. Skipping this chunk.")
            
        if end_pos == total:
            break
        pos += (chunk_size - overlap)
        
    print(f"Pass 1 complete. Total raw topics mapped: {len(all_topics)}")
    
    # --- PRINT TOPIC MAP TABLE & APPLY WEIGHTING ---
    print("\n--- GENERATED TOPIC MAP & WEIGHTING ---")
    print(f"{'Start':<6} | {'End':<6} | {'Duration':<8} | {'Category':<18} | {'Score':<5} | {'Title'}")
    print("-" * 100)
    
    flagged_indices = set()
    
    for t in all_topics:
        duration = t["end_idx"] - t["start_idx"] + 1
        score = score_topic(t)
        flagged_str = "[FLAGGED]" if score >= 6 else "       "
        print(f"{t['start_idx']:<6} | {t['end_idx']:<6} | {duration:<8} | {t['category']:<18} | {score:<5} | {t['title']} {flagged_str}")
        
        if score >= 6:
            for idx in range(t["start_idx"], t["end_idx"] + 1):
                flagged_indices.add(idx)
                
    print("-" * 100)
    
    if not flagged_indices:
        print("No ad breaks flagged by the weighting heuristic.")
        with open(ad_path, "w", encoding="utf-8") as f:
            pass
        print("Created empty .ad file.")
        return
        
    # --- RECONCILIATION & COLLISION MERGING ---
    rough_segments = get_flagged_ranges(flagged_indices, gap_threshold=20)
    print(f"\nRough ad segments identified (merged): {rough_segments}")
    
    # --- PASS 2: TARGETED BOUNDARY REFINEMENT ---
    print("\n--- PASS 2: Targeted Boundary Refinement (Voting Consensus) ---")
    final_ad_indices = set()
    NUM_RUNS = 3
    TEMP = 0.4
    
    for start_rough, end_rough in rough_segments:
        print(f"Refining boundaries for segment roughly {start_rough} to {end_rough}...")
        
        # 1. Refine Start Boundary
        if start_rough <= 5 and 1 in flagged_indices:
            print(f"  Refining start boundary (around {start_rough})... [Safeguard] Snapped to 1 because ad starts at the beginning of the show.")
            final_start = 1
        else:
            print(f"  Refining start boundary (around {start_rough})...", end=" ", flush=True)
            start_votes = []
            for run in range(NUM_RUNS):
                res, err = ask_phase3_refine_start(ollama_url, model_refine, blocks, start_rough, temperature=TEMP)
                if res is not None:
                    start_votes.append(res)
                else:
                    print(f"[Run {run+1} failed: {err}]", end=" ", flush=True)
                    
            final_start = get_median(start_votes)
            if final_start is None:
                print(f"Failed all runs. Falling back to {start_rough}.")
                final_start = start_rough
            else:
                print(f"Consensus start index: {final_start} (Votes: {start_votes})")
            
        # 2. Refine End Boundary
        if end_rough >= total - 5 and total in flagged_indices:
            print(f"  Refining end boundary (around {end_rough})... [Safeguard] Snapped to {total} because ad runs to the end of the show.")
            final_end = total
        else:
            print(f"  Refining end boundary (around {end_rough})...", end=" ", flush=True)
            end_votes = []
            for run in range(NUM_RUNS):
                res, err = ask_phase3_refine_end(ollama_url, model_refine, blocks, end_rough, temperature=TEMP)
                if res is not None:
                    end_votes.append(res)
                else:
                    print(f"[Run {run+1} failed: {err}]", end=" ", flush=True)
                    
            final_end = get_median(end_votes)
            if final_end is None:
                print(f"Failed all runs. Falling back to {end_rough}.")
                final_end = end_rough
            else:
                print(f"Consensus end index: {final_end} (Votes: {end_votes})")
            
        # Safe-guard for snap-to-edge constraint for index 1
        # If the start is 2, do NOT snap to 1 unless block 1 is flagged in topic map.
        if final_start == 2:
            if 1 not in flagged_indices:
                print("  [Safeguard] Leaving start at 2 to preserve content.")
            else:
                print("  [Safeguard] Snapping start to 1 because block 1 was flagged in topic map.")
                final_start = 1
                
        print(f"  => Confirmed refined range: {final_start} to {final_end}")
        for idx in range(final_start, final_end + 1):
            final_ad_indices.add(idx)

    # Gap filling: If there is a small gap (<= 6 blocks) between two ad blocks, merge them.
    sorted_ads = sorted(list(final_ad_indices))
    final_ads = set()
    if sorted_ads:
        current = sorted_ads[0]
        final_ads.add(current)
        for idx in sorted_ads[1:]:
            if idx - current <= 7:
                for fill in range(current + 1, idx):
                    final_ads.add(fill)
            final_ads.add(idx)
            current = idx
            
    print(f"\nFound total {len(final_ads)} ad blocks after gap filling.")
    
    # Filter and write matching blocks to the .ad file
    ad_blocks = []
    for b in blocks:
        if b['idx'] in final_ads:
            ad_blocks.append(b['raw'])
            
    if ad_blocks:
        with open(ad_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(ad_blocks) + "\n\n")
        print(f"Saved {len(ad_blocks)} advertisement blocks to {ad_path}")
    else:
        with open(ad_path, "w", encoding="utf-8") as f:
            pass
        print("No ads detected. Created empty .ad file.")
