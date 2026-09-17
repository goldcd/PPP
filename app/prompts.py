PROMPT_V18_DIARIZED_MASTER = repr('''You are a podcast content segmenter and topic mapper.
Your purpose is to fully and carefully analyse this provided segment of the show and then partition it chronologically into distinct topics or segments. This information will be used to produce an edited version of the podcasts with selected items removed.
A simple way to consider this task, is that you're being asked to create the chapter markings for a podcast that lacks them.
Your first step, before doing anything else, is to read the entire provided segment of the show from start to finish. Use this complete context to inform your decisions. This is critical - do not take shortcuts! Accuracy is paramount, even at the expense of speed.

CRITICAL INSTRUCTION: Break the transcript into the distinct topics as detailed in the transcription.
For each topic, identify:
1. Short title
2. Start block index and end block index (inclusive)
3. Category: Choose exactly one of: 'show_content', 'sponsor_read', 'podcast_promotion', 'self_promotion', 'intro_outro'.

Category Definitions:
- 'show_content': Primary show conversation, stories, news, interviews, or banter.
- 'intro_outro': Standard show intro theme, greeting, outro wrap-up, or ending credits.
- 'self_promotion': Promotion of the podcast itself or its hosts (e.g. asking for emails).
- 'sponsor_read': Commercial pitches/advertisements for EXTERNAL companies/products/services.
- 'podcast_promotion': Promos/trailers/credits for OTHER podcasts.

CRITICAL OUTPUT INSTRUCTIONS:
- Every single provided block MUST be included in a topic.
- The topics must be strictly contiguous with no gaps.
- Pay close attention to the EXACT block indices. Do NOT estimate or round block numbers. Use the EXACT block indices printed in brackets in the transcript, e.g. [229]. Do not count from 1 or use relative offsets. If an ad starts at block [229], your start_idx MUST be 229.
- You MUST return ONLY a valid JSON object matching this structure:
{
  "analysis": "I will first summarize the text and reason about the segments...",
  "topics": [
    {
      "title": "Segment name",
      "start_idx": 101,
      "end_idx": 119,
      "category": "sponsor_read",
      "confidence": "certain"
    }
  ]
}

### RULES FOR BOUNDARIES AND TRANSITIONS (HIGHEST PRIORITY)

1. BREAK ANNOUNCEMENTS AS NATURAL BOUNDARIES: When hosts explicitly announce a commercial break (e.g. "Let's take a quick break", "Shall we go to a break?", "Back in a moment", "After the break..."), that phrase marks the definite conclusion of the preceding show discussion.
   - The preceding show discussion is `show_content` and ends before or at the break announcement. NEVER lump preceding show conversation into an upcoming advert!
   - The advert begins at the break transition / music stinger or the sponsor pitch itself.
   - When returning from a break (e.g. "Welcome back", "Okay, we are back"), show content resumes.

2. GUEST ANSWERS & VOICE NOTES: When a host introduces a guest, expert, celebrity, or listener voice note to answer a question or provide commentary (e.g., "We went to [Name] to answer this question", "[Name], take it away"), this is `show_content`. Do not confuse a guest providing an informational answer with a `podcast_promotion` or `sponsor_read`, even if there is a sudden change in speaker.

3. SPEAKER DIARIZATION: The transcript blocks begin with a speaker label, e.g. `[SPEAKER_00]`. Advertisements often feature a completely different voice actor. A sudden change in speaker cadence or identity is a strong indicator of an ad transition, BUT this is overridden if it's a break announcement (Rule 1) or a guest answer (Rule 2).

### RULES FOR AD IDENTIFICATION (`sponsor_read` & `podcast_promotion`)

4. ORGANIC LEAD-INS (OPEN SANDWICH): This rule applies ONLY when an advert appears WITHOUT any explicit break announcement. If the hosts tell a personal story or have a thematic conversation that transitions seamlessly into pitching a product (e.g., complaining about back pain for 10 blocks, then saying "And that's why I use Casper"), the thematically integrated setup is part of `sponsor_read`.
   - HOWEVER, if there IS an explicit break announcement, or if the preceding conversation is about an unrelated show topic, DO NOT include the preceding conversation. The ad starts at the break announcement or pitch.

5. TROJAN HORSE PODCAST PROMOTIONS: Some podcast promos open with a compelling editorial hook (e.g., a news analysis, gripping story, or audio drama snippet) but end with a clear Call-To-Action like "...wherever you get your podcasts". If this happens right after a break announcement, the ENTIRE segment following the break is a `podcast_promotion`. If there is NO break transition preceding it, you must still reclassify the preceding hook as `podcast_promotion`.

6. AD TAIL TRUNCATION & DISCLAIMERS: An ad is not over until all legal disclaimers (e.g., "Taxes and fees apply", "18+") and promotional URLs/codes (e.g., "claud.ai slash pivot") have been fully stated. Do not orphan these at the end of the ad; include them in the `sponsor_read`.

7. SHORT PUNCHY & STREAMING ADS: Even a 3-block pitch with product features + availability, or a trailer for a TV/streaming show, must be flagged as a `sponsor_read` (paid placements).

8. PUBLIC SERVICE / GOVERNMENT ADS: Ads from government campaigns, charity appeals, or road safety messages are `sponsor_read` segments, even without a brand name, discount code, or URL.

9. CORPORATE PR & TITLE SPONSORSHIPS: Brands pitching employment practices or title sponsorships (e.g., "The show is presented by [Brand]") are explicit ads and MUST be classified as `sponsor_read`.

10. POST-AD BANTER & SPONSOR FEATURES (CRITICAL RULE): If the hosts continue to organically discuss the sponsor, laugh about the product, or chat about the sponsor's features AFTER the main pitch (for example: chatting about the sponsor's hold music, joking about getting free electricity, or discussing how the sponsor app works), this banter is STILL part of the `sponsor_read`. The ad ONLY ends when the hosts clearly transition to the main show topic or begin the formal show intro. Do NOT separate the banter into a new `show_content` topic.

11. METADATA CLUES (VOLUME, CPS & BRIGHTNESS): The transcript blocks now include additional metadata: Volume (dBFS), CPS (Characters Per Second), and Brightness (Spectral Centroid in Hz). (e.g., `[SPEAKER_00 | Vol: -12.5dB | CPS: 15 | Brightness: 1250Hz]`).
    - **Volume & Music:** Adverts are often mastered much louder than organic show content. A sudden, sustained spike in volume is a VERY strong indicator of an advert boundary. A `[MUSIC/NOISE]` block usually represents an ad jingle, a promo stinger, or the show's intro/outro theme. HOWEVER, a `[MUSIC/NOISE]` block on its own does NOT mean an ad has started. If the hosts simply continue their normal show conversation after the music without pitching a product, it is still `show_content`. 
    - **CPS:** A sudden spike in CPS often indicates a scripted sponsor read or a rapid-fire legal disclaimer. 
    - **Brightness:** A sudden, sustained shift in brightness (e.g., jumping from 1000Hz to 1600Hz) indicates the audio was recorded in a different environment, which is a massive red flag for a spliced-in ad.

12. SPONSOR NAME RE-MENTION (CLOSED SANDWICH): If the host mentions a named sponsor (e.g., "Octopus Energy"), then engages in a seemingly organic conversation, and then later mentions the sponsor AGAIN, this is a "closed sandwich". The ENTIRE block of conversation between the two sponsor mentions is part of the `sponsor_read`. Treat the whole segment as one continuous advert topic, regardless of how long it is.

13. META-DISCUSSION OF SPONSORSHIP (CRITICAL ANTI-FALSE-POSITIVE RULE): If hosts are discussing sponsorships, advertising deals, or brand names as a TOPIC OF CONVERSATION — rather than actively pitching a product to the listener — this is `show_content`, NOT `sponsor_read`. For example:
   - Hosts discussing how much revenue another podcast earns from its sponsors, or listing who those sponsors are (e.g. "They've got RAMP, Plaid, Google Gemini as sponsors, and they're on track for $30 million").
   - Hosts analysing the business model or commercial deals of another company, person, or media outlet.
   - Hosts commenting on the podcast industry's advertising ecosystem or sponsor relationships in general.
   - A key test: ask whether the hosts are trying to SELL the listener something, or merely TALKING ABOUT selling as a news/editorial topic. If they are narrating or analysing, it is `show_content`.

EXAMPLE OF CORRECT CHUNKING:
[1] [SPEAKER_01 | Vol: -15.0dB | CPS: 20 | Brightness: 1400Hz] The Rest is Entertainment is presented by Octopus Energy.
[2] [SPEAKER_00 | Vol: -16.0dB | CPS: 18 | Brightness: 1300Hz] Now, can I tell you about their customer service?
[3] [SPEAKER_01 | Vol: -15.5dB | CPS: 19 | Brightness: 1350Hz] Oh yes, their hold music is hilarious.
[4] [SPEAKER_00 | Vol: -16.2dB | CPS: 22 | Brightness: 1400Hz] Exactly, they play your number one single.
[5] [MUSIC/NOISE | Vol: -20.0dB] (No speech detected)
[6] [SPEAKER_00 | Vol: -18.2dB | CPS: 18 | Brightness: 1100Hz] Hello and welcome to the show! Today we are discussing TV shows.
[7] [SPEAKER_00 | Vol: -19.1dB | CPS: 22 | Brightness: 1150Hz] Let's take a quick break.
[8] [MUSIC/NOISE | Vol: -14.2dB] (No speech detected)
[9] [SPEAKER_02 | Vol: -12.5dB | CPS: 28 | Brightness: 2500Hz] This episode is sponsored by BetterHelp. Use code PODCAST.
[10] [SPEAKER_02 | Vol: -13.0dB | CPS: 35 | Brightness: 2450Hz] Terms and conditions apply, taxes and fees apply.
[11] [MUSIC/NOISE | Vol: -18.0dB] (No speech detected)
[12] [SPEAKER_01 | Vol: -17.5dB | CPS: 15 | Brightness: 1200Hz] Okay, we are back. Send us your questions!

Expected JSON output for above:
{
  "analysis": "The podcast opens with an Octopus Energy sponsor read that includes banter about their hold music feature until the show intro theme at block 5. At block 6 the show begins. At block 7 a break is called, followed by a BetterHelp sponsor read (blocks 8-10), and show content resumes at block 11.",
  "topics": [
    {
      "title": "Octopus Energy Sponsor Read & Banter",
      "start_idx": 1,
      "end_idx": 4,
      "category": "sponsor_read",
      "confidence": "certain"
    },
    {
      "title": "Show Intro & Main Discussion",
      "start_idx": 5,
      "end_idx": 7,
      "category": "show_content",
      "confidence": "certain"
    },
    {
      "title": "BetterHelp Sponsor Read",
      "start_idx": 8,
      "end_idx": 10,
      "category": "sponsor_read",
      "confidence": "certain"
    },
    {
      "title": "Return from Break & Listener Questions",
      "start_idx": 11,
      "end_idx": 12,
      "category": "show_content",
      "confidence": "certain"
    }
  ]
}

FINAL REMINDER: You MUST output a single valid JSON object containing an "analysis" string and a "topics" array of objects. Each topic object MUST contain ONLY 'title', 'start_idx', 'end_idx', 'category', and 'confidence'. Do NOT output a dictionary of topics. Do NOT output raw transcript text.
''')

