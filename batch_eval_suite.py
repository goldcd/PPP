import sys
import os
import time

sys.path.append('e:/projects/PPP')
from app.detect_adverts import start_ollama, detect_adverts, stop_ollama, parse_srt_blocks

TEST_EPISODES = [
    ("00890bf8-17ef-11f1-945a-a30fe2569c70.srt", "McDonald's + Octopus + Accenture"),
    ("013d87a2-2ddb-11f1-bfa6-67b3a0d22274.srt", "Octopus Hold Music Banter + Indeed"),
    ("03956556-47da-11f1-96ae-1314eccd0ce0.srt", "Lloyds + Drug Awareness + Big Arch"),
    ("04a69e1c-2136-11f1-81c3-730977a326a3.srt", "Bumble + Oscars Ad Discussion Guard"),
    ("0b52f52e-2e9e-11f1-aed1-7f26b09f1089.srt", "Octopus + McDonald's Big Arch + Tesco Mobile"),
]

def run_suite():
    raw_folder = "data/the-rest-is-entertainment/raw"
    start_ollama()
    
    results = {}
    for filename, description in TEST_EPISODES:
        print(f"\n========================================================")
        print(f"EVALUATING: {filename} ({description})")
        print(f"========================================================")
        
        t0 = time.time()
        detect_adverts(filename, raw_folder)
        elapsed = time.time() - t0
        
        ad_file = os.path.join(raw_folder, filename.replace(".srt", ".ad"))
        ad_blocks_count = 0
        if os.path.exists(ad_file):
            with open(ad_file, "r", encoding="utf-8") as f:
                raw_ad = f.read()
            ad_blocks = parse_srt_blocks(raw_ad.replace("\r\n", "\n").strip().split("\n\n"))
            ad_blocks_count = len(ad_blocks)
            
        results[filename] = {
            "description": description,
            "ad_blocks": ad_blocks_count,
            "elapsed_s": round(elapsed, 1)
        }
        
    stop_ollama()
    
    print("\n\n========================================================")
    print("BATCH EVALUATION SUITE SUMMARY")
    print("========================================================")
    for fn, r in results.items():
        print(f"{fn} ({r['description']}): {r['ad_blocks']} ad blocks flagged in {r['elapsed_s']}s")

if __name__ == "__main__":
    run_suite()
