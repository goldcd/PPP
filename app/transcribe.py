import os
import sys
import time
import warnings
# Suppress harmless warnings from pyannote and lightning to keep the console clean
warnings.filterwarnings("ignore", category=UserWarning, message="(?s).*torchcodec is not installed correctly.*")
warnings.filterwarnings("ignore", category=UserWarning, message="(?s).*upgraded your loaded checkpoint.*")
warnings.filterwarnings("ignore", category=UserWarning, message="(?s).*TensorFloat-32.*")
warnings.filterwarnings("ignore", category=UserWarning, message="(?s).*degrees of freedom is <= 0.*")

import logging
logging.getLogger("lightning.pytorch.utilities.migration.utils").setLevel(logging.ERROR)
logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)

# Configure PyTorch globally before any models are loaded
try:
    import torch
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
except ImportError:
    pass

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

def calculate_dbfs(audio_array, start_time, end_time, sample_rate=16000):
    import numpy as np
    start_sample = int(start_time * sample_rate)
    end_sample = int(end_time * sample_rate)
    segment_audio = audio_array[start_sample:end_sample]
    
    if len(segment_audio) == 0:
        return -100.0
        
    rms = np.sqrt(np.mean(segment_audio**2))
    if rms == 0:
        return -100.0
        
    return 20 * np.log10(rms)

