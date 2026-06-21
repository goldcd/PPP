import os
import sys
import time
import torch
import requests
import json

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
    chunks = [raw_blocks[i:i + chunk_size] for i in range(0, len(raw_blocks), step)]
    ad_block_indices = set()

    print(f"Processing transcript in {len(chunks)} overlapping chunks...")

    for i, chunk in enumerate(chunks):
        # Join the blocks in this chunk back together into a string
        chunk_text = "\n\n".join(chunk)

        # Calculate approximate progress in the episode
        progress = f"Chunk {i+1} of {len(chunks)}"

        # Get the first and last SRT index in this chunk for grounding the model
        first_idx = chunk[0].strip().split("\n")[0].strip()
        last_idx  = chunk[-1].strip().split("\n")[0].strip()

        
        # The more complex my prompt was getting, the seemingly worse my results...
        prompt = (
            f"You are analyzing a segment of a podcast transcript ({progress})\n\n"
            "GOAL:Identify the SRT index ranges of all advertisement blocks and sponsor reads.\n\n"
            "Some segments may be entirely adverts, or contiguous groups of adverts. Don't worry about how much of a segment you're identifying as adverts."
            "Obviously advert segments are more likely to be next to other advert segments. So weight based upon adjancencies.\n"
            "Segments are being provided sequentially with an overlap of 10 - so if you're unsure about the very edges, it will be picked up by the next segment.\n"
            "A block of adverts is likely to span over 30 seconds, but be under several minutes."
            "Respond ONLY with a valid JSON object. Do not include markdown formatting or explanations.\n"
            "If an advert runs from block 10 to 15, return it as a range: [10, 15]. For a single block, return [20, 20].\n"
            "{\"advert_ranges\": [[10, 15], [20, 20]]}\n"
            "If no ads are found, return: {\"advert_ranges\": []}\n\n"
            f"Transcript Segment:\n{chunk_text}"
        )

        
        """

        prompt = (
            f"You are analyzing a segment of a podcast transcript ({progress}).\n"
            "Identify any blocks in this segment that are advertisements or sponsor reads.\n"
            "Adverts are often clustered together, so look for groups of adverts.\n"
            "Individual adverts and runs of adverts are likely to run over contiguous blocks of the transcript.\n"
            "Return a JSON object containing a list 'advert_indices' which is an array of SRT indexes (numbers) that are advertisements.\n"
            f"Only return indices between {first_idx} and {last_idx} — the range present in this segment.\n"
            "Format of response MUST be JSON: {\"advert_indices\": [1, 2, 3]}\n"
            "If no ads are found, return: {\"advert_indices\": []}\n\n"
            f"Transcript Segment:\n{chunk_text}"
        )
        

        prompt = (
             f"You are analyzing chunk of a podcast transcript.\n"
            "Analyze the following transcript in SRT format and identify the index ranges of all advertisement blocks and sponsor reads.\n"
            "These ads often have a fixed duration of 30 - 60 seconds and are frequently clumped together back-to-back.\n"
            f"Only return indices between {first_idx} and {last_idx} — the range present in this segment.\n"
            "Format of response MUST be JSON: {\"advert_indices\": [1, 2, 3]}\n"
            "If no ads are found, return: {\"advert_indices\": []}\n\n"
            f"Transcript Segment:\n{chunk_text}"
        )
        """

        try:
            print(f"  Analyzing chunk {i+1}/{len(chunks)}...")

            # Build the set of SRT indices actually present in this chunk for validation
            valid_chunk_indices = set()
            for block in chunk:
                lines = block.strip().split("\n")
                try:
                    valid_chunk_indices.add(int(lines[0].strip()))
                except (ValueError, IndexError):
                    continue

            # Start with base messages
            messages = [
                {"role": "system", "content": "You are a precise podcast ad detector. You output JSON containing only the 'advert_ranges' key. Do not include markdown blocks."},
                {"role": "user", "content": prompt}
            ]

            max_retries = 4
            for attempt in range(max_retries + 1):
                response = requests.post(
                    ollama_url,
                    json={
                        "model": ollama_model,
                        "messages": messages,
                        "stream": False,
                        "format": "json",
                        "options": {
                            "temperature": 0.0
                        }
                    },
                    timeout=None  # Wait as long as needed - real failures will raise, not silently skip
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result.get("message", {}).get("content", "{}")
                    
                    # Guard against Ollama occasionally returning empty content
                    if not content.strip():
                        print(f"    -> Warning: Empty response from Ollama for chunk {i+1}, skipping.")
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

                    # If model hallucinated old/invalid indices, feed the error back into context and retry
                    if hallucinated and attempt < max_retries:
                        print(f"    -> Warning: Hallucinated indices {hallucinated}. Retrying ({attempt+1}/{max_retries})...")
                        messages.append({"role": "assistant", "content": content})
                        messages.append({
                            "role": "user", 
                            "content": f"Error: You returned indices {hallucinated} which are NOT present in this chunk. The valid indices for this chunk are between {first_idx} and {last_idx}. Please try again and ONLY return indices that physically exist in the transcript segment provided."
                        })
                        continue  # Retry with the updated message history!

                    if hallucinated and attempt == max_retries:
                        print(f"    -> Warning: Max retries reached. Discarding {len(hallucinated)} hallucinated index/indices.")

                    if validated:
                        print(f"    -> Found ad indices in chunk: {validated}")
                    else:
                        print(f"    -> No ads detected in chunk.")
                        
                    for idx in validated:
                        ad_block_indices.add(int(idx))
                        
                    break  # Success! Exit the retry loop
                else:
                    print(f"    -> Error calling Ollama (Status {response.status_code}): {response.text}")
                    break

        except Exception as e:
            print(f"    -> Exception occurred during chunk analysis: {e}")

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
