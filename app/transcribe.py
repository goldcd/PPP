import os
import sys
import time

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml

##Slopped function to convert time to convert seconts to the format I want to put into my SRT files: HH:MM:SS,mmm
def format_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    # Handle rounding overflow (e.g. 1000ms -> 1s)
    if milliseconds >= 1000:
        secs += 1
        milliseconds -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"    


def transcribe_all():
    print("\nTranscribing!\n")

    # If the data path doesn't exist, then tell the user they need to add some podcasts
    if not os.path.exists("data"):
        print("No data folder found. Add some podcasts and try again")
        return
    
    ##Go on an adventure in the data folder and detect all of the podcasts that haven't had a paired .srt generated for them   
    for podcast_folder in os.listdir("data"):
        podcast_path = os.path.join("data", podcast_folder)
        if os.path.isdir(podcast_path):
            ##Now, within each podcast folder, we're looking for a raw folder with the rss.xml file in it
            raw_folder = os.path.join(podcast_path, "raw")
            if os.path.exists(raw_folder):
                ##Now within the raw folder, we're looking for .mp3 files
                for mp3_file in os.listdir(raw_folder):
                    if mp3_file.endswith(".mp3"):
                        ##Now we need to check if the .mp3 file has already been transcribed
                        ##If so, we skip it
                        transcribed_file = os.path.join(raw_folder, mp3_file.replace(".mp3", ".srt"))
                        if os.path.exists(transcribed_file):
                            continue
                        else:
                            ##Now we've found a file, trigger the transcribe for it
                            transcribe(mp3_file, raw_folder)

#I'm very proud of myself. I've actually separated out the logic here from the front end. Well done me!
def transcribe(mp3_file, raw_folder):
    #Didn't like it when I imported these with the package
    import torch
    from faster_whisper import WhisperModel
    
    print(f"Now transcribing {mp3_file} in {raw_folder}")

    ##See if the user has a GPU installed and use this to determine what device whisper will use.

    ##If you're team nvidia
    if torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16"
        print("\n Using GPU to transcribe \n")
    ##a degenerate Apple fanboi (faster-whisper/ctranslate2 doesn't support MPS GPU yet, but CPU is extremely fast on Apple Silicon)
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "cpu"
        compute_type = "int8"
        print("\n Using CPU - but I think you're on Apple, so it should be OK \n")
    ##poor. Although I think you might be screwed when we later try to locally work out where the adverts are...
    else:
        device = "cpu"
        compute_type = "int8"
        print("\n Using CPU to transcribe - this will be brutally slow \n")

    ##Call Whisper to do the transcribing
    #Load the whisper model - exact model to use is specified in the config.toml file   
    with open("config.toml", "rb") as f:
        config = toml.load(f)
    model_to_use = config["transcribe"]["model_to_use"]
    force_cpu = config.get("processing", {}).get("force_cpu", False)
    if force_cpu and device == "cuda":
        device = "cpu"
        compute_type = "int8"
        print("\n force_cpu=true in config.toml — overriding GPU, using CPU instead \n")
    #Updated to both allow the model to be selected and where you want it to be run
    model = WhisperModel(model_to_use, device=device, compute_type=compute_type)
    
    ##Transcribe the podcast!!
    
    start_time = time.time()
    # beam_size=5 matches standard Whisper default accuracy.
    segments, info = model.transcribe(os.path.join(raw_folder, mp3_file), beam_size=5)
    
    srt_path = os.path.join(raw_folder, mp3_file.replace(".mp3", ".srt"))
    #AI to the rescue - although think I could have done that myself.. well googled it..
    srt_blocks = []
    for i, segment in enumerate(segments, start=1):
        start = format_srt_time(segment.start)
        end = format_srt_time(segment.end)
        text = segment.text.strip()
        
        srt_blocks.append(f"{i}\n{start} --> {end}\n{text}\n\n")
        
    with open(srt_path, "w", encoding="utf-8") as f:
        f.writelines(srt_blocks)
            
    elapsed_time = time.time() - start_time
    print(f"Finished transcribing {mp3_file} in {elapsed_time:.1f} seconds")
    

    
    
    
    