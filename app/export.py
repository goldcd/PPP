##Very simple function to put everything we've generated somewhere else
##i.e. I'm dumping this to a webserver I've got mounted
import os
import shutil
import sys
import json
import xml.etree.ElementTree as ET

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml

def export():
    print("Exporting podcasts...")

    if not os.path.exists("config.toml"):
        print("config.toml not found. Skipping export.")
        return

    with open("config.toml", "rb") as f:
        config = toml.load(f)

    export_config = config.get("export", {})
    export_activated = export_config.get("export_activated", False)
    export_path = export_config.get("export_path", "").strip()
    base_url = export_config.get("base_url", "").strip()
    if base_url.endswith("/"):
        base_url = base_url[:-1]

    if not export_activated:
        print("Export is deactivated in config. Skipping.")
        return

    if not export_path:
        print("Export path is empty in config. Skipping.")
        return

    os.makedirs(export_path, exist_ok=True)

    ## Read feeds to know what we have
    if not os.path.exists("data/feeds.json"):
        print("No feeds.json found. Skipping export.")
        return

    with open("data/feeds.json", "r", encoding="utf-8") as f:
        feeds = json.load(f)

    feed_links = []

    for feed in feeds:
        feed_id = str(feed.get("id"))
        feed_title = feed.get("title", f"Podcast {feed_id}")
        
        source_dir = os.path.join("data", feed_id, "output")
        target_dir = os.path.join(export_path, feed_id)
        
        if not os.path.exists(source_dir):
            continue
            
        os.makedirs(target_dir, exist_ok=True)
        
        ## Track if we actually copied anything to link it
        has_files = False
        
        for filename in os.listdir(source_dir):
            source_file = os.path.join(source_dir, filename)
            target_file = os.path.join(target_dir, filename)
            
            if not os.path.isfile(source_file):
                continue
                
            has_files = True
                
            if filename.endswith(".mp3"):
                if not os.path.exists(target_file):
                    print(f"Exporting MP3: {feed_title} -> {filename}")
                    shutil.copy2(source_file, target_file)
            elif filename == "rss.xml":
                print(f"Exporting RSS: {feed_title} -> {filename}")
                if base_url:
                    try:
                        tree = ET.parse(source_file)
                        root = tree.getroot()
                        channel = root.find("channel")
                        if channel is not None:
                            for item in channel.findall("item"):
                                enclosure = item.find("enclosure")
                                if enclosure is not None:
                                    url = enclosure.get("url", "")
                                    if url and not url.startswith("http"):
                                        enclosure.set("url", f"{base_url}/{feed_id}/{url}")
                        tree.write(target_file, encoding='utf-8', xml_declaration=True)
                    except Exception as e:
                        print(f"Failed to rewrite RSS {source_file}: {e}")
                        shutil.copy2(source_file, target_file)
                else:
                    shutil.copy2(source_file, target_file)
            else:
                ## For any other files, just copy if they don't exist
                if not os.path.exists(target_file):
                    shutil.copy2(source_file, target_file)
                    
        if has_files:
            feed_links.append((feed_id, feed_title))
            
    ## Now generate the index.html at the root of the export path
    html_content = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "    <title>My Cleaned Podcasts</title>",
        "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "    <style>",
        "        body { font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; line-height: 1.6; background-color: #f8f9fa; }",
        "        h1 { color: #333; text-align: center; margin-bottom: 30px; font-weight: 800; letter-spacing: -1px; }",
        "        p.subtitle { text-align: center; color: #666; margin-bottom: 40px; }",
        "        ul { list-style-type: none; padding: 0; }",
        "        li { margin-bottom: 15px; padding: 20px; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); transition: transform 0.2s; border: 1px solid #eaeaea; }",
        "        li:hover { transform: translateY(-2px); box-shadow: 0 6px 12px rgba(0,0,0,0.08); }",
        "        a { text-decoration: none; color: #0066cc; font-weight: bold; font-size: 1.2em; display: block; margin-bottom: 12px; }",
        "        a:hover { color: #004499; }",
        "        .button-group { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 15px; }",
        "        button.subscribe { color: white; border: none; padding: 8px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85em; font-weight: bold; flex: 1; min-width: 140px; display: flex; align-items: center; justify-content: center; gap: 6px; }",
        "        button.apple { background: #b14fff; }",
        "        button.apple:hover { background: #963cdb; }",
        "        button.pktc { background: #f22d3d; }",
        "        button.pktc:hover { background: #c22431; }",
        "        button.overcast { background: #fc7e0f; }",
        "        button.overcast:hover { background: #e06d0b; }",
        "        button.castro { background: #00b265; }",
        "        button.castro:hover { background: #009955; }",
        "        button.addict { background: #f4842b; }",
        "        button.addict:hover { background: #d97323; }",
        "        p.desc { font-size: 0.9em; color: #888; margin-top: 15px; margin-bottom: 0; text-transform: uppercase; letter-spacing: 0.5px; }",
        "    </style>",
        "    <script>",
        "        function subscribe(feedPath, type) {",
        "            var absoluteUrl = new URL(feedPath, window.location.href).href;",
        "            // Bypasses aggressive backend caching (like Pocket Casts)",
        "            absoluteUrl += '?nocache=' + Date.now();",
        "            var podcastUrl;",
        "            var feedNoHttp = absoluteUrl.replace(/^https?:\\/\\//i, '');",
        "            if (type === 'pktc') {",
        "                podcastUrl = 'pktc://subscribe/' + feedNoHttp;",
        "            } else if (type === 'overcast') {",
        "                podcastUrl = 'overcast://' + feedNoHttp;",
        "            } else if (type === 'castro') {",
        "                podcastUrl = 'castro://subscribe/' + feedNoHttp;",
        "            } else if (type === 'podcastaddict') {",
        "                podcastUrl = 'podcastaddict://' + feedNoHttp;",
        "            } else {",
        "                podcastUrl = 'podcast://' + feedNoHttp;",
        "            }",
        "            window.location.href = podcastUrl;",
        "        }",
        "    </script>",
        "</head>",
        "<body>",
        "    <h1>PPP</h1>",
        "    <p class=\"subtitle\">Click a button to open the feed directly in your podcast app.</p>",
        "    <ul>"
    ]

    for feed_id, title in feed_links:
        html_content.append(f"        <li>")
        html_content.append(f"            <a href=\"{feed_id}/rss.xml\">{title}</a>")
        html_content.append(f"            <div class=\"button-group\">")
        html_content.append(f"                <button class=\"subscribe apple\" onclick=\"subscribe('{feed_id}/rss.xml', 'podcast')\">Apple</button>")
        html_content.append(f"                <button class=\"subscribe pktc\" onclick=\"subscribe('{feed_id}/rss.xml', 'pktc')\">Pocket Casts</button>")
        html_content.append(f"                <button class=\"subscribe overcast\" onclick=\"subscribe('{feed_id}/rss.xml', 'overcast')\">Overcast</button>")
        html_content.append(f"                <button class=\"subscribe castro\" onclick=\"subscribe('{feed_id}/rss.xml', 'castro')\">Castro</button>")
        html_content.append(f"                <button class=\"subscribe addict\" onclick=\"subscribe('{feed_id}/rss.xml', 'podcastaddict')\">Podcast Addict</button>")
        html_content.append(f"            </div>")
        html_content.append(f"            <p class=\"desc\">Feed ID: {feed_id}</p>")
        html_content.append(f"        </li>")
        
    if not feed_links:
        html_content.append("        <li style=\"text-align:center; color:#999;\">No podcasts exported yet.</li>")
        
    html_content.extend([
        "    </ul>",
        "</body>",
        "</html>"
    ])
    
    html_path = os.path.join(export_path, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_content))
        
    print(f"Generated web index at: {html_path}")
    print("Export complete!")
