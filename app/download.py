import sys
import os
import requests
import xml.etree.ElementTree as ET
import datetime
from app.RSS_Handler import get_feed_file, save_feed_file

def download():
    print("\nDownloading podcasts:\n")
    ##Loop through all of the podcasts in the feeds file:
    feeds = get_feed_file()
    for feed in feeds:
        ##If it doesn't exist, create a subfolder called "raw" within our podcasts folder. We'll use this to store what we download
        safe_name = feed.get("safe_name", str(feed["id"]))
        podcast_folder = f"data/{safe_name}"
        raw_folder = os.path.join(podcast_folder, "raw")
        os.makedirs(raw_folder, exist_ok=True)

        ##Now grab the raw feed XML, and save it as rss.xml in the podcast_folder, overwriting if it exists
        response = requests.get(feed['url'])
        with open(os.path.join(raw_folder, "rss.xml"), "w", encoding="utf-8") as f:
            f.write(response.text)

        ##Parse the XML with our XML parser of choice
        try:
            tree = ET.parse(os.path.join(raw_folder, "rss.xml"))
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"Failed to parse RSS feed for {feed['title']}: {e}")
            return

        ##Work out how far back in this feed we should be looking, based upon the syncfrom date in the feeds file
        ##I really should add an option to let the user override this when they on-board. Maybe config just becomes a pre-populated default
        syncfrom_date = datetime.datetime.fromisoformat(feed['syncFrom'])

        import email.utils
        ## Iterate through the rss.xml entries and process any that are newer than our syncfrom date
        for item in root.findall("channel/item"):
            pubdate = item.find("pubDate").text
            
            # Parse the pubDate, and strip timezone info to make it easy for comparison
            pubdate = email.utils.parsedate_to_datetime(pubdate).replace(tzinfo=None)
            
            if pubdate > syncfrom_date:

                print(f"{feed['title']}: {item.find('title').text}")
                ##Take the guid from the rss entry (unique ID)
                guid = item.find("guid").text
                import re
                safe_guid = re.sub(r'[\\/*?:"<>|]', '_', guid)
                ##Get the media url
                media_url = item.find("enclosure").get("url")
                ##Download the file, and save it with the guid as the filename
                download_response = requests.get(media_url)
                with open(os.path.join(raw_folder, f"{safe_guid}.mp3"), "wb") as f:
                    f.write(download_response.content)

        ##New we've grabbed any new podcasts, we should update the syncfrom date to be the current date
        feed['syncFrom'] = datetime.datetime.now().isoformat()
        save_feed_file(feeds)        

                
        
        
        

        