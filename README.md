# Perfect Podcast Proxy

## Purpose

Provide a proxy for your podcasts - with the adverts removed.

Entirely self-contained/private. No cloud processing of data. No community annotations/corrections required.

## Scope

The current scope is to:
- Allow you to onboard a public RSS podcast feed
- Trigger a local download of this feed (defaults to last 7 days of episodes)
- Generate an SRT transcription of each episode
- Parse transcription to detect advert
  - Firstly detect the thematic segments within the podcast
  - Apply rules/weightings to segments, based on user config/preferences
  - Generate SRT of content to be removed
- Generate a 'cleaned' version of the podcast with these segments excised
- Optionally output a web page with modified feeds and podcasts, allowing you to subscribe to them however you normally do

## Prerequisites

- Python (run script should create venv)
- Disk space (run script will be downloading models, plus whatever you need for your podcasts)
- nVidia GPU ideally, but should fall back to CPU 
  - e2e processing on GPU ~ 15x on GPU, 3x on CPU (Apple should be faster, but not tried)
- Ollama


## Usage

- run.bat/sh launches the application
- "Manage Podcast Feeds" allows you to view/add/delete RSS feeds. 
  - This is persisted \data\feeds.json
  - Defaults lookback period to 7 days (can change this in config)
- "Manage Podcast Processing"
  - Download
    - Retrieves latest version of public RSS feed to data\\<podcast>\raw
    - Downloads podcast mp3s (unless older than lookback or already downloaded)
  - Transcribe 
    - Generates ,srt transcription in data\<podcast id> for all podcasts without one
  - Detect Adverts
    - Scans transcription for adverts and generates SRT of their placement
    - Types of content you want to remove/retain can be specified in config
  - Generate Clean
    - Generates a new mp3 file with the adverts removed
    - Configurable Pop can be inserted where content was removed
  - Export Podcast
    - Copies processed files to a web-accessible directory
    - Generates a cleaned RSS feed that can be subscribed to, via landing page (or by copying the RSS link, if that doesn't work)
- "Trigger All Podcast Processing"
  - Executes all of the "Manage Podcast Processing" options in order
  
  
## Known Issues / Limitations

- Current versions isn't designed to operate from the CLI. I'll add this later, so this can more easily be run in the background/automated.
  - #edit#I did hack in "grab_and_process_new_podcasts.bat" to just give you something to click to update existing feeds
- Assumes Ollama is installed locally on default port
- Only really been tested against my personal needs/PC
- No mechanism to manage downloaded podcasts - they'll just accumulate over time. Probably the next feature. 
- Currently we hard-cut adverts. Not seen mistakes yet, but they'll happen. Maybe add a chapter annotation as a mandatory feature. Then can have the cutting of adverts as an optional extra (I'll need to check what podcast players know to skip advert chapters, and what triggers them)



## Example

Example of how PPP generates an overview of the show content from the transcription and scores them. If it scores too highly, it gets flagged and added to the list of segments to be removed.

