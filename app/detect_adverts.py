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

"""

This script processes transcription (.srt) files to detect and isolate adverts using an LLM and scoring

1. Discovery (detect_all_adverts):
   - Scans the 'data' directory for podcasts and their 'raw' folders.
   - Finds any '.srt' files that do not yet have a corresponding '.ad' file .
   - If unprocessed files are found, we start processing.

2. Model Initialization (start_ollama / stop_ollama):
   - Reads 'config.toml' to determine the LLM API endpoint and which model to use.
   - Automatically selects between a CPU or GPU model based on hardware availability and configuration.
   - Warms up/loads the model into memory, and optionally downloads it if it is missing locally.

3. Processing Individual Transcripts (detect_adverts):
   - Reads the configuration to identify which content categories the user wants to remove (e.g., 'sponsor_read', 'podcast_promotion').
   - Parses the raw .srt file into a list of block dictionaries (parse_srt_blocks) containing the index, text, and raw string.
   - Topic Mapping (ask_phase1_topics): Chunks the blocks (with overlap) and prompts the LLM to partition the transcript into 
     contiguous topics. The LLM categorizes each segment into types like 'sponsor_read', 'show_content', etc.
   - Scoring (score_topic): Evaluates each identified topic based on its category, duration, and keyword matches to generate a "spam score".
   - Flagging & Gap Filling: Flags topics for removal if they match the user's config categories OR if they achieve a high spam score
     (catching stealthy ads). It then bridges small gaps between flagged segments to create continuous ad blocks.
   - Finally, writes out the flagged SRT blocks into a new '.ad' file for downstream removal.
"""


# Global variables for Ollama (set when try to start it)
ollama_url = None   
model_to_use = None 


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
                            
    ## If we found any unprocessed .srt, then we've put them on this list. So now if there's anything on it, we should process each one.abs
    if len(srt_process_list) > 0:
        print(f"\n Found {len(srt_process_list)} unprocessed .srt files \n")
        print("\nStarting Ollama LLM Engine\n")
        start_ollama()
        for srt_file, raw_folder in srt_process_list:
            detect_adverts(srt_file, raw_folder)
        print("\nStopping Ollama LLM Engine\n")
        ##Then stop the ollama engine. It's on a timeout, and gets kicked from memory if you load something else - so if we quit out/crash, this will leave eventually by itself.
        stop_ollama()
    else:
        print("No unprocessed .srt files found")
        return

##Function to determine which ollama model to use and load it up
##AI did this - should grab any model it needs (assuming it's in Ollama and it's not hallucinating names again - check this, if you change it and see errors..)
def start_ollama():
    global ollama_url, model_to_use
    
    config = {}
    if os.path.exists("config.toml"):
        with open("config.toml", "rb") as f:
            config = toml.load(f)
    ollama_config = config.get("ollama", {})
    ollama_url = ollama_config.get("ollama_url", "http://localhost:11434/api/chat")
    
    force_cpu = config.get("processing", {}).get("force_cpu", False)
    if torch.cuda.is_available() and not force_cpu:
        model_to_use = ollama_config.get("gpu_model", "qwen3:14b")
        print(f"\n Using GPU model '{model_to_use}' for advert detection \n")
    else:
        model_to_use = ollama_config.get("cpu_model", "qwen3:8b")
        print(f"\n Using CPU model '{model_to_use}' for advert detection \n")
    
    # Pre-warm/load the model into memory
    print(f"Requesting Ollama to load: {model_to_use}")
    try:
        response = requests.post(
            ollama_url,
            json={"model": model_to_use, "messages": [], "stream": False},
            timeout=120
        )
        if response.status_code == 404:
            print(f"Model '{model_to_use}' not found locally. Initiating download...")
            pull_url = ollama_url.replace("/api/chat", "/api/pull")
            pull_response = requests.post(
                pull_url,
                json={"name": model_to_use, "stream": False},
                timeout=600  # Give it up to 10 minutes depending on speed
            )
            if pull_response.status_code == 200:
                print(f"Successfully downloaded {model_to_use}!")
                requests.post(ollama_url, json={"model": model_to_use, "messages": [], "stream": False})
            else:
                print(f"Failed to download model: {pull_response.text}")
    except Exception as e:
        print(f"Failure to load model '{model_to_use}': {e}")

## Function to tidy up the model when we're done
##AI did this
def stop_ollama():
    global ollama_url, model_to_use
    if ollama_url and model_to_use:
        print(f"Unloading {model_to_use} from memory...")
        try:
            requests.post(
                ollama_url,
                json={"model": model_to_use, "messages": [], "stream": False, "keep_alive": 0},
                timeout=5
            )
        except Exception as e:
            print(f"Warning: Could not unload model '{model_to_use}': {e}")

