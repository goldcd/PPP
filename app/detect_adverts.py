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
ollama_model = None 


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
    #Just going to make these global, so I don't need to pass them about. I'm lazy. And I've not used globals here, so good practice.
    global ollama_url, ollama_model
    
    #This whole TOML thing seems to require way more code than a I thought.. what is the point of it?
    #*pastes*
    config = {}
    if os.path.exists("config.toml"):
        with open("config.toml", "rb") as f:
            config = toml.load(f)
    ollama_config = config.get("ollama", {})
    ollama_url = ollama_config.get("ollama_url", "http://localhost:11434/api/chat")
    
    ## Work out which model we need, then try to get it from config, and fallback to defaults.. Seriously, there's got to be a better config mechanism
    ##AI says there is - but I'm not arsed enough yet. To copy and paste blindly is to be human
    force_cpu = config.get("processing", {}).get("force_cpu", False)
    if torch.cuda.is_available() and not force_cpu:
        ollama_model = ollama_config.get("gpu_model", "gemma4:12b")
        print(f"\n Using GPU model '{ollama_model}' for advert detection \n")
    else:
        ollama_model = ollama_config.get("cpu_model", "gemma4:e2b")
        if force_cpu:
            print(f"\n force_cpu=true in config.toml — using CPU model '{ollama_model}' for advert detection \n")
        else:
            print(f"\n Using CPU model '{ollama_model}' for advert detection \n")
    
    # Pre-warm/load the model into memory
    print(f"Requesting Ollama to load: {ollama_model}")
    try:
        response = requests.post(
            ollama_url,
            json={"model": ollama_model, "messages": [], "stream": False},
            timeout=10
        )

        ## This block's AI. If the model isn't there, it downloads it. Apparently.
        if response.status_code == 404:
            print(f"Model '{ollama_model}' not found locally. Initiating download...")
            pull_url = ollama_url.replace("/api/chat", "/api/pull")
            pull_response = requests.post(
                pull_url,
                json={"name": ollama_model, "stream": False},
                timeout=600  # Give it up to 10 minutes depending on speed
            )
            if pull_response.status_code == 200:
                print(f"Successfully downloaded {ollama_model}!")
                requests.post(ollama_url, json={"model": ollama_model, "messages": [], "stream": False})
            else:
                print(f"Failed to download model: {pull_response.text}")

    except Exception as e:
        print(f"Failure to load model: {e}")

## Function to tidy up the model when we're done
def stop_ollama():
    global ollama_url, ollama_model
    if ollama_url and ollama_model:
        print(f"Unloading {ollama_model} from memory...")
        try:
            ## Setting keep_alive to 0 tells Ollama to clear memory right now
            requests.post(
                ollama_url,
                json={"model": ollama_model, "messages": [], "stream": False, "keep_alive": 0},
                timeout=5
            )
        except Exception as e:
            print(f"Warning: Could not unload model: {e}")

##The actual function to process the .srt file and detect the adverts
##Took quite a while of boring stuff to get here. So "hurrah!"
##Scope of this is to take in a path and an SRT file in it. Then we'll write back a modified version of the srt with the .ad extension, that hopefully just contains the adverts to remove
## which is another task.. but onwards.
## I think it might have been better to retain the content - but this is easier for me to check (i.e. is everything in the output a dull advert?)
## better to not remove all the adverts, than start chomping random bits of content out.

