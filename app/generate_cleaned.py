import os
import subprocess
import tempfile
import shutil
try:
    import tomllib as toml
except ModuleNotFoundError:
    import tomli as toml

from app.detect_adverts import parse_srt_blocks

##This module is for generating the actual output of this app
##To use this module in the raw folder, we should have the original podcast file, and a .ad (an SRT describing the sections of the advert we want to remove)

## Helper function I stole, to convert SRT timestamps to seconds
def convert_time_to_seconds(time_str):
    """
    Convert SRT time format (HH:MM:SS,MS --> HH:MM:SS,MS)
    to total seconds (float).
    """
    try:
        parts = time_str.split(" --> ")
        start_str = parts[0].strip()
        
        h, m, s_ms = start_str.split(':')
        s, ms = s_ms.split(',')
        
        total_seconds = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
        return total_seconds
    except Exception as e:
        print(f"Error converting timestamp {time_str}: {e}")
        return None 


def generate_all_cleaned():
    print("Generating cleaned podcasts")

    ##If the data path doesn't exist, then tell the user they need to add some podcasts
    if not os.path.exists("data"):
        print("No data folder found. Add some podcasts and try again")
        return

    ##Now we need to determine which podcasts we have to process.
    ## First of all, loop through all the podcast folders in the data directory
    ## Then we look for a .mp3 and .ad file pair, where an .mp3 with the same name doesn't exist in the output folder
    ## Add the path and filename into a list as a tuple
    ## Once we have this list, we should print out the number of podcasts we found
    ## And then we should loop through this list and process each one
    ## Phew
    ##Right, now for the logic
    
    ##Output list
    podcast_process_list = []
    ##Loop folders in my data directory
    for folder in os.listdir("data"):
        folder_path = os.path.join("data", folder)
        ##set the raw and output folder paths
        if os.path.isdir(folder_path):
            raw_folder = os.path.join(folder_path, "raw")
            
            output_folder = os.path.join(folder_path, "output")
                
            os.makedirs(output_folder, exist_ok=True)
            
            ##Then if we have an mp3 and ad pair (i.e. we've transcribed and then ad-detected the podcast)
            for filename in os.listdir(raw_folder):
                if filename.endswith(".mp3"):
                    base_name = os.path.splitext(filename)[0]
                    ad_filename = f"{base_name}.ad"
                    if os.path.exists(os.path.join(raw_folder, ad_filename)):
              
                       ##BUT we haven't created an output file yet. check it's not already there.abs
                        if not os.path.exists(os.path.join(output_folder, filename)):
                            #Then we have a file to process
                            podcast_process_list.append((folder_path, output_folder, filename))

    print(f"Found {len(podcast_process_list)} podcasts to process")

    for folder_path, output_folder, filename in podcast_process_list:
        generate_cleaned(folder_path, output_folder, filename)

    ## Now the final-final step is to tidy up this cloned RSS feed in the output folder
    ## Firstly update all the mp3 paths to just be in the same relative path as the RSS file (which means we can move this around)
    ## Truncate the RSS feed, to remove any shows, where the MP3 isn't in this folder_path
    ## Vibey Vibey :)
    import xml.etree.ElementTree as ET
    import re
    
    # Register standard podcast namespaces so ElementTree doesn't mangle them
    ET.register_namespace('itunes', 'http://www.itunes.com/dtds/podcast-1.0.dtd')
    ET.register_namespace('googleplay', 'http://www.google.com/schemas/play-podcasts/1.0')
    ET.register_namespace('atom', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('media', 'http://search.yahoo.com/mrss/')
    ET.register_namespace('content', 'http://purl.org/rss/1.0/modules/content/')

    # We should process ALL active podcasts, not just ones we just generated, in case we need to rebuild the RSS
    ## Another bit I threw at AI. Cleaning up the RSS so it didn't get conflated with the original feed was a bastard
    ## 
    for folder in os.listdir("data"):
        folder_path = os.path.join("data", folder)
        if os.path.isdir(folder_path):
            raw_folder = os.path.join(folder_path, "raw")
            output_folder = os.path.join(folder_path, "output")
                
            rss_path = os.path.join(raw_folder, "rss.xml")
            output_rss_path = os.path.join(output_folder, "rss.xml")
            
            # Always make sure the latest RSS is copied before tidying
            if os.path.exists(rss_path) and os.path.exists(output_folder):
                shutil.copy2(rss_path, output_rss_path)

            if os.path.exists(output_rss_path):
                try:
                    tree = ET.parse(output_rss_path)
                    root = tree.getroot()
                    channel = root.find('channel')
                    
                    if channel is not None:
                        # Remove atom:link rel="self" to prevent podcast apps from redirecting to the original feed
                        atom_namespace = "http://www.w3.org/2005/Atom"
                        for link in channel.findall(f'{{{atom_namespace}}}link'):
                            if link.get('rel') == 'self':
                                channel.remove(link)
                                
                        ## Adding a prefix of PPP to all of our channels that we create, so they can be differentiated from the original
                        ## Should probably make more changes in the future (e.g. the image) - a nice black/white version or something? PPP overlay?
                        channel_title = channel.find('title')
                        if channel_title is not None and channel_title.text:
                            if not channel_title.text.startswith("PPP: "):
                                channel_title.text = f"PPP: {channel_title.text}"
                                
                        ## Change channel link to avoid matching original feed
                        ## Again - might need to add more of this later. Every app will I'm sure have different rules.. 
                        ## and makes sense they don't want impersonators to on-board and swap the adverts.. actually maybe in PPP v2? 
                        channel_link = channel.find('link')
                        if channel_link is not None:
                            channel_link.text = "http://localhost/ppp"
                            
                        # Scrub author
                        itunes_namespace = "http://www.itunes.com/dtds/podcast-1.0.dtd"
                        author_elem = channel.find(f'{{{itunes_namespace}}}author')
                        if author_elem is not None and author_elem.text:
                            author_elem.text = f"PPP: {author_elem.text}"
                            
                        # Scrub image metadata
                        image_elem = channel.find('image')
                        if image_elem is not None:
                            img_link = image_elem.find('link')
                            if img_link is not None:
                                img_link.text = "http://localhost/ppp"
                            img_title = image_elem.find('title')
                            if img_title is not None and img_title.text:
                                if not img_title.text.startswith("PPP: "):
                                    img_title.text = f"PPP: {img_title.text}"
                                
                        items_to_remove = []
                        for item in channel.findall('item'):
                            enclosure = item.find('enclosure')
                            if enclosure is not None:
                                guid_elem = item.find('guid')
                                if guid_elem is not None and guid_elem.text:
                                    safe_guid = re.sub(r'[\\/*?:"<>|]', '_', guid_elem.text)
                                    mp3_filename = f"{safe_guid}.mp3"
                                else:
                                    url = enclosure.get('url', '')
                                    base_url = url.split('?')[0]
                                    mp3_filename = os.path.basename(base_url)
                                
                                # Check if this MP3 exists in the output folder
                                if os.path.exists(os.path.join(output_folder, mp3_filename)):
                                    # Update the URL to be a relative local path
                                    enclosure.set('url', mp3_filename)
                                    
                                    # Prefix the title to avoid confusion
                                    title_elem = item.find('title')
                                    if title_elem is not None and title_elem.text:
                                        if not title_elem.text.startswith("PPP: "):
                                            title_elem.text = f"PPP: {title_elem.text}"
                                            
                                    # Alter the GUID so podcast apps treat it as a new distinct episode
                                    if guid_elem is not None and guid_elem.text:
                                        if not guid_elem.text.endswith("_ppp"):
                                            guid_elem.text = f"{guid_elem.text}_ppp"
                                else:
                                    items_to_remove.append(item)
                            else:
                                items_to_remove.append(item)
                                
                        for item in items_to_remove:
                            channel.remove(item)
                            
                    ##and we're done
                    tree.write(output_rss_path, encoding='utf-8', xml_declaration=True)
                    print(f"Tidied up RSS feed: {output_rss_path}")
                except Exception as e:
                    print(f"Error processing RSS feed {output_rss_path}: {e}")

    ##Final-final-final
    ##I'd just like to create a 


def get_original_title(mp3_path):
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format_tags=title",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp3_path
        ]
        result = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
        return result
    except Exception as e:
        print(f"Failed to extract title: {e}")
        return ""

