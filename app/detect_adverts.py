import os
import sys
import time
import torch
import requests

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
    if torch.cuda.is_available():
        ollama_model = ollama_config.get("gpu_model", "gemma4:12b")
        print(f"\n Using GPU model '{ollama_model}' for advert detection \n")
    else:
        ollama_model = ollama_config.get("cpu_model", "gemma4:e2b")
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


def detect_adverts(srt_file, raw_folder):
    print(f"Detecting adverts for {srt_file}")