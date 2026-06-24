import sys
import os
import requests
import json
import xml.etree.ElementTree as ET
import datetime
import shutil
import re

##Seemingly necessary for python 3.10 (where tomllib doesn't exist)
if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml

##Using onboarding index to store podcast in filesystem (e.g. /data/raw/1/) caused a problem.
## IF you add/removed a podcast, it might end up with a different integer, and then ultimately causes to path to the output RSS file to change - this is bad
## function generates a 'safe' string path for the podcast we can rely on
def generate_safe_path(title):
    ## Convert to lowercase
    safe_title = title.lower()
    ## Replace any non-alphanumeric character with a hyphen
    safe_title = re.sub(r'[^a-z0-9]+', '-', safe_title)
    ## Strip leading and trailing hyphens
    safe_title = safe_title.strip('-')
    ## Now send back a lovely name
    return safe_title

def add_RSS():
    
    ##Initialize our storage file for our RSS feeds
    initialize_feed_file()

    #Prompt the user to input an RSS feed URL
    rss_url = input("Enter the URL of the feed you want to add:")

    ##Now try to grab this XML
    response = requests.get(rss_url)

    ##Check we got a 200 (i.e. we could actually grab from the provided URL)
    if response.status_code != 200:
        print("Failed to fetch the feed. Status code:", response.status_code)
        return

    ##Put it into an XML tree and catch it if it fucks up
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print("Failed to parse the response as XML", e)
        return

    ##Now let's try to get the title out of this tree
    title = root.find("channel").find("title").text
    if not title:
        print("Couldn't find a title for this podcast. It might be XML, but it's probably not a podcast.")
        return

    ##Finally Let's try to write something to our feeds file.
    ##First open it
    feeds = get_feed_file()

  
    ##I'm going to need to iterate through the values to check if it's there, as the key is now the ID
    for feed in feeds:
        if feed["title"] == title:
            print(f"{title} is already in the feeds file.")
            return
    
   
    ##Get any existing IDs, then iterate through them until you find a space (i.e. we'll fill any gaps we create by deleting)
    used_ids = {feed["id"] for feed in feeds}
    nextID = 1
    while nextID in used_ids:
        nextID += 1
    
    ##Generate a safe string path for the podcast directory based on the title
    base_safe_name = generate_safe_path(title)
    safe_name = base_safe_name
    used_safe_names = {feed.get("safe_name") for feed in feeds}
    counter = 1
    while safe_name in used_safe_names:
        safe_name = f"{base_safe_name}-{counter}"
        counter += 1
    
    ##Create a child folder in the data folder for this podcast, using the safe_name as the name
    os.makedirs(f"data/{safe_name}", exist_ok=True)
    

    ##For now just set the current date-stamp as syncfrom, less the lookback from the config file
    ##I'm not sure TOML is the smooth config file to use - but I asked AI for best practice, and here we are..
    config = toml.loads(open("config.toml").read())
    ##Get the lookback from the config file, and then offset this from a current datestamp
    lookback = config["RSS_Import"]["initial_podcast_lookback"]
    sync_date = datetime.datetime.now() - datetime.timedelta(days=lookback)
    syncfrom = sync_date.isoformat()

    ##Now append the entry to our feeds list
    feeds.append({"id":nextID,"title":title,"url":rss_url, "syncFrom": syncfrom, "safe_name": safe_name})
    
    ##And finally save it back to file
    save_feed_file(feeds)

    print(f"Added {title} to the feeds file.")
        
def view_RSS():
    ##Initialize our storage file for our RSS feeds
    initialize_feed_file()
    feeds = get_feed_file()

    ##get the feeds from the file and order them by ascending ID
    feeds = sorted(feeds, key=lambda x: x["id"])
    for feed in feeds:
        print(f"{feed['id']}: {feed['title']}")

def delete_RSS():
    ##Use View function to display the feeds
    view_RSS()
    ##Now ask the user which ID they want to delete.
    id_to_delete = input("Enter the ID of the feed you want to delete:")
    ##Check it's an integer
    if not id_to_delete.isdigit():
        print("Invalid ID. Please enter a number.")
        return
    ##Convert it to an integer
    id_to_delete = int(id_to_delete)
    ##Open the file
    feeds = get_feed_file()
    ##Check if the ID exists
    feed_to_delete = next((feed for feed in feeds if feed["id"] == id_to_delete), None)
    if not feed_to_delete:
        print("ID not found.")
        return
        
    safe_name = feed_to_delete.get("safe_name", str(id_to_delete))
    
    ##Remove the feed
    feeds = [feed for feed in feeds if feed["id"] != id_to_delete]
    ##Save the file
    save_feed_file(feeds)

    ##Delete the child folder associated with this feed, including all subfolders and files within
    folder_to_delete = f"data/{safe_name}"
    if os.path.exists(folder_to_delete):
        shutil.rmtree(folder_to_delete)

    print(f"Deleted feed with ID {id_to_delete}.")
    

def initialize_feed_file():
    ##If the data folder doesn't exist, create it
    if not os.path.exists("data"):
        os.makedirs("data") 
    ##If we don't have a file for our RSS feeds, then create one 
    if not os.path.exists("data/feeds.json"):
        f = open("data/feeds.json", "w")
        f.write("[]")
        f.close()
        print("Created a new feeds.json file.")
    else:
        print("Existing feeds.json found")

def get_feed_file():
    initialize_feed_file()
    with open("data/feeds.json", "r") as f:
        return json.load(f)

def save_feed_file(feeds):
    with open("data/feeds.json", "w") as f:
        json.dump(feeds, f, indent=4)