## Generate the cleaned podcast - using the paired ad file as a guide to remove segments from the original file

def generate_cleaned(podcast_path, output_folder, filename):

    print(f"Processing: {filename}")

    ##First we just need to generate the paths to out input mp3, input .ad, and where we're going to be writing the output mp3 to
    raw_folder = os.path.join(podcast_path, "raw")
    
    input_mp3 = os.path.join(raw_folder, filename)
    base_name = os.path.splitext(filename)[0]
    input_ad = os.path.join(raw_folder, f"{base_name}.ad")
    output_mp3 = os.path.join(output_folder, filename)
    
    os.makedirs(output_folder, exist_ok=True)
    
    original_title = get_original_title(input_mp3)

    ## Now parse the ad file (it's just an SRT, and we have a helper function in the detect_adverts module)
    with open(input_ad, "r", encoding="utf-8") as f:
        raw_ad_content = f.read()

    raw_blocks_list = raw_ad_content.replace("\r\n", "\n").strip().split("\n\n")
    if not raw_blocks_list or not raw_blocks_list[0]:
        print("No ads to remove.")
        return

    blocks = parse_srt_blocks(raw_blocks_list)

    ## What we want to get from this is just the start/end times of the ad segments we want to remove
    ## Possibly there was a nicer way of doing this, but we just need to work through the file.
    ## start point of first block is where we're going to make out first cut. Then when we find the next block isn't contiguous, we cut at the end point of this block. Then if there's another block,
    ## the start of that is the next cut point. And so on and so forth.
    ## What we want to do, is generate a list of pairs of timestamps we're going to cut.
    cut_segments = []
    if blocks:
        current_start_time = None
        current_end_time = None
        last_idx = None
        
        for b in blocks:
            lines = b['raw'].split("\n")
            if len(lines) >= 2:
                timestamps = lines[1].split(" --> ")
                if len(timestamps) == 2:
                    start_time = timestamps[0].strip()
                    end_time = timestamps[1].strip()
                    
                    if last_idx is None:
                        current_start_time = start_time
                        current_end_time = end_time
                        last_idx = b['idx']
                    elif b['idx'] == last_idx + 1:
                        current_end_time = end_time
                        last_idx = b['idx']
                    else:
                        cut_segments.append((current_start_time, current_end_time))
                        current_start_time = start_time
                        current_end_time = end_time
                        last_idx = b['idx']
                        
        if current_start_time and current_end_time:
            cut_segments.append((current_start_time, current_end_time))

    ## Initially, let's just print this on the screen for debugging 
    print(f"Segments to cut: {cut_segments}")

    ##Now let's get out the scissors... i.e. cut the mp3 up into segments, skipping out the ad segments.
    if not cut_segments:
        print("No ads to remove. Copying original file to output.")
        shutil.copy2(input_mp3, output_mp3)
        return

    # Convert cut string segments to seconds
    cut_seconds = []
    for start_str, end_str in cut_segments:
        s = convert_time_to_seconds(start_str)
        e = convert_time_to_seconds(end_str)
        if s is not None and e is not None:
            cut_seconds.append((s, e))

    # Sort just in case they aren't sequential
    cut_seconds.sort(key=lambda x: x[0])

    # Check config for pop insertion
    insert_pop = True
    if os.path.exists("config.toml"):
        try:
            with open("config.toml", "rb") as f:
                config_data = toml.load(f)
                insert_pop = config_data.get("processing", {}).get("insert_edit_pop", True)
        except Exception as e:
            print(f"Failed to read config.toml: {e}")

    # Build the playlist of kept segments and pops
    playlist = []
    current_time = 0.0

    for start_sec, end_sec in cut_seconds:
        if start_sec > current_time:
            # Add kept segment
            playlist.append(('keep', current_time, start_sec))
            # Since we are about to cut an ad, insert a pop (if enabled)
            if insert_pop:
                playlist.append(('pop', None, None))
        else:
            # Overlapping cut. If it's the very first cut at 0.0, we still want a pop.
            if len(playlist) == 0 and insert_pop:
                playlist.append(('pop', None, None))
                
        current_time = max(current_time, end_sec)

    # We also need the segment from the last cut to the end of the file.
    playlist.append(('keep', current_time, None))

    print(f"Constructed playlist: {playlist}")

    # Now use ffmpeg to extract these segments and concatenate them
    with tempfile.TemporaryDirectory() as temp_dir:
        concat_file_path = os.path.join(temp_dir, "concat.txt")
        temp_files = []
        pop_file_path = None

        if insert_pop and any(item[0] == 'pop' for item in playlist):
            # Probe input for exact sample rate and channels
            sample_rate = "44100"
            channels = "2"
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", input_mp3]
                probe_res = subprocess.check_output(probe_cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
                if "," in probe_res:
                    sr_parsed, ch_parsed = probe_res.split(",")
                    if sr_parsed.isdigit(): sample_rate = sr_parsed
                    if ch_parsed.isdigit(): channels = ch_parsed
            except Exception as e:
                print(f"Failed to probe input_mp3: {e}")

            pop_file_path = os.path.join(temp_dir, "pop.mp3")
            pop_cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "aevalsrc=exprs=sin(400*2*PI*t)*exp(-30*t):d=0.15",
                "-c:a", "libmp3lame", "-ar", sample_rate, "-ac", channels, pop_file_path
            ]
            try:
                subprocess.run(pop_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"Failed to generate pop sound: {e}")
                pop_file_path = None

        with open(concat_file_path, "w", encoding="utf-8") as f:
            for i, (p_type, start_sec, end_sec) in enumerate(playlist):
                if p_type == 'keep':
                    temp_mp3 = os.path.join(temp_dir, f"part_{i}.mp3")
                    cmd = ["ffmpeg", "-y", "-i", input_mp3, "-ss", str(start_sec)]
                    if end_sec is not None:
                        cmd.extend(["-to", str(end_sec)])
                    # Fast copy without re-encoding
                    cmd.extend(["-c", "copy", temp_mp3])

                    print(f"Extracting part {i}: {start_sec} to {end_sec if end_sec else 'EOF'}...")
                    try:
                        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        temp_files.append(temp_mp3)
                        escaped_path = temp_mp3.replace('\\', '/')
                        f.write(f"file '{escaped_path}'\n")
                    except subprocess.CalledProcessError as e:
                        print(f"Error extracting part {i}: {e}")
                elif p_type == 'pop' and pop_file_path:
                    escaped_pop = pop_file_path.replace('\\', '/')
                    f.write(f"file '{escaped_pop}'\n")

        # Now concatenate the extracted parts
        if temp_files:
            print("Concatenating parts to generate final podcast...")
            concat_cmd = [
                "ffmpeg", "-y", 
                "-f", "concat", "-safe", "0", "-i", concat_file_path,
                "-i", input_mp3,
                "-map", "0:a",
                "-map", "1:v?",
                "-map_metadata", "1",
                "-id3v2_version", "3",
            ]
            
            if original_title:
                concat_cmd.extend(["-metadata", f"title=PPP: {original_title}"])
            else:
                concat_cmd.extend(["-metadata", "title=PPP: Cleaned Podcast"])
                
            concat_cmd.extend([
                "-c", "copy", 
                output_mp3
            ])
            try:
                subprocess.run(concat_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"Successfully generated cleaned podcast: {output_mp3}")
            except subprocess.CalledProcessError as e:
                print(f"Error concatenating parts: {e}")





