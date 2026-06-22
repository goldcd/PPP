# Perfect Podcast Proxy

## Purpose

Goal of this app is to provide a proxy for your podcasts, which will modify the raw feed in useful ways - initially advert removal.

App should be entirely self-contained, allowing podcasts to be processed and served from your local machine, without external interaction.

## Scope

The current scope is to:
- Allow you to onboard a public RSS podcast feed
- Trigger a local download of this feed (defaults to last 7 days of episodes)
- Generate an SRT transcription of each episode
- Parse transcription to detect advert segments
- Generate a 'cleaned' version of the podcast with these segments excised
- Provide a server that allows you to subscribe this cleaned feed.



## Prerequisites

- Python (run script should create venv)
- Disk space (run script will be downloading models, plus whatever you need for your podcasts
- nVidia GPU ideally, but should fall back to CPU (fast on Apple, not fast on anything else)
- Ollama


## Usage

- run.bat/sh launches the application
- "Manage Podcast Feeds" allows you to view/add/delete RSS feeds. 
  - This is persisted \data\feeds.json
  - Defaults lookback period to 7 days (can change this in config)
- "Manage Podcast Processing"
  - Download
    - Retrieves latest version of public RSS feed to data\<podcast id>\raw
    - Downloads podcast mp3s (unless older than lookback or already downloaded)
  - Transcribe 
    - Generates ,srt transcription in data\<podcast id> for all podcasts without one
- "Trigger All Podcast Processing"
  - Executes all of the "Manage Podcast Processing" options in order
  
  
## Known Issues / Limitations

- Current versions isn't designed to operate from the CLI. I'll add this later, so this can more easily be run in the background/automated.
- Assumes Ollama is installed locally on default port
- I'd like to find a way to dump the output somewhere web-accessible (i.e. so I don't have to have the app running, to transfer to my phone)

## Scratchpad

I'll use Pivot as my test podcast. Mainly as there's no way to get a version of it without adverts - so I'm guilt free

At some point need to come up with a longer list, for testing
https://feeds.megaphone.fm/pivot

https://feeds.megaphone.fm/kermodeandmayo

https://audioboom.com/channels/2399216.rss

- 