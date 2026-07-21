import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

"""
generate_stats.py

Generates a Markdown report of ad-to-content ratios across all processed podcasts.

How it works:
  1. Walks data/ for podcast folders containing a raw/rss.xml.
  2. Parses the RSS to get the podcast title and a GUID→episode-title mapping.
  3. For each episode that has both a .srt and a .ad file, computes:
       - Total podcast duration  (first block start → last block end)
       - Total ad duration       (sum of contiguous ad-block runs)
       - Percentage of ad time
  4. Writes a report to data/podcast_stats.md.
"""


def _parse_time(t_str):
    """Convert an SRT timestamp string to seconds (float)."""
    t_str = t_str.strip().replace(',', '.')
    h, m, s = t_str.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def _parse_srt_timing(path):
    """
    Parse an SRT file and return a list of {idx, start_time, end_time} dicts.
    Returns an empty list on any failure.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return []

    blocks = []
    for raw in re.split(r'\n\n+', content.replace('\r\n', '\n').strip()):
        lines = [l for l in raw.strip().split('\n') if l.strip()]
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
            time_line = lines[1].strip()
            if ' --> ' not in time_line:
                continue
            start_str, end_str = time_line.split(' --> ')
            blocks.append({
                'idx': int(idx),
                'start_time': _parse_time(start_str),
                'end_time':   _parse_time(end_str),
            })
        except Exception:
            pass
    return blocks


def _calc_episode_stats(srt_path, ad_path):
    """
    Compute stats for one episode.
    Returns (total_secs, ad_secs, ad_pct) or None if the files can't be parsed.
    """
    srt_blocks = _parse_srt_timing(srt_path)
    if not srt_blocks:
        return None

    total_secs = srt_blocks[-1]['end_time'] - srt_blocks[0]['start_time']
    if total_secs <= 0:
        return None

    ad_blocks = _parse_srt_timing(ad_path)
    if not ad_blocks:
        return (total_secs, 0.0, 0.0)

    # Build set of ad block indices and walk the full SRT to measure contiguous runs
    ad_idx_set = {b['idx'] for b in ad_blocks}
    ad_srt_blocks = [b for b in srt_blocks if b['idx'] in ad_idx_set]

    if not ad_srt_blocks:
        return (total_secs, 0.0, 0.0)

    total_ad_secs  = 0.0
    run_start = ad_srt_blocks[0]['start_time']
    run_end   = ad_srt_blocks[0]['end_time']
    last_idx  = ad_srt_blocks[0]['idx']

    for b in ad_srt_blocks[1:]:
        if b['idx'] == last_idx + 1:
            run_end = b['end_time']
        else:
            total_ad_secs += run_end - run_start
            run_start = b['start_time']
            run_end   = b['end_time']
        last_idx = b['idx']

    total_ad_secs += run_end - run_start

    ad_pct = (total_ad_secs / total_secs) * 100
    return (total_secs, total_ad_secs, ad_pct)


def generate_stats():
    """
    Main entry point. Scans all podcasts, computes ad percentages,
    and writes data/podcast_stats.md.
    """
    print("Generating podcast ad statistics...")

    data_dir = "data"
    if not os.path.exists(data_dir):
        print("No data folder found.")
        return

    podcasts = []

    for podcast_folder in sorted(os.listdir(data_dir)):
        podcast_path = os.path.join(data_dir, podcast_folder)
        if not os.path.isdir(podcast_path):
            continue  # skip files like feeds.json

        raw_folder = os.path.join(podcast_path, "raw")
        rss_path   = os.path.join(raw_folder, "rss.xml")

        if not os.path.exists(rss_path):
            continue

        # --- Parse RSS ---
        podcast_title = podcast_folder  # fallback
        guid_to_info = {}
        guid_order    = []

        try:
            tree    = ET.parse(rss_path)
            root    = tree.getroot()
            channel = root.find('channel')
            if channel is not None:
                title_el = channel.find('title')
                if title_el is not None and title_el.text:
                    podcast_title = title_el.text.strip()

                for item in channel.findall('item'):
                    guid_el     = item.find('guid')
                    ep_title_el = item.find('title')
                    pub_date_el = item.find('pubDate')
                    if guid_el is not None and ep_title_el is not None:
                        guid = guid_el.text.strip()
                        title = ep_title_el.text.strip()
                        pub_date = "Unknown Date"
                        if pub_date_el is not None and pub_date_el.text:
                            try:
                                dt = parsedate_to_datetime(pub_date_el.text.strip())
                                pub_date = dt.strftime("%Y-%m-%d")
                            except Exception:
                                pass
                        
                        guid_to_info[guid] = {
                            'title': title,
                            'pub_date': pub_date
                        }
                        guid_order.append(guid)
        except Exception as e:
            print(f"  Warning: could not parse RSS for '{podcast_folder}': {e}")

        # --- Match SRT + AD pairs ---
        episodes = []
        if os.path.exists(raw_folder):
            for fname in os.listdir(raw_folder):
                if not fname.endswith('.srt'):
                    continue
                guid     = fname[:-4]  # strip .srt
                srt_path = os.path.join(raw_folder, fname)
                ad_path  = os.path.join(raw_folder, guid + '.ad')

                if not os.path.exists(ad_path):
                    continue  # not yet processed

                info = guid_to_info.get(guid, {'title': f"Unknown episode ({guid[:8]}...)", 'pub_date': 'Unknown Date'})
                ep_title = info['title']
                pub_date = info['pub_date']
                stats    = _calc_episode_stats(srt_path, ad_path)
                rss_pos  = guid_order.index(guid) if guid in guid_order else 9999

                episodes.append({
                    'guid':    guid,
                    'title':   ep_title,
                    'pub_date': pub_date,
                    'stats':   stats,   # (total_secs, ad_secs, pct) or None
                    'rss_pos': rss_pos,
                })

        if not episodes:
            continue

        # Sort by published date descending (fallback to rss_pos if unknown)
        episodes.sort(key=lambda e: e['pub_date'], reverse=True)

        podcasts.append({
            'title':    podcast_title,
            'episodes': episodes,
            'latest_pub': episodes[0]['pub_date'] if episodes else 'Unknown Date'
        })

    # Sort podcasts by latest published episode descending, then alphabetically
    podcasts.sort(key=lambda p: p['title'].lower())
    podcasts.sort(key=lambda p: p['latest_pub'], reverse=True)

    # --- Build Markdown report ---
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Podcast Ad Statistics",
        f"_Generated: {now}_",
        "",
    ]

    total_eps     = 0
    total_podcasts = 0

    for podcast in podcasts:
        valid_stats = [e['stats'] for e in podcast['episodes'] if e['stats'] is not None]
        if valid_stats:
            total_podcast_secs = sum(s[0] for s in valid_stats)
            total_podcast_ad_secs = sum(s[1] for s in valid_stats)
            avg_pct = (total_podcast_ad_secs / total_podcast_secs) * 100 if total_podcast_secs > 0 else 0.0
            
            ad_m = int(round(total_podcast_ad_secs / 60))
            tot_m = int(round(total_podcast_secs / 60))
            avg_str = f"({ad_m}m/{tot_m}m) {avg_pct:.1f}%"
        else:
            avg_str = "N/A"

        lines.append("---")
        lines.append("")
        lines.append(f"## {podcast['title']}  _(avg: {avg_str})_")
        lines.append("")
        lines.append("| Broadcast Date | Episode | Ad % |")
        lines.append("|---|---|---:|")

        for ep in podcast['episodes']:
            if ep['stats'] is not None:
                total_secs, ad_secs, pct = ep['stats']
                ad_m = int(round(ad_secs / 60))
                tot_m = int(round(total_secs / 60))
                pct_str = f"({ad_m}m/{tot_m}m) {pct:.1f}%"
            else:
                pct_str = "—"
            # Escape any pipe characters in titles
            safe_title = ep['title'].replace('|', '\\|')
            lines.append(f"| {ep['pub_date']} | {safe_title} | {pct_str} |")

        lines.append("")
        total_eps      += len(podcast['episodes'])
        total_podcasts += 1

    report   = "\n".join(lines) + "\n"
    out_path = os.path.join(data_dir, "podcast_stats.md")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"Stats report written to: {out_path}")
    print(f"Covered {total_eps} episode(s) across {total_podcasts} podcast(s).")