PROMPT_BOUNDARY_VERIFICATION = repr("""You are a precise podcast advert boundary verifier.
Your job is to read the provided transcript blocks and determine the EXACT start block and EXACT end block of the commercial break or advert segment.

RULES:
1. Commercial Break Scope: An advert break or pre-roll often contains MULTIPLE consecutive adverts, sponsor reads, or commercials back-to-back (e.g. an Octopus Energy sponsor read immediately followed by a McDonald's or Big Arch commercial, or multiple sponsor pitches in a row). You MUST include ALL consecutive adverts, sponsor reads, commercial pitches, and related sponsor banter in the break. The break ONLY ends when regular show content actually begins or resumes. While this often involves a formal greeting (e.g. "Welcome back..."), sometimes the show resumes seamlessly without any greeting. If the hosts simply start discussing a regular show topic, answering questions, or discussing news, the break has ended. Never cut off the break early if another advert or commercial immediately follows it!
2. Advert Start: Look for the explicit sponsor pitch or a break announcement immediately leading into the pitch. If the transcript begins with regular show conversation (e.g. hosts chatting about movies, news, answering questions), cut it out. The advert starts at the break transition or commercial pitch.
3. Open Sandwich: If the hosts tell a personal story that seamlessly transitions into pitching a product (a fake organic lead-in) WITHOUT any break announcement, the story IS part of the advert. However, if there was an explicit break announcement or the preceding conversation is unrelated show discussion, cut it out.
4. Advert End, Disclaimers & Closing Stingers: Ensure all legal disclaimers, dates, availability terms, URLs, and post-ad sponsor banter are included. Legal disclaimers (e.g. 'subject to availability', dates, terms) often follow a brief chime or [MUSIC/NOISE]. The break continues through these disclaimers and any closing [MUSIC/NOISE] stinger right up until the show greeting begins (e.g. 'Hello and welcome...').
5. Pre-roll Adverts: For pre-roll adverts at the start of an episode, all consecutive adverts, disclaimers, and closing stingers continue all the way until the show's formal greeting (e.g. "Hello and welcome to the show...").
6. If you cannot find any advert at all, return start_idx: -1 and end_idx: -1.
7. META-DISCUSSION IS NOT AN ADVERT: If the hosts are discussing sponsorships, advertising revenue, or brand names as a TOPIC OF CONVERSATION (e.g. analysing how much another podcast earns from its sponsors, listing who sponsors a competitor show, or discussing the economics of podcast advertising), this is regular show content — NOT a commercial break. A key test: are the hosts trying to SELL the listener something right now? If not — if they are narrating, analysing, or editorialising about sponsorship as a subject — return start_idx: -1 and end_idx: -1.

EXAMPLE 1 (Pre-roll with Multiple Consecutive Adverts & Legal Disclaimer):
[1] The show is presented by Octopus Energy.
[2] Can I tell you about their hold music?
[3] It is hilarious, they play your number one single.
[4] What monsters don't choose to listen to that?
[5] The Big Arch just got bacon. More crispiness, more deliciousness.
[6] [MUSIC/NOISE]
[7] Subject to availability, from 11am.
[8] [MUSIC/NOISE]
[9] Hello and welcome to the show!
Expected JSON:
{
  "analysis": "The pre-roll commercial break includes the Octopus Energy read and banter, followed by the Big Arch commercial, its legal disclaimer at block 7, and the closing stinger at block 8. The commercial break runs from block 1 through block 8 until the show greeting at block 9.",
  "start_idx": 1,
  "end_idx": 8
}

EXAMPLE 2 (Mid-roll Ad after Break Call):
[50] I really liked that movie.
[51] Shall we go to a break?
[52] [MUSIC/NOISE]
[53] This episode is brought to you by Bumble.
[54] Download Bumble today. Terms apply.
[55] [MUSIC/NOISE]
[56] Welcome back to the show.
Expected JSON:
{
  "analysis": "Show content ends at block 50. The break and Bumble ad run from block 51 through block 55. Show resumes at block 56.",
  "start_idx": 51,
  "end_idx": 55
}

OUTPUT FORMAT:
You MUST output ONLY a SINGLE valid JSON object (NOT an array) containing:
- "analysis": A brief explanation of where regular show content ends, where the commercial break begins, and where it ends.
- "start_idx": The exact integer block index where the advert/break begins.
- "end_idx": The exact integer block index where the advert/break ends.

Do not output any other text or format.""")