##I gave up trying to do this manually. AI can have this function..
def detect_adverts(srt_file, raw_folder):
    global ollama_url, ollama_model
    
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
    raw_blocks = raw_srt_content.replace("\r\n", "\n").strip().split("\n\n")
    if not raw_blocks or not raw_blocks[0]:
        print("No blocks found in SRT file.")
        return

    # Process in overlapping chunks to handle ads straddling boundaries
    # chunk_size of 50 with step of 40 creates a 10-block overlap (~60-90s of audio)
    # Note: 100-block chunks exceed Ollama's default 4096 token context window
    chunk_size = 50
    step = 40
    ad_block_votes = Counter()    # How many chunks flagged this block as an ad
    block_coverage = Counter()    # How many chunks even saw this block
    total_blocks = len(raw_blocks)

    print(f"Processing transcript of {total_blocks} blocks with dynamic overlapping chunks...")

    current_start_idx = 0
    chunk_count = 0
    jitter_applied = False

    while current_start_idx < total_blocks:
        chunk = raw_blocks[current_start_idx : current_start_idx + chunk_size]
        if not chunk:
            break
            
        chunk_count += 1
        chunk_text = "\n\n".join(chunk)

        # Calculate approximate progress in the episode
        progress = f"Chunk {chunk_count} (~{min(100, int((current_start_idx/total_blocks)*100))}% through episode)"

        # Get the first and last SRT index in this chunk for grounding the model
        first_idx = chunk[0].strip().split("\n")[0].strip()
        last_idx  = chunk[-1].strip().split("\n")[0].strip()


        # Build overlap context from previously detected ad blocks to give the model
        # awareness of what's been found in adjacent/overlapping regions
        overlap_context = ""
        if ad_block_votes:
            try:
                first_int = int(first_idx)
                last_int = int(last_idx)
                # Blocks in the overlap region of this chunk that were already flagged
                already_flagged = sorted([idx for idx in ad_block_votes if first_int <= idx <= last_int])
                if already_flagged:
                    overlap_context = (
                        f"Context from previous analysis: blocks {already_flagged[0]}-{already_flagged[-1]} "
                        f"in this segment were already identified as advertisements. "
                        "Blocks adjacent to this range are likely also part of the same ad break.\n\n"
                    )
                else:
                    # How recently did the last ad end before this chunk?
                    preceding_ads = [idx for idx in ad_block_votes if idx < first_int]
                    if preceding_ads:
                        last_ad = max(preceding_ads)
                        gap = first_int - last_ad
                        if gap <= 15:
                            overlap_context = (
                                f"Context: Advertisements were detected ending at block {last_ad}, "
                                f"only {gap} blocks before this segment starts. "
                                "This segment may be continuing that ad break.\n\n"
                            )
                        else:
                            overlap_context = (
                                f"Context: The last advertisement was at block {last_ad} "
                                f"({gap} blocks before this segment). "
                                "Any ads here would be a fresh, independent ad break.\n\n"
                            )
            except (ValueError, TypeError):
                pass

        prompt = (
            "You are analyzing a podcast transcript for advertisements.\n"
            f"Identify all advertisement blocks in the SRT segment below (indices {first_idx} to {last_idx}).\n\n"
            "Ads typically contain: sponsor mentions ('brought to you by', 'sponsored by', 'thanks to'), "
            "product names, discount codes, website URLs, or calls to action.\n"
            "Regular podcast content (interviews, news, banter, storytelling) is NOT an ad.\n"
            "Ad breaks last 30 seconds to a few minutes. Multiple ads often run back-to-back with no gap between them.\n"
            "If surrounding blocks are clearly ads, treat the whole run as a single ad break.\n\n"
            "End of show credits and references to the show itself, should not be considered adverts.\n\n"
            f"{overlap_context}"
            "Return JSON with the SRT index ranges of all ads.\n"
            "Example: {\"advert_ranges\": [[10, 15], [20, 20]]}\n"
            "No ads: {\"advert_ranges\": []}\n\n"
            f"Transcript:\n{chunk_text}"
        )

        try:
            print(f"  Analyzing chunk {chunk_count} (blocks {current_start_idx} to {current_start_idx+len(chunk)})...")
            chunk_success = False

            # Build the set of SRT indices actually present in this chunk for validation
            valid_chunk_indices = set()
            for block in chunk:
                lines = block.strip().split("\n")
                try:
                    idx = int(lines[0].strip())
                    valid_chunk_indices.add(idx)
                    block_coverage[idx] += 1  # Track how many chunks see each block
                except (ValueError, IndexError):
                    continue

            # Start with base messages
            messages = [
                {"role": "system", "content": "You are a precise podcast ad detector. You output JSON containing only the 'advert_ranges' key. Do not include markdown blocks."},
                {"role": "user", "content": prompt}
            ]

            max_retries = 2
            for attempt in range(max_retries + 1):
                response = requests.post(
                    ollama_url,
                    json={
                        "model": ollama_model,
                        "messages": messages,
                        "stream": False,
                        "format": "json",
                        "options": {
                            "temperature": 0.1
                        }
                    },
                    timeout=None  # Wait as long as needed - real failures will raise, not silently skip
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result.get("message", {}).get("content", "{}")
                    
                    # Guard against Ollama occasionally returning empty content
                    if not content.strip():
                        if attempt < max_retries:
                            print(f"    -> Warning: Empty response from Ollama for chunk {chunk_count}. Retrying ({attempt+1}/{max_retries})...")
                            messages.append({"role": "assistant", "content": ""})
                            messages.append({
                                "role": "user", 
                                "content": "Error: You returned an empty response. You MUST return a valid JSON object containing the 'advert_ranges' key. If there are no ads, return {\"advert_ranges\": []}."
                            })
                            continue
                        else:
                            print(f"    -> Warning: Max retries reached for empty responses for chunk {chunk_count}. Triggering jitter.")
                            break
                            
                    data = json.loads(content)
                    ranges = data.get("advert_ranges", [])
                    
                    indices = []
                    for r in ranges:
                        if isinstance(r, list) and len(r) >= 2:
                            indices.extend(range(int(r[0]), int(r[1]) + 1))
                        elif isinstance(r, list) and len(r) == 1:
                            indices.append(int(r[0]))
                        elif isinstance(r, (int, float, str)):
                            # Just in case it hallucinates flat numbers despite instructions
                            try:
                                indices.append(int(r))
                            except ValueError:
                                pass

                    validated = [idx for idx in indices if int(idx) in valid_chunk_indices]
                    hallucinated = [idx for idx in indices if int(idx) not in valid_chunk_indices]

                    if hallucinated:
                        print(f"    -> Warning: Model hallucinated {len(hallucinated)} indices (e.g. {hallucinated[:3]}). Triggering jitter.")
                        # Leaving chunk_success as False will trigger the jitter logic below
                        break
                    else:
                        if validated:
                            print(f"    -> Found ad indices in chunk: {validated}")
                        else:
                            print(f"    -> No ads detected in chunk.")
                            
                        for idx in validated:
                            ad_block_votes[int(idx)] += 1
                            
                        chunk_success = True
                        break # Success!
                else:
                    print(f"    -> Error calling Ollama (Status {response.status_code}): {response.text}")
                    break

            if not chunk_success:
                if not jitter_applied and current_start_idx >= 15:
                    print(f"    -> Chunk failed completely. Applying a 15-block backward jitter and retrying...")
                    current_start_idx -= 15
                    jitter_applied = True
                    continue  # Try the while loop again at new index
                else:
                    print(f"    -> Chunk failed completely despite jitter (or at start). Moving on.")
                    current_start_idx += step
                    jitter_applied = False
            else:
                current_start_idx += step
                jitter_applied = False

        except Exception as e:
            print(f"    -> Exception occurred during chunk analysis: {e}")
            current_start_idx += step
            jitter_applied = False

    # Build the final ad block set using consensus voting.
    # A block must be flagged by at least as many chunks as it was seen by (capped at 2).
    # This eliminates false positives from a single chunk over-extending at a boundary,
    # while preserving true ads that only appear in one chunk (e.g., intro ads).
    ad_block_indices = {
        idx for idx, votes in ad_block_votes.items()
        if votes >= min(2, block_coverage.get(idx, 1))
    }

    # Filter and write matching blocks to the .ad file
    ad_blocks = []
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        try:
            idx = int(lines[0].strip())
            if idx in ad_block_indices:
                ad_blocks.append(block)
        except (ValueError, IndexError):
            continue

    if ad_blocks:
        with open(ad_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(ad_blocks) + "\n\n")
        print(f"Saved {len(ad_blocks)} advertisement blocks to {ad_path}")
    else:
        with open(ad_path, "w", encoding="utf-8") as f:
            pass
        print("No ads detected. Created empty .ad file.")
