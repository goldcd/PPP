import sys
import os
import requests
import xml.etree.ElementTree as ET
import datetime
import email.utils
import re
from app.RSS_Handler import get_feed_file, save_feed_file

def download():
    print("\nDownloading podcasts:\n")
    feeds = get_feed_file()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for feed in feeds:
        feed_title = feed.get("title", f"ID {feed.get('id')}")
        try:
            safe_name = feed.get("safe_name", str(feed["id"]))
            podcast_folder = f"data/{safe_name}"
            raw_folder = os.path.join(podcast_folder, "raw")
            os.makedirs(raw_folder, exist_ok=True)

            feed_success = True
            sync_start_time = datetime.datetime.now(datetime.timezone.utc)

            # Fetch RSS feed
            try:
                response = requests.get(feed['url'], headers=headers, timeout=30)
                response.raise_for_status()
            except Exception as e:
                print(f"Error fetching RSS feed for {feed_title} ({feed.get('url')}): {e}")
                continue

            rss_path = os.path.join(raw_folder, "rss.xml")
            try:
                with open(rss_path, "w", encoding="utf-8") as f:
                    f.write(response.text)
            except OSError as e:
                if os.path.exists(rss_path):
                    os.remove(rss_path)
                with open(rss_path, "w", encoding="utf-8") as f:
                    f.write(response.text)

            try:
                tree = ET.parse(rss_path)
                root = tree.getroot()
            except ET.ParseError as e:
                print(f"Failed to parse RSS feed for {feed_title}: {e}")
                continue

            syncfrom_date = datetime.datetime.fromisoformat(feed['syncFrom'])
            if syncfrom_date.tzinfo is None:
                syncfrom_date = syncfrom_date.astimezone(datetime.timezone.utc)
            else:
                syncfrom_date = syncfrom_date.astimezone(datetime.timezone.utc)

            items = root.findall("channel/item")
            for item in items:
                pubdate_elem = item.find("pubDate")
                if pubdate_elem is None or not pubdate_elem.text:
                    continue

                try:
                    pubdate = email.utils.parsedate_to_datetime(pubdate_elem.text)
                    if pubdate.tzinfo is None:
                        pubdate = pubdate.replace(tzinfo=datetime.timezone.utc)
                    else:
                        pubdate = pubdate.astimezone(datetime.timezone.utc)
                except Exception as e:
                    print(f"Could not parse pubDate '{pubdate_elem.text}': {e}")
                    continue

                if pubdate > syncfrom_date:
                    title_elem = item.find('title')
                    episode_title = title_elem.text if (title_elem is not None and title_elem.text) else "Untitled Episode"
                    
                    guid_elem = item.find("guid")
                    guid = guid_elem.text if (guid_elem is not None and guid_elem.text) else None
                    if not guid:
                        enclosure_elem = item.find("enclosure")
                        guid = enclosure_elem.get("url") if enclosure_elem is not None else episode_title

                    safe_guid = re.sub(r'[\\/*?:"<>|]', '_', guid)
                    mp3_path = os.path.join(raw_folder, f"{safe_guid}.mp3")

                    # Check if valid file already exists
                    if os.path.exists(mp3_path):
                        if os.path.getsize(mp3_path) >= 10240:
                            print(f"Skipping download, file already exists: {safe_guid}.mp3")
                            continue
                        else:
                            print(f"Existing file is corrupt/truncated ({os.path.getsize(mp3_path)} bytes), will re-download: {safe_guid}.mp3")
                            try:
                                os.remove(mp3_path)
                            except OSError:
                                pass

                    enclosure = item.find("enclosure")
                    if enclosure is None or not enclosure.get("url"):
                        print(f"Skipping '{episode_title}': No enclosure audio URL found.")
                        feed_success = False
                        continue

                    media_url = enclosure.get("url")
                    print(f"{feed_title}: {episode_title}")
                    temp_path = f"{mp3_path}.part"

                    try:
                        with requests.get(media_url, headers=headers, stream=True, timeout=120) as download_response:
                            download_response.raise_for_status()
                            with open(temp_path, "wb") as f:
                                for chunk in download_response.iter_content(chunk_size=1024 * 64):
                                    if chunk:
                                        f.write(chunk)

                        file_size = os.path.getsize(temp_path)
                        if file_size < 10240:
                            with open(temp_path, "rb") as f:
                                preview = f.read(200)
                            raise ValueError(f"Downloaded content too small ({file_size} bytes). Preview: {preview}")

                        with open(temp_path, "rb") as f:
                            header = f.read(64)
                        if header.startswith(b"<!DOCT") or header.startswith(b"<html") or b"EPISODE_NOT_FOUND" in header:
                            raise ValueError(f"Downloaded content appears to be text/error page, not audio: {header[:40]}")

                        # Validation passed, move temp file to target path
                        if os.path.exists(mp3_path):
                            os.remove(mp3_path)
                        os.replace(temp_path, mp3_path)
                        print(f"Successfully downloaded: {safe_guid}.mp3 ({file_size / (1024*1024):.1f} MB)")

                    except Exception as e:
                        print(f"Failed to download '{episode_title}' ({safe_guid}.mp3): {e}")
                        feed_success = False
                        if os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except OSError:
                                pass
                        continue

            # Only update syncFrom if all episodes since syncfrom_date were successfully downloaded
            if feed_success:
                feed['syncFrom'] = sync_start_time.isoformat()
                save_feed_file(feeds)
                print(f"Sync complete for {feed_title}. syncFrom updated to {feed['syncFrom']}\n")
            else:
                print(f"WARNING: One or more episodes failed for {feed_title}. syncFrom date NOT updated, will retry on next run.\n")

        except Exception as e:
            print(f"Unexpected error processing feed {feed_title}: {e}\n")
            continue        

                
        
        
        

        