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
   - Flagging & Gap Filling: Flags topics for removal if they match the user's config categories It then bridges small gaps between flagged segments to create continuous ad blocks.
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
    
    def parse_time(t_str):
        t_str = t_str.replace(',', '.')
        h, m, s = t_str.split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)

    for rb in raw_blocks:
        lines = rb.strip().split("\n")
        if len(lines) >= 3:
            try:
                idx = int(lines[0].strip())
                
                # Parse time from line 2
                time_line = lines[1].strip()
                start_time = 0.0
                end_time = 0.0
                duration = 0.0
                if " --> " in time_line:
                    start_str, end_str = time_line.split(" --> ")
                    start_time = parse_time(start_str)
                    end_time = parse_time(end_str)
                    duration = end_time - start_time

                text = " ".join(lines[2:]).strip()
                blocks.append({
                    ##The index of the block
                    "idx": idx,
                    ##The content/transcript of the block
                    "text": text,
                    ##An unmolested and complete (but trimmed) version of the block as it appeared in the original file
                    "raw": rb.strip(),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration
                })
            except Exception:
                pass
    return blocks

def auto_heal_gaps(cleaned_topics, min_idx, max_idx):
    if not cleaned_topics:
        return cleaned_topics
        
    # Sort topics by start index just in case LLM returned them out of order
    cleaned_topics.sort(key=lambda x: x['start_idx'])
    
    # 1. Ensure the first topic starts at min_idx
    if cleaned_topics[0]['start_idx'] > min_idx:
        cleaned_topics[0]['start_idx'] = min_idx
        
    # 2. Heal any gaps between consecutive topics
    for i in range(len(cleaned_topics) - 1):
        current_end = cleaned_topics[i]['end_idx']
        next_start = cleaned_topics[i+1]['start_idx']
        
        if current_end < next_start - 1:
            # Expand the current topic's end_idx to close the gap
            cleaned_topics[i]['end_idx'] = next_start - 1
            
    # 3. Ensure the last topic ends at max_idx
    if cleaned_topics[-1]['end_idx'] < max_idx:
        cleaned_topics[-1]['end_idx'] = max_idx
        
    return cleaned_topics

