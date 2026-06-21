import os
import sys
import whisper
import torch

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml


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
    ##This function will handle the transcribing of a single podcast file
    print(f"Now transcribing {mp3_file} in {raw_folder}")

    ##See if the user has a GPU installed and use this to determine what device whisper will use.

    #If you're team nvidia
    if torch.cuda.is_available():
        device = "cuda"
    ##a degenerate Apple fanboi
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"  
    ##poor. Although I think you might be screwed when we later try to locally work out where the adverts are...
    else:
        device = "cpu"

    ##Call Whisper to do the transcribing
    #Load the whisper model - exact model to use is specified in the config.toml file   
    config = toml.loads(open("config.toml").read())
    model_to_use = config["transcribe"]["model_to_use"]
    #Updated to both allow the model to be selected and where you want it to be run
    model = whisper.load_model(model_to_use, device)
    ##Transcribe the podcast
    result = model.transcribe(os.path.join(raw_folder, mp3_file))
    ##Save the transcript
    with open(os.path.join(raw_folder, mp3_file.replace(".mp3", ".srt")), "w") as f:
        f.write(result["text"])
    print(f"Finished transcribing {mp3_file}")

    

    
    
    
    