## Function to convert the SRT into a list of dictionaries, for easier handling.
def parse_srt_blocks(raw_blocks):
    blocks = []
    for rb in raw_blocks:
        lines = rb.strip().split("\n")
        if len(lines) >= 3:
            try:
                idx = int(lines[0].strip())
                text = " ".join(lines[2:]).strip()
                blocks.append({
                    ##The index of the block
                    "idx": idx,
                    ##The content/transcript of the block
                    "text": text,
                    ##An unmolested and complete (but trimmed) version of the block as it appeared in the original file
                    "raw": rb.strip()
                })
            except Exception:
                pass
    return blocks

## Function to take in the list of block dictionaries, and give us our first idea of segments
##Ignore that it's called phase 1 - there were more, but it got stupidly complicated..
def ask_phase1_topics(url, model, blocks_subset):
    ##Determine the start and end index of the blocks we're passing in
    valid_indices = {b['idx'] for b in blocks_subset}
    ##Get the min and max of this set of indices
    min_idx = min(valid_indices)
    max_idx = max(valid_indices)
    ##Combine the text of the blocks into a single string
    transcript_text = " ".join(f"[{b['idx']}] {b['text']}" for b in blocks_subset)
    
    ##This request to map the segments into topics, is performing way way better than previous "take out the adverts!"
    ##Also Qwen is a champion. Second time I've come back to her. My eye should never have wandered..
    ##NOTE TO SELF - I think I should let people choose what topics they want taking out of the podcast. Should also split between self-promotion and podcast-promotion
    sys_msg = (
        "You are a podcast content segmenter and topic mapper.\n"
        "Your task is to analyze this segment of the transcript and partition it chronologically into distinct topics or segments covered in the show.\n"
        "CRITICAL INSTRUCTION: You MUST NOT skip or drop any block indices! Every single block from the first index to the last index MUST be included in exactly one topic. Do not omit any part of the transcript, even if it is an advert. The topics must be strictly contiguous with no gaps.\n\n"
        "For each topic, identify:\n"
        "1. Short title\n"
        "2. Start block index and end block index (inclusive)\n"
        "3. Category: Choose exactly one of: 'show_content', 'sponsor_read', 'podcast_promotion', 'self_promotion','intro_outro', 'other'.\n\n"
        "Category Definitions:\n"
        "- 'show_content': Primary show conversation, stories, news, interviews, or banter.\n"
        "- 'sponsor_read': Commercial pitches for external companies/products/services (e.g. software, B2B, consumer goods, retail stores, food/drink, savings etc.) and any other kind of commercial or sponsorship promotion.\n"
        "- 'podcast_promotion': Promos/trailers/credits for other podcasts, channels, or shows (e.g. cross-promotions like 'Creator Destroy').\n"
        "- 'self_promotion': Promotion of the current podcast (e.g. live shows, patreon, paid ad-free versions of this podcast, merchandise etc).\n"
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
    
    # Format the user message to include the actual transcript subset being processed.
    user_msg = f"Transcript Segment (Blocks {min_idx} to {max_idx}):\n{transcript_text}\n\nMap topics in JSON."
    
    try:
        # Make a POST request to the local LLM API (e.g., Ollama).
        # Temperature is set to 0.0 for more deterministic and consistent output formatting.
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
        # Process the successful response
        if r.status_code == 200:
            # Extract the raw content from the response message
            raw = r.json().get("message", {}).get("content", "").strip()
            
            # Clean up the output in case the LLM wrapped the JSON in markdown code blocks
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                
            # Parse the cleaned string into a JSON dictionary
            data = json.loads(raw)
            # Retrieve the list of topics from the parsed JSON
            topics = data.get("topics", [])
            
            # Ensure the API returned a list as expected
            if not isinstance(topics, list):
                return None, "topics is not a list in JSON output"
                
            cleaned = []
            # Iterate through each topic to validate and clean up the data
            for t in topics:
                # Ensure the topic entry is a dictionary
                if not isinstance(t, dict):
                    continue
                # Extract title and category, providing defaults if missing
                title = t.get("title", "Unknown")
                category = t.get("category", "other")
                
                # Extract start and end indices, accounting for potential key name variations from the LLM
                s_idx = t.get("start_idx") or t.get("start_index") or t.get("start_rx")
                e_idx = t.get("end_idx") or t.get("end_index") or t.get("end_rx")
                
                # Skip topic if it lacks valid start or end index references
                if s_idx is None or e_idx is None:
                    continue
                try:
                    # Convert indices to integers
                    s_val = int(s_idx)
                    e_val = int(e_idx)
                    
                    # Clamp the indices to ensure they fall within the bounds of the current chunk
                    s_val = max(min_idx, min(max_idx, s_val))
                    e_val = max(min_idx, min(max_idx, e_val))
                    
                    # Ensure the start index is less than or equal to the end index
                    if s_val > e_val:
                        s_val, e_val = e_val, s_val
                        
                    # Append the sanitized topic data to our cleaned list
                    cleaned.append({
                        "title": str(title),
                        "start_idx": s_val,
                        "end_idx": e_val,
                        "category": str(category).lower()
                    })
                except (ValueError, TypeError):
                    # Ignore and drop any topics where indices couldn't be parsed as integers
                    pass
            # Return the successfully cleaned list of topics
            return cleaned, None
        else:
            # Handle HTTP errors from the API
            return None, f"API Error: Status {r.status_code} - {r.text}"
    except Exception as e:
        # Handle connection errors or other exceptions during the request
        return None, f"Request Error: {e}"


## Function to score the topics returned by the LLM, so we know if they should be yeeted
## We do this by checking the category, the duration, and looking for naughty keywords
## Anything scoring 6 or higher gets flagged as an advert

## With the LLM improvements and current limitation on this (not checking the transcript etc, just the topic). Not quite sure if this is worth keeping..
## I was wondering if instead we could either do another LLM pass? (i.e. the round 3 we had from the final prototype)

def score_topic(topic):
    score = 0
    cat = topic["category"].lower()
    title = topic["title"].lower()
    duration = topic["end_idx"] - topic["start_idx"] + 1
    
    # 1. Category Weighting
    if "sponsor" in cat or "ad" in cat or "advert" in cat:
        score += 10
    elif cat == "podcast_promotion":
        score += 10
    # Note: intro_outro, show_content, other, and self_promotion get 0 base category score
        
    # 2. Duration Weighting
    if duration <= 40:
        score += 4
    elif duration <= 60:
        score += 1
    elif duration > 70:
        score -= 8
        
    # 3. Keyword Check
    keywords = ["sponsor", "code", "discount", "website", "support for", "creator destroy", "promo", "advertisement", "advertise", "subscribe", "newsletter", "offer", "visit", "save", "saving", "price", "buy", "purchase", "checkout", "money back"]
    found_kw = False
    for kw in keywords:
        if kw in cat or kw in title:
            found_kw = True
            break
    if found_kw:
        score += 3
        
    return score

## Top level function to call, to detect adverts (and now other stuff), in a single SRT file
## This is the new single-pass champion that chunks the SRT and passes it to Qwen to do all the heavy lifting
def detect_adverts(srt_file, raw_folder):
    global ollama_url, model_to_use
    
    # Load config to determine what content to remove
    config = {}
    if os.path.exists("config.toml"):
        with open("config.toml", "rb") as f:
            config = toml.load(f)
    content_to_remove = config.get("content_to_remove", {
        "sponsor_read": True,
        "podcast_promotion": True,
        "self_promotion": False,
        "intro_outro": False,
        "show_content": False,
        "other": False
    })
    
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
        
    ##Number of chunks we feed into the LLM at once, along with the overlap between them (i.e. if advert is on boundary, it'll get picked up on other iteration in context)
    total = len(blocks)
    chunk_size = 120
    overlap = 15

    # --- TOPIC MAPPING ---
    print("\n--- Topic Mapping & Classification ---")
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
            res, err = ask_phase1_topics(ollama_url, model_to_use, chunk)
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
        
    print(f"Topic mapping complete. Total raw topics mapped: {len(all_topics)}")
    
    # --- PRINT TOPIC MAP TABLE & APPLY WEIGHTING ---
    print("\n--- GENERATED TOPIC MAP & WEIGHTING ---")
    print(f"{'Start':<6} | {'End':<6} | {'Duration':<8} | {'Category':<18} | {'Score':<5} | {'Title'}")
    print("-" * 100)
    
    flagged_indices = set()
    
    for t in all_topics:
        duration = t["end_idx"] - t["start_idx"] + 1
        score = score_topic(t)
        
        cat = t['category'].lower()
        
        # Check if the LLM's chosen category is toggled ON for removal in the config
        is_flagged = content_to_remove.get(cat, False)
        
        # Safety net: If the heuristic score is high (indicating a sneaky ad block)
        # AND the user wants sponsor reads removed, flag it anyway,
        # but ONLY if it wasn't explicitly categorised as a type the user wants to keep.
        if not is_flagged and score >= 6 and content_to_remove.get("sponsor_read", True):
            if cat in ["show_content", "other"]:
                is_flagged = True

        flagged_str = "[FLAGGED]" if is_flagged else "       "
        print(f"{t['start_idx']:<6} | {t['end_idx']:<6} | {duration:<8} | {t['category']:<18} | {score:<5} | {t['title']} {flagged_str}")
        
        if is_flagged:
            for idx in range(t["start_idx"], t["end_idx"] + 1):
                flagged_indices.add(idx)
                
    print("-" * 100)
    
    if not flagged_indices:
        print("No ad breaks flagged by the weighting heuristic.")
        with open(ad_path, "w", encoding="utf-8") as f:
            pass
        print("Created empty .ad file.")
        return
        
    # Gap filling: If there is a small gap (<= 7 blocks) between two ad blocks, merge them.
    sorted_ads = sorted(list(flagged_indices))
    final_ads = set()
    if sorted_ads:
        current = sorted_ads[0]
        final_ads.add(current)
        for idx in sorted_ads[1:]:
            if idx - current <= 8:  # Allow bridging a small gap of ~7 unflagged blocks
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