def transcribe_all():
    print("\nTranscribing!\n")

    # If the data path doesn't exist, then tell the user they need to add some podcasts
    if not os.path.exists("data"):
        print("No data folder found. Add some podcasts and try again")
        return
    
    ## Gather all files that need transcribing
    files_to_transcribe = []
    for podcast_folder in os.listdir("data"):
        podcast_path = os.path.join("data", podcast_folder)
        if os.path.isdir(podcast_path):
            raw_folder = os.path.join(podcast_path, "raw")
            if os.path.exists(raw_folder):
                for mp3_file in os.listdir(raw_folder):
                    if mp3_file.endswith(".mp3"):
                        transcribed_file = os.path.join(raw_folder, mp3_file.replace(".mp3", ".srt"))
                        if not os.path.exists(transcribed_file):
                            files_to_transcribe.append((mp3_file, raw_folder))

    if not files_to_transcribe:
        return

    import torch
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    # Load configuration
    with open("config.toml", "rb") as f:
        config = toml.load(f)
        
    device = "cuda" if torch.cuda.is_available() else ("cpu" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu")
    compute_type = "float16" if device == "cuda" else "int8"
    
    force_cpu = config.get("processing", {}).get("force_cpu", False)
    if force_cpu and device == "cuda":
        device = "cpu"
        compute_type = "int8"
        print("\n force_cpu=true in config.toml — overriding GPU, using CPU instead \n")
        
    hf_token = config.get("huggingface", {}).get("hf_token", "")
    if not hf_token:
        print("\n ERROR: No hf_token provided in config.toml! Cannot run Pyannote diarization. \n")
        return
        
    model_to_use = config["transcribe"]["model_to_use"]
    
    print(f"Loading WhisperX {model_to_use} model into {device} memory once for batch processing...")
    model = whisperx.load_model(model_to_use, device, compute_type=compute_type)
    
    print("Loading Diarization Pipeline into memory...")
    try:
        diarize_model = DiarizationPipeline(token=hf_token, device=device)
    except Exception as e:
        print(f"\n Error authenticating with Hugging Face: {e}\n")
        return

    # Process all files
    for mp3_file, raw_folder in files_to_transcribe:
        transcribe(mp3_file, raw_folder, model=model, diarize_model=diarize_model, device=device)
        
    # Unload models after batch
    print("Batch complete. Unloading transcription models from GPU memory...")
    import gc
    del model
    del diarize_model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

#I'm very proud of myself. I've actually separated out the logic here from the front end. Well done me!
def transcribe(mp3_file, raw_folder, model=None, diarize_model=None, device=None):
    #Didn't like it when I imported these with the package
    import torch
    import whisperx
    from whisperx.diarize import DiarizationPipeline
    
    print(f"\nNow transcribing {mp3_file} in {raw_folder}")

    is_local_model = False
    if model is None or diarize_model is None or device is None:
        is_local_model = True
        if torch.cuda.is_available():
            device = "cuda"
            compute_type = "float16"
            print("\n Using GPU to transcribe \n")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "cpu"
            compute_type = "int8"
            print("\n Using CPU - but I think you're on Apple, so it should be OK \n")
        else:
            device = "cpu"
            compute_type = "int8"
            print("\n Using CPU to transcribe - this will be brutally slow \n")

        with open("config.toml", "rb") as f:
            config = toml.load(f)
        model_to_use = config["transcribe"]["model_to_use"]
        force_cpu = config.get("processing", {}).get("force_cpu", False)
        if force_cpu and device == "cuda":
            device = "cpu"
            compute_type = "int8"
            print("\n force_cpu=true in config.toml — overriding GPU, using CPU instead \n")
            
        hf_token = config.get("huggingface", {}).get("hf_token", "")
        if not hf_token:
            print("\n ERROR: No hf_token provided in config.toml! Cannot run Pyannote diarization. \n")
            return
            
        model = whisperx.load_model(model_to_use, device, compute_type=compute_type)
        try:
            diarize_model = DiarizationPipeline(token=hf_token, device=device)
        except Exception as e:
            print(f"\n Error authenticating with Hugging Face: {e}\n")
            return
    
    ##Transcribe the podcast!!
    
    start_time = time.time()
    
    mp3_path = os.path.join(raw_folder, mp3_file)
    print("Loading audio into memory...")
    audio = whisperx.load_audio(mp3_path)
    
    print("Transcribing (this may take a few minutes)...")
    # beam_size=5 isn't standard in whisperx load_model, we just use the default transcribe
    result = model.transcribe(audio, batch_size=16)
    
    print("Aligning audio...")
    model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
    result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
    
    # Clean up the alignment model immediately, it's specific to the language of this file
    import gc
    del model_a
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    print("Diarizing speakers...")
    diarize_segments = diarize_model(audio)
    
    print("Assigning speakers to text blocks...")
    result = whisperx.assign_word_speakers(diarize_segments, result)
    
    srt_path = os.path.join(raw_folder, mp3_file.replace(".mp3", ".srt"))
    #AI to the rescue - although think I could have done that myself.. well googled it..
    srt_blocks = []
    block_index = 1
    last_end_time = 0.0
    
    for segment in result["segments"]:
        start_time = segment["start"]
        end_time = segment["end"]
        
        # Check for gap (music/noise detection)
        gap_duration = start_time - last_end_time
        if gap_duration > 1.5 and last_end_time > 0:
            gap_dbfs = calculate_dbfs(audio, last_end_time, start_time)
            if gap_dbfs > -45.0:  # Ignore total silence
                start_str = format_srt_time(last_end_time)
                end_str = format_srt_time(start_time)
                srt_blocks.append(f"{block_index}\n{start_str} --> {end_str}\n[MUSIC/NOISE | Vol: {gap_dbfs:.1f}dB] (No speech detected)\n\n")
                block_index += 1
                
        # Main text segment
        seg_dbfs = calculate_dbfs(audio, start_time, end_time)
        start_str = format_srt_time(start_time)
        end_str = format_srt_time(end_time)
        text = segment["text"].strip()
        speaker = segment.get("speaker", "UNKNOWN")
        
        srt_blocks.append(f"{block_index}\n{start_str} --> {end_str}\n[{speaker} | Vol: {seg_dbfs:.1f}dB] {text}\n\n")
        block_index += 1
        last_end_time = end_time
    with open(srt_path, "w", encoding="utf-8") as f:
        f.writelines(srt_blocks)
            
    elapsed_time = time.time() - start_time
    print(f"Finished transcribing {mp3_file} in {elapsed_time:.1f} seconds")
    
    if is_local_model:
        # Explicitly unload models from memory to free up VRAM for Ollama if we loaded them locally
        print("Unloading local transcription models from GPU memory...")
        del model
        del diarize_model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()    
    
    
    