## Function to take in the list of block dictionaries, and give us our first idea of segments
##Ignore that it's called phase 1 - there were more, but it got stupidly complicated..
def ask_phase1_topics(url, model, blocks_subset, previous_context=None):
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
    
    ##Old version of the prompt, whilst I make big changes below
    """
    sys_msg = (
        "You are a podcast content segmenter and topic mapper.\n"
        "Your task is to analyze this segment of the transcript and partition it chronologically into distinct topics or segments covered in the show.\n"
        f"CRITICAL INSTRUCTION: Every single block from {min_idx} to {max_idx} MUST be included in a topic.\n"
        "CRITICAL INSTRUCTION: The topics must be strictly contiguous with no gaps (e.g. 101-110, 111-115, 116-150).\n"
        "CRITICAL INSTRUCTION: Break the transcript into distinct topics based on natural conversation shifts.\n"
        "CRITICAL INSTRUCTION: Carefully identify any advertisements or sponsor reads. They are usually short (2-15 blocks) and MUST be placed in their own isolated 'sponsor_read' topics.\n"
        "CRITICAL INSTRUCTION: Ensure your topic lengths vary naturally according to the conversation (e.g. one topic might be 3 blocks long, another might be 45 blocks long).\n\n"
        "For each topic, identify:\n"
        "1. Short title\n"
        "2. Start block index and end block index (inclusive)\n"
        "3. Category: Choose exactly one of: 'show_content', 'sponsor_read', 'podcast_promotion', 'self_promotion', 'intro_outro'.\n\n"
        "Category Definitions:\n"
        "- 'show_content': Primary show conversation, stories, news, interviews, or banter.\n"
        "- 'sponsor_read': Commercial pitches for external companies/products/services (e.g. software, B2B, consumer goods, retail stores, food/drink, savings etc.) and any other kind of commercial or sponsorship promotion. Classify ALL obvious advertisements as sponsor_read!\n"
        "- 'podcast_promotion': Promos/trailers/credits for other podcasts, channels, or shows (e.g. cross-promotions like 'Creator Destroy').\n"
        "- 'self_promotion': Promotion of the current podcast (e.g. live shows, patreon, paid ad-free versions of this podcast, merchandise etc).\n"
        "- 'intro_outro': Standard show intro theme, greeting, outro wrap-up, or ending credits.\n\n"
        "You MUST return ONLY a valid JSON object matching the structure below. This is an example of variable-length chunking:\n"
        "{\n"
        "  \"analysis\": \"I will first summarize the entire text from start to finish. I see an intro from blocks X-Y, a sponsor read for Brand Z from blocks A-B, and then main content...\",\n"
        "  \"topics\": [\n"
        "    {\n"
        "      \"title\": \"Example Intro\",\n"
        f"      \"start_idx\": {min_idx},\n"
        f"      \"end_idx\": {min(max_idx, min_idx + 3)},\n"
        "      \"category\": \"intro_outro\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Example Sponsor\",\n"
        f"      \"start_idx\": {min(max_idx, min_idx + 4)},\n"
        f"      \"end_idx\": {min(max_idx, min_idx + 11)},\n"
        "      \"category\": \"sponsor_read\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Example Main Segment\",\n"
        f"      \"start_idx\": {min(max_idx, min_idx + 12)},\n"
        f"      \"end_idx\": {max_idx},\n"
        "      \"category\": \"show_content\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    
    sys_msg = (
        "You are a podcast content segmenter and topic mapper.\n"
        "Your task is to fully and carefully analyse this provided segment of the show and then partition it chronologically into distinct topics or segments.\n"
        f"CRITICAL INSTRUCTION: Every single provided block from {min_idx} to {max_idx} MUST be included in a topic.\n"
        "CRITICAL INSTRUCTION: The topics must be strictly contiguous with no gaps (e.g. 101-110, 111-115, 116-150).\n"
        "CRITICAL INSTRUCTION: Break the transcript into distinct topics based on natural conversation shifts.\n"
        "CRITICAL INSTRUCTION: Especially identify any promotional content. They are usually short (2-15 blocks) and MUST be placed in their own isolated topics.\n"
        "CRITICAL INSTRUCTION: The precise boundaries of the blocks are critical. Once you think you've identified a boundary, look on both preceeding and following blocks again to confirm you are exactly right. Do not make snap decisions. \n"
        "CRITICAL INSTRUCTION: Hosts will often signpost a break in the show with phrases like 'let's take a short break', 'a message from our sponsor', 'we'll be right back', or 'after the break'.\n"
        "NOTE: A break can lead into a 'sponsor_read', a 'podcast_promotion', OR a 'self_promotion'. Do not assume all breaks are sponsor reads. Look carefully at what is being promoted.\n"
        "Often multiple promotions are placed back-to-back to create an advertising block. Identify all of these and categorize them appropriately.\n"
        "Hosts will often signpost the end of a break and a return to regular show content with phrases like 'Welcome back' or 'back to the show'.\n" 
        "For each topic, identify:\n"
        "1. Short title\n"
        "2. Start block index and end block index (inclusive)\n"
        "3. Category: Choose exactly one of: 'show_content', 'sponsor_read', 'podcast_promotion', 'self_promotion', 'intro_outro'.\n\n"
        "Category Definitions:\n"
        "- 'show_content': Primary show conversation, stories, news, interviews, or banter.\n"
        "- 'sponsor_read': Commercial pitches/advertisements for EXTERNAL companies/products/services/charities (e.g. software, B2B, consumer goods, retail stores, food/drink, savings etc.). Classify ALL obvious advertisements for 3rd parties as sponsor_read. N.B. Discussion of a generic item is not necessarily an advert - it must refer to a specific brand name/company.\n"
        "- 'podcast_promotion': Promos/trailers/credits for OTHER podcasts, channels, or shows. Similar to sponsor_reads/adverts, but for other shows or content creators. Keep these distinct from sponsor_reads.\n"
        "- 'self_promotion': Promotion of THIS podcast or its hosts (e.g. live shows, festivals, tours, patreon, paid ad-free versions, merchandise, appearances). Even if it mentions tickets or websites, if it's about seeing the hosts/podcast live, it is self_promotion.\n"
        "- 'intro_outro': Standard show intro theme, greeting, outro wrap-up, or ending credits.\n\n"
        "You MUST return ONLY a valid JSON object matching the structure below. This is an example of variable-length chunking:\n"
        "{\n"
        "  \"analysis\": \"I will first summarize the entire text from start to finish. I see an intro from blocks X-Y, a sponsor read for Brand Z from blocks A-B, and then main content...\",\n"
        "  \"topics\": [\n"
        "    {\n"
        "      \"title\": \"Example Intro\",\n"
        f"      \"start_idx\": {min_idx},\n"
        f"      \"end_idx\": {min(max_idx, min_idx + 3)},\n"
        "      \"category\": \"intro_outro\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Example Sponsor\",\n"
        f"      \"start_idx\": {min(max_idx, min_idx + 4)},\n"
        f"      \"end_idx\": {min(max_idx, min_idx + 11)},\n"
        "      \"category\": \"sponsor_read\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Example Main Segment\",\n"
        f"      \"start_idx\": {min(max_idx, min_idx + 12)},\n"
        f"      \"end_idx\": {max_idx},\n"
        "      \"category\": \"show_content\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
"""    
    sys_msg = (
        "You are a podcast content segmenter and topic mapper.\n"
        "Your purpose is to fully and carefully analyse this provided segment of the show and then partition it chronologically into distinct topics or segments. This information will be used to produce an edited version of the podcasts with selected items removed.\n"
        "A simple way to consider this task, is that you're being asked to create the chapter markings for a podcast that lacks them.\n"
        "Your first step, before doing anything else, is to read the entire provided segment of the show from start to finish. Use this complete context to inform your decisions. This is critical - do not take shortcuts! Accuracy is paramount, even at the expense of speed.\n\n"
        "CRITICAL INSTRUCTION: Break the transcript into the distinct topics as detailed in the transcription. \n"
        "For each topic, identify:\n"
        "1. Short title\n"
        "2. Start block index and end block index (inclusive)\n"
        "3. Category: Choose exactly one of: 'show_content', 'sponsor_read', 'podcast_promotion', 'self_promotion', 'intro_outro'.\n"
        "4. Take a deep breath and work on this problem carefully. This is not a task where a general output is acceptable. This is lights-out, one-shot, high-stakes. This is your last chance before I'm forced to switch my LLM model.\n\n"
    )
    
    if previous_context:
        sys_msg += f"CRITICAL CONTEXT FROM PREVIOUS CHUNK:\n{previous_context}\n\n"
        
    sys_msg += (
        "Category Definitions:\n"
        "- 'show_content': Super-set of all primary show conversation, stories, news, interviews, or banter. What a listener would refer to as 'the podcast itself'. This category is for the main content of the show we'd expect any listener to want to keep. i.e. You should assume initially the whole podcast transcipt is 'show_content' - then carve out out other segment types as you match them.\n"
        "- 'intro_outro': A sub-set of show_content. Standard show intro theme, greeting, outro wrap-up, or ending credits.\n"
        "- 'self_promotion': A sub-set of show_content. This category is for promotion of the podcast itself or its hosts. (e.g. live shows, festivals, tours, patreon, paid ad-free versions, merchandise, appearances, or promoting other episodes/series on this podcast's own feed). \n"
        "- 'sponsor_read': Super-set of all advertising (excluding self_promotion) that appears on the podcast - Commercial pitches/advertisements for EXTERNAL companies/products/services/charities/movies/events (e.g. software, B2B, consumer goods, retail stores, food/drink, savings, film releases, cross-promos from other network hosts etc.). 'Promotions', 'Discount Codes', URLs and general positivity about a service are strong indicators it's an advert. N.B. Discussion of a generic item is not necessarily an advert - it must refer to a specific brand name/company.\n"
        "- 'podcast_promotion': Sub-set of sponsor_read. Promos/trailers/credits for OTHER podcasts, audio channels, or audio shows. IMPORTANT: Do NOT use this for general discussions about TV shows or movies (which belong in 'show_content').\n\n"
        "IMPORTANT HINTS for classification:\n"
        "- Individual items of sponsor_read are often grouped together into larger blocks of advertising. Each item should be individually identified with its own topic/sponsor.\n"
        "- Hosts will often signpost a sponsor_read in the show with phrases like 'let's take a short break', 'a message from our sponsor', 'we'll be right back', or 'after the break'. The end of such a sponsor_read block may be signposted with similar phrases such as 'Welcome back' or 'back to the show'.\n"
        "- Individual sponsor_read items are often 30-60 seconds in duration. However they can be longer or shorter. Do not make assumptions about the duration of the content in blocks.\n"
        "- sponsor_read segments are usually unrelated to the content around them and the themes of the podcast.\n"
        "- sponsor_read segments sometimes include a short discussion to make them appear more organic. Normally these can be identified by explicit references to the sponsor around the seemingly organic component.\n"
        "- sponsor_read sections are self-contained adverts. CHECK the identified block actually matches a self-contained advert. The advert should be entirely in the identified block, the surrounding blocks should be unrelated.\n"
        "- Whilst the categories are related, they are distinct. Carefully consider which ONE every section of the podcast best fits to.\n"
        "- Do not confuse a short mentioning/reference of a company or service in passing to be a sponsor_read.\n"
        "- A genuine sponsor_read is always explicitly promotional (or a PSA/charity appeal): the speaker will be actively describing a product, service, or charity, and directing the listener to take some action (e.g. visit a URL, use a discount code, donate, sign up - 'a call to action'). Be careful not to confuse news bulletins about disasters with charity appeals; if it asks for money or directs to a donation URL, it is a sponsor_read. If the content is purely conversational, factual news, or anecdotal without a call to action, it is show_content.\n"
        "- All the previous rules are guidance. I have no idea what podcasts you'll be asked to process, so please adapt, rather than blindly follow.\n"
        "- What is mandatory is accurate classification of the sections - mistakes made here cannot be undone later. There's no fallback or workaround.\n\n"
        "CRITICAL PROCESSING:\n"
        "- Once you believe you have categorized all the provided blocks, before returning a result, check you are satisfied with the categorization.\n"
        "- Do not get lazy with your checking. All blocks are of equal and critical importance for analysis.\n"
        "- Pay attention to the boundaries of the blocks, look on either side to check you're happy with the placement.\n"
        "- Be extremely precise when an advert transitions into the main show. If an advert ends and the very next block contains the show's formal greeting (e.g. 'Hello and welcome to...'), that block MUST be the start of the 'intro_outro' segment, it should not be lumped into the preceding 'sponsor_read'.\n\n"
        "CRITICAL OUTPUT INSTRUCTIONS:\n"
        f"- Every single provided block from {min_idx} to {max_idx} MUST be included in a topic.\n"
        "- The topics must be strictly contiguous with no gaps (e.g. 101-110, 111-115, 116-150).\n"
        "- You MUST return ONLY a valid JSON object matching the structure below. This is an example of variable-length chunking:\n"
        "{\n"
        "  \"analysis\": \"I will first summarize the text. Blocks 101 to 119 contain organic banter which acts as a purely conversational setup for an advert for Brand X, so all 19 blocks are a single sponsor_read. Blocks 120 to 136 are a distinct, separate advert for Service Y. Blocks 137 to 151 feature a guest host promoting a new movie release, which is a sponsor_read (NOT intro_outro, despite starting with a 'Hello'). The actual show intro begins at 152 with 'Hello and welcome to this episode', which is intro_outro, leading into the first main conversational topic about a popstar at 157 which is show_content.\",\n"
        "  \"topics\": [\n"
        "    {\n"
        "      \"title\": \"Brand X Ad (with organic lead-in)\",\n"
        "      \"start_idx\": 101,\n"
        "      \"end_idx\": 119,\n"
        "      \"category\": \"sponsor_read\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Service Y Ad\",\n"
        "      \"start_idx\": 120,\n"
        "      \"end_idx\": 136,\n"
        "      \"category\": \"sponsor_read\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Movie Promo\",\n"
        "      \"start_idx\": 137,\n"
        "      \"end_idx\": 151,\n"
        "      \"category\": \"sponsor_read\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Show Intro\",\n"
        "      \"start_idx\": 152,\n"
        "      \"end_idx\": 156,\n"
        "      \"category\": \"intro_outro\"\n"
        "    },\n"
        "    {\n"
        "      \"title\": \"Main Show Topic 1\",\n"
        "      \"start_idx\": 157,\n"
        "      \"end_idx\": 250,\n"
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
                    "num_ctx": 12288
                },
                "format": "json"
            },
            timeout=300,
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
                category = t.get("category", "show_content")
                
                # Extract start and end indices, accounting for potential key name variations from the LLM
                s_idx = t.get("start_idx") or t.get("start_index") or t.get("start_rx") or t.get("start")
                e_idx = t.get("end_idx") or t.get("end_index") or t.get("end_rx") or t.get("end")
                
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
            if len(cleaned) == 0:
                print(f"\n  [DEBUG] LLM returned 0 valid topics. Raw output was:\n{raw}\n")
            else:
                cleaned = auto_heal_gaps(cleaned, min_idx, max_idx)
            return cleaned, None
        else:
            # Handle HTTP errors from the API
            return None, f"API Error: Status {r.status_code} - {r.text}"
    except Exception as e:
        # Handle connection errors or other exceptions during the request
        return None, f"Request Error: {e}"


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
        "show_content": False
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
    ##Should add this to config - currently hardcoded here for now
    ##Larger blocks (was 150 before) could be processes - but LLM starts to get lazy, and couldn't find a way to make it be careful.. seemingly "be fucking careful" doesn't help
    total = len(blocks)
    chunk_size = 80
    overlap = 0

    # --- TOPIC MAPPING ---
    print("\n--- Topic Mapping & Classification ---")
    all_topics = []
    
    pos = 0
    previous_context = None
    while pos < total:
        end_pos = min(pos + chunk_size, total)
        chunk = blocks[pos:end_pos]
        if not chunk:
            break
            
        print(f"Mapping topics in blocks {chunk[0]['idx']} to {chunk[-1]['idx']} ({end_pos}/{total})...", end=" ", flush=True)
        
        max_retries = 3
        found = None
        for attempt in range(max_retries):
            res, err = ask_phase1_topics(ollama_url, model_to_use, chunk, previous_context)
            if res is not None:
                found = res
                break
            else:
                print(f"\n  [Retry {attempt+1}/{max_retries} due to: {err}]", end=" ", flush=True)
                time.sleep(3)
                
        if found is not None:
            print(f"Identified {len(found)} topic segments.")
            all_topics.extend(found)
            if len(found) > 0:
                last_topic = found[-1]
                # Only pass context forward when it's at an interesting boundary.
                # If the chunk ended on plain show_content, passing that context forward
                # just primes the next chunk to also expect show_content, causing laziness.
                # Context is only valuable when an advert or special segment may spill over.
                if last_topic['category'] != 'show_content':
                    previous_context = f"The previous chunk ended with a topic titled '{last_topic['title']}' categorized as '{last_topic['category']}' which ended at block {last_topic['end_idx']}. Use this context to determine if the first few blocks of this current chunk continue that topic or start a new one."
                else:
                    previous_context = None
            else:
                previous_context = None
        else:
            print("Failed. Skipping this chunk.")
            previous_context = None
            
        if end_pos == total:
            break
        pos += (chunk_size - overlap)
        
    # Reconcile topics to avoid overlapping prints and prioritize flagged content
    block_topics = {}
    
    for t in all_topics:
        cat = t['category'].lower()
        is_flagged = content_to_remove.get(cat, False)
        
        for idx in range(t["start_idx"], t["end_idx"] + 1):
            if idx not in block_topics:
                block_topics[idx] = (t, is_flagged)
            else:
                _, old_flagged = block_topics[idx]
                if is_flagged and not old_flagged:
                    block_topics[idx] = (t, is_flagged)
                    
    # Rebuild contiguous, non-overlapping clean_topics
    clean_topics = []
    if block_topics:
        indices = sorted(list(block_topics.keys()))
        current_topic_ref, current_flagged = block_topics[indices[0]]
        current_start = indices[0]
        current_end = indices[0]
        
        for idx in indices[1:]:
            t_ref, is_flagged = block_topics[idx]
            if t_ref == current_topic_ref and idx == current_end + 1:
                current_end = idx
            else:
                clean_topics.append({
                    "start_idx": current_start,
                    "end_idx": current_end,
                    "category": current_topic_ref["category"],
                    "title": current_topic_ref["title"],
                    "is_flagged": current_flagged
                })
                current_topic_ref = t_ref
                current_flagged = is_flagged
                current_start = idx
                current_end = idx
                
        clean_topics.append({
            "start_idx": current_start,
            "end_idx": current_end,
            "category": current_topic_ref["category"],
            "title": current_topic_ref["title"],
            "is_flagged": current_flagged
        })

    print(f"Topic mapping complete. Total distinct segments after reconciling overlaps: {len(clean_topics)}")
    
    # --- PRINT TOPIC MAP TABLE ---
    print("\n--- GENERATED TOPIC MAP ---")
    print(f"{'Start':<6} | {'End':<6} | {'Duration':<8} | {'Category':<18} | {'Title'}")
    print("-" * 100)
    
    flagged_indices = set()
    
    for t in clean_topics:
        duration = t["end_idx"] - t["start_idx"] + 1
        is_flagged = t["is_flagged"]
        
        flagged_str = "[FLAGGED]" if is_flagged else "       "
        print(f"{t['start_idx']:<6} | {t['end_idx']:<6} | {duration:<8} | {t['category']:<18} | {t['title']} {flagged_str}")
        
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

    if blocks and len(blocks) > 0:
        total_podcast_time = blocks[-1]['end_time'] - blocks[0]['start_time']
        
        # Calculate time of ads by grouping contiguous final_ads blocks
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
            print(f"Percentage of podcast flagged for removal: {percentage:.1f}%")
        else:
            print("Percentage of podcast flagged for removal: 0.0%")
