# Perfect Podcast Proxy

## Version
- 2.1
  - Upgraded advert detection to high-accuracy Two-Stage Macro-Window + Boundary Verification pipeline
  - Upgraded default GPU model to Qwen 3.8 27B (IQ3_S MTP)
- 2.0
  - Upgraded transcription to include diarization (WhisperX + pyannote)
  - Upgraded to three-pass advert detection, dramatically improving accuracy

## Purpose

Provide a proxy for your podcasts - with the adverts removed.

Entirely self-contained/private. No cloud processing of data. No community annotations/corrections required.

## Scope

The current scope is to:
- Allow you to onboard a public RSS podcast feed
- Trigger a local download of this feed (defaults to last 7 days of episodes)
- Generate an SRT transcription of each episode
- Parse transcription to detect advert
- Generate a 'cleaned' version of the podcast with these segments excised
- Optionally output a web page with modified feeds and podcasts, allowing you to subscribe to them however you normally do
- Includes basic logging and stat generation

## Prerequisites

- Python (run script should create venv)
- Disk space (run script will be downloading models, plus whatever you need for your podcasts)
- nVidia GPU ideally, but should fall back to CPU 
  - e2e processing on GPU ~ 15x on GPU, 3x on CPU (Apple should be faster, but not tried)
- Ollama
- Requires HuggingFace API token for transcription (see config.toml)


## Usage

- run.bat/sh launches the application
- "Manage Podcast Feeds" allows you to view/add/delete RSS feeds. 
  - This is persisted \data\feeds.json
  - Defaults lookback period to 7 days (can change this in config)
- "Manage Podcast Processing"
  - Download
    - Retrieves latest version of public RSS feed to `data/<podcast>/raw`
    - Downloads podcast mp3s (unless older than lookback or already downloaded)
  - Transcribe 
    - Generates .srt transcription in data\<podcast id> for all podcasts without one
  - Detect Adverts
    - Scans transcription for adverts and generates SRT of their placement
  - Generate Clean
    - Generates a new mp3 file with the adverts removed
    - Configurable Pop can be inserted where content was removed
  - Export Podcast
    - Copies processed files to a web-accessible directory
    - Generates a cleaned RSS feed that can be subscribed to, via landing page (or by copying the RSS link, if that doesn't work). Cleaned feed removes metadata and adds "PPP" prefix to podcast (prevents some podcast apps deciding to helpfully grab the un-cleaned feed, rather than the one you provided)
- "Trigger All Podcast Processing"
  - Executes all of the "Manage Podcast Processing" options in order

## State Logic

- Logic flow is determine by presence of files, so I'll just explain that here (maybe I'll do this properly later, but probably not)
- Nothing is ever automatically deleted
- When adding a podcast, this is added to /data/feeds.json and defaults to 7 days back as download limit (can be changed at any time)
- Downloaded Podcasts are placed in /data/<podcast>/raw
  - Download is skipped, if file already exists
  - Following download, feeds.json is updated with current timestamp, so this podcast won't be re-downloaded (unless manually push back the timestamp)
- Transcription creates .srt file for each podcast in raw folder
  - Transcription is skipped, if .srt exists for the podcast
- Ad-detection creates another sibling with .ad extension
  - Ad-detection is skipped, if .ad exists for the podcast
  - .ad contains the portion of the SRT marked for excision (i.e. diff the .ad and .srt, to see what's being retained)
- Cleaned Podcast is written to /data/<podcast>/output
  - If it doesn't already exist in /output
- i.e. Unless you're ever wanting to re-process - you can delete the /raw folders to save space. 
  
  
## Example

Example of how PPP generates an overview of the show content from the transcription and scores them. If it scores too highly, it gets flagged and excised from podcast presented on cleaned feed.

```
--- GENERATED TOPIC MAP ---
Start  | End    | Duration | Category           | Title
----------------------------------------------------------------------------------------------------
1      | 12     | 12       | show_content       |       Show Content
13     | 25     | 13       | sponsor_read       |       Fuse Energy Sponsor Read [FLAGGED]
26     | 32     | 7        | sponsor_read       |       Accenture Sponsor Read [FLAGGED]
33     | 343    | 311      | show_content       |       Show Content
344    | 350    | 7        | podcast_promotion  |       Promotion of Podcast Series with The Observer [FLAGGED]
351    | 360    | 10       | show_content       |       Show Content
361    | 361    | 1        | podcast_promotion  |       Intro Music and 'The Rest is Football' Promotion [FLAGGED]
362    | 365    | 4        | podcast_promotion  |       Promotion of 'The Rest is Football' Podcast on Netflix [FLAGGED]
366    | 368    | 3        | podcast_promotion  |       Podcast Promotion for 'The Rest is Football' [FLAGGED]
369    | 380    | 12       | sponsor_read       |       Wordsmith Sponsor Read [FLAGGED]
381    | 395    | 15       | sponsor_read       |       Staysure Travel Insurance Sponsor Read [FLAGGED]
396    | 724    | 329      | show_content       |       Show Content
----------------------------------------------------------------------------------------------------
```

## Advert Detection Process

The system utilizes a high-precision, two-stage advert detection pipeline using modern LLMs (e.g., Qwen 3.8 27B / Qwen 2.5):

* **Stage 1: Macro-Window Commercial Pod Isolation**
  The transcript is processed in overlapping macro-windows of 120 subtitle blocks (~8–10 minutes) with a step of 90 blocks. This macro-context ensures the model sees the entire commercial break container (including multiple stacked sponsors, promotional trailers, and surrounding show transitions) in a single view, preventing attention loss and avoiding cutting ads in half.

* **Stage 2: Targeted Boundary Verification Refinement**
  For each detected commercial break pod, a focused boundary verification pass is executed on a narrow window (+/- 8 blocks) around the candidate edges. This stage snaps start and end boundaries down to the exact subtitle line, trims trailing host banter, and prunes false-positive candidates that contain no external sponsors.

* **Stage 3: Micro-Gap Bridging & Excision Mapping**
  Small micro-gaps (<= 3 blocks) caused by music stingers, transition sound effects, or breathers between consecutive adverts are bridged into a single clean cut. The resulting `.ad` excision file is generated alongside the original `.srt`.

