import requests
import json
import sys

sys_msg = "You are a bot. Output JSON."
user_msg = "Hello."

print("Sending request...")
try:
    r = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen3:14b",
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            "stream": True,
            "think": True,
            "options": {
                "temperature": 0.0,
                "num_ctx": 8192,
                "stop": ["</s>", "<|im_end|>", "<|endoftext|>"]
            }
        },
        stream=True,
        timeout=180,
    )
    print("Response status:", r.status_code)
    for line in r.iter_lines():
        if line:
            chunk = json.loads(line)
            print(chunk.get("message", {}).get("content", ""), end="", flush=True)
            if chunk.get("done"):
                break
    print("\nDone.")
except Exception as e:
    print(f"Error: {e}")