```
--- GENERATED TOPIC MAP & WEIGHTING ---
Start  | End    | Duration | Category           | Score | Title
----------------------------------------------------------------------------------------------------
1      | 10     | 10       | sponsor_read       | 17    | Ateo Sponsor Read [FLAGGED]
11     | 19     | 9        | sponsor_read       | 17    | Core Wave Sponsor Read [FLAGGED]
20     | 25     | 6        | podcast_promotion  | 17    | Markets Podcast Promo [FLAGGED]
26     | 30     | 5        | intro_outro        | 4     | Show Intro
31     | 120    | 90       | show_content       | -8    | Cannes and Heat Discussion
106    | 119    | 14       | show_content       | 4     | Discussion about hotel bills and Adweek event location
120    | 159    | 40       | show_content       | 4     | Creator economy trends and statistics
160    | 183    | 24       | show_content       | 4     | Evolution of podcasting and future directions
184    | 189    | 6        | show_content       | 4     | Discussion about 'unnatural acts' and interview strategy
190    | 225    | 36       | show_content       | 4     | Green Water Gate incident and Trump's claims
211    | 229    | 19       | show_content       | 4     | Reflecting Pool Incident and Government Incompetence
230    | 250    | 21       | show_content       | 4     | Iranian MOU and Diplomatic Stalemate
251    | 272    | 22       | show_content       | 4     | Impact of Iran's Strategy and JCPOA Analysis
273    | 282    | 10       | show_content       | 4     | Reflecting Pool as a Symbol of Incompetence
283    | 300    | 18       | show_content       | 4     | Trump's Leadership and Political Consequences
301    | 317    | 17       | show_content       | 4     | Midterm Elections and Iran's Nuclear Threat
318    | 330    | 13       | sponsor_read       | 17    | Sponsor Read: Framer Website Builder Promotion [FLAGGED]
316    | 321    | 6        | show_content       | 4     | Discussion on Iran and Political Break
322    | 339    | 18       | sponsor_read       | 17    | Framer Sponsor Read [FLAGGED]
340    | 341    | 2        | sponsor_read       | 17    | Framer Discount Reminder [FLAGGED]
342    | 358    | 17       | sponsor_read       | 17    | Vanta Sponsor Read [FLAGGED]
359    | 378    | 20       | sponsor_read       | 17    | ShipStation Sponsor Read [FLAGGED]
379    | 435    | 57       | show_content       | 1     | UK Political Analysis and Discussion
421    | 470    | 50       | show_content       | 1     | UK Politics and Economic Challenges
471    | 500    | 30       | show_content       | 4     | Trump's Feud with Italian PM and Marjorie Taylor Greene
501    | 540    | 40       | show_content       | 4     | European Unity and Trump's Impact on Alliances
526    | 561    | 36       | show_content       | 4     | Political Discussion on Leadership and Trump
576    | 598    | 23       | sponsor_read       | 17    | Sponsor Read: Freedom from Religion Foundation [FLAGGED]
599    | 601    | 3        | sponsor_read       | 17    | Sponsor Read: HIMS Weight Loss Services [FLAGGED]
602    | 619    | 18       | sponsor_read       | 17    | Sponsor Read: Teleport AI Infrastructure [FLAGGED]
620    | 645    | 26       | show_content       | 4     | Discussion on Trump, Zuckerberg, and Bezos
631    | 728    | 98       | show_content       | -8    | Political Commentary on Billionaire-Politician Dynamics
729    | 750    | 22       | show_content       | 4     | Amazon's Decision to Drop Sam Altman Film
736    | 755    | 20       | show_content       | 4     | Discussion of Amazon's Movie and Netflix's Cancellation
756    | 784    | 29       | show_content       | 4     | Netflix's Cancellation of Big Tech Series and Reasons
785    | 819    | 35       | show_content       | 4     | Details on the Canceled Show's Development and Challenges
820    | 855    | 36       | show_content       | 4     | Analysis of Media Trends and Big Tech Storytelling
841    | 860    | 20       | show_content       | 4     | Discussion on Sheryl Sandberg and Big Tech Figures
861    | 876    | 16       | show_content       | 4     | Mention of Book and Theatrical Show Projects
877    | 880    | 4        | show_content       | 4     | SpaceX Stock Price Analysis
884    | 895    | 12       | show_content       | 4     | Listener Question on Elon Musk's Share Holdings
896    | 900    | 5        | show_content       | 4     | Explanation of Borrowing Against Shares
901    | 920    | 20       | show_content       | 4     | Detailed Discussion on 'Buy, Borrow, Die' Strategy
921    | 931    | 11       | show_content       | 4     | Tax Implications and Wealth Management
932    | 940    | 9        | show_content       | 4     | Borrowing Against Stock for Political Funding
941    | 960    | 20       | show_content       | 4     | Price-to-Sales Ratio Comparison of Companies
946    | 977    | 32       | show_content       | 4     | Stock Market and Company Analysis
978    | 1007   | 30       | show_content       | 4     | Health Impacts of GLP-1 Drugs and Personal Health Decisions
1020   | 1042   | 23       | sponsor_read       | 17    | Sponsor Read: Gusto Payroll and HR Software [FLAGGED]
1043   | 1055   | 13       | sponsor_read       | 17    | Sponsor Read: Vanta Security Platform [FLAGGED]
1056   | 1065   | 10       | show_content       | 4     | Wins and Fails Segment: World Cup Tourism and Cultural Reactions
1051   | 1055   | 5        | sponsor_read       | 17    | Vantar Sponsor Pitch [FLAGGED]
1056   | 1104   | 49       | show_content       | 1     | World Cup Tourism Successes and Cultural Observations
1105   | 1170   | 66       | show_content       | 0     | Discussion of Holly Market's Deceptive Practices
1156   | 1179   | 24       | show_content       | 4     | Deceptive Marketing and Free Speech Debate
1180   | 1199   | 20       | show_content       | 4     | Political Commentary on Transphobic Attacks
1203   | 1224   | 22       | show_content       | 4     | Discussion of New Toy Story Movie
1228   | 1249   | 22       | show_content       | 4     | Humorous Anecdote About Ex-Wife and Woody
1252   | 1275   | 24       | intro_outro        | 4     | Toy Story 6 Plot Discussion and Outro Transition
1261   | 1280   | 20       | show_content       | 4     | Toy Story 6 Joke and Banter
1281   | 1293   | 13       | show_content       | 4     | Live Event and Interview Announcements
1294   | 1300   | 7        | show_content       | 4     | Playful Banter and Social Plans
1301   | 1306   | 6        | show_content       | 4     | Listener Engagement and Question Submission
1307   | 1339   | 33       | show_content       | 4     | Interview with Harvey Levin from TMZ
1340   | 1349   | 10       | intro_outro        | 4     | Outro and Production Credits
1350   | 1360   | 11       | sponsor_read       | 17    | Dell PCs Sponsorship Pitch [FLAGGED]
----------------------------------------------------------------------------------------------------
```
