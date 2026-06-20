import os
import requests
import json
import xml.etree.ElementTree as ET

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

    ##Check it's not already there
    if feeds.get(title):
        print(f"{title} is already in the feeds file.")
        return
    
    ##Now we can add it
    feeds[title]={"url":rss_url}
    
    ##And finally save it back to file
    save_feed_file(feeds)

    print(f"Added {title} to the feeds file.")
        

    

def initialize_feed_file():
    ##If we don't have a file for our RSS feeds, then create one 
    if not os.path.exists("data/feeds.json"):
        f = open("data/feeds.json", "w")
        f.write("{}")
        f.close()
        print("Created a new feeds.json file.")
    else:
        print("Existing feeds.json found")

def get_feed_file():
    with open("data/feeds.json", "r") as f:
        return json.load(f)

def save_feed_file(feeds):
    with open("data/feeds.json", "w") as f:
        json.dump(feeds, f, indent=4)


