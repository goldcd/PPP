##This was just written by AI as beyond my paygrade! It seems to work, but I don't understand it!


import shutil
import importlib.util
import requests

def is_command_installed(name):
    """Check if a CLI command is available on the system PATH."""
    return shutil.which(name) is not None

def is_python_package_installed(name):
    """Check if a Python library is installed in the current environment."""
    return importlib.util.find_spec(name) is not None

def is_ollama_service_running(url="http://localhost:11434"):
    """Check if the local Ollama background server is responding."""
    try:
        # Ollama server responds with "Ollama is running" on '/'
        response = requests.get(url, timeout=1)
        return response.status_code == 200
    except requests.RequestException:
        return False

def check_prerequisites():
    """Verify system and environment requirements, and display warnings."""
    print("Checking system prerequisites...")
    all_passed = True

    # 1. Check Whisper (Python library or CLI command)
    has_whisper_lib = is_python_package_installed("whisper")
    has_whisper_cli = is_command_installed("whisper")
    
    if not (has_whisper_lib or has_whisper_cli):
        print("❌ Whisper: Not found. (Install with: pip install openai-whisper)")
        all_passed = False
    else:
        status = []
        if has_whisper_lib: status.append("Python library")
        if has_whisper_cli: status.append("CLI tool")
        print(f"✅ Whisper: Found ({', '.join(status)})")

    # 2. Check Ollama
    if not is_command_installed("ollama"):
        print("❌ Ollama: CLI tool not found. Please install it from https://ollama.com")
        all_passed = False
    else:
        if is_ollama_service_running():
            print("✅ Ollama: Found and running")
        else:
            print("⚠️  Ollama: CLI found, but the background service is not running. (Run: ollama serve)")
            # We don't mark this as a hard fail since they might start it later, 
            # but it is a good warning to display.

    if all_passed:
        print("🎉 All prerequisites met!\n")
    else:
        print("⚠️  Warning: Some prerequisites are missing. Features may crash if run.\n")
        input("Press Enter to ignore and continue to the menu...")
