import sys
import os
import shutil
import importlib.util
import platform
import subprocess
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
        response = requests.get(url, timeout=1)
        return response.status_code == 200
    except requests.RequestException:
        return False

def install_python_package(package_name):
    """Install a Python package using pip."""
    print(f"Installing Python package '{package_name}'...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", package_name], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install {package_name} via pip: {e}")
        return False

def reinstall_pytorch_with_cuda():
    """Reinstall PyTorch with CUDA (GPU) support."""
    print("Reinstalling PyTorch with CUDA (GPU) support...")
    try:
        print("Uninstalling CPU-only PyTorch packages...")
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "torch", "torchvision", "torchaudio"], check=True)
        print("Installing CUDA-enabled PyTorch packages (this may take a few minutes)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu121"], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to reinstall PyTorch with CUDA: {e}")
        return False

def install_ffmpeg(system):
    """Install FFmpeg using the system's package manager."""
    print("Installing FFmpeg...")
    try:
        if system == "Windows":
            subprocess.run(["winget", "install", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements"], check=True)
            return True
        elif system == "Darwin":  # macOS
            subprocess.run(["brew", "install", "ffmpeg"], check=True)
            return True
        elif system == "Linux":
            if shutil.which("apt-get"):
                subprocess.run(["sudo", "apt-get", "update"], check=True)
                subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"], check=True)
                return True
            else:
                print("Linux detected, but 'apt-get' not found. Please install FFmpeg using your system package manager.")
                return False
    except subprocess.CalledProcessError as e:
        print(f"Failed to install FFmpeg: {e}")
        return False
    except FileNotFoundError:
        print("Required package manager (winget/brew) was not found on the system path.")
        return False

def install_ollama(system):
    """Install Ollama using the system's package manager or install script."""
    print("Installing Ollama...")
    try:
        if system == "Windows":
            subprocess.run(["winget", "install", "Ollama.Ollama", "--accept-source-agreements", "--accept-package-agreements"], check=True)
            return True
        elif system == "Darwin":  # macOS
            subprocess.run(["brew", "install", "ollama"], check=True)
            return True
        elif system == "Linux":
            print("Downloading and running Ollama installer script...")
            subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True)
            return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install Ollama: {e}")
        return False
    except FileNotFoundError:
        print("Required installer utility was not found on the system path.")
        return False

def check_prerequisites():
    """Verify system and environment requirements, and offer auto-installation."""
    print("Checking system prerequisites...")
    system = platform.system()
    
    missing_whisper = not (is_python_package_installed("whisper") or is_command_installed("whisper"))
    missing_ffmpeg = not is_command_installed("ffmpeg")
    missing_ollama = not is_command_installed("ollama")
    
    # Check for PyTorch CUDA support if Whisper is installed, using a subprocess to avoid file locking
    missing_cuda_support = False
    is_gpu_enabled = False
    if not missing_whisper:
        if is_command_installed("nvidia-smi"):
            try:
                res = subprocess.run(
                    [sys.executable, "-c", "import torch; print(torch.cuda.is_available())"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                cuda_available = res.stdout.strip() == "True"
                if not cuda_available:
                    missing_cuda_support = True
                else:
                    is_gpu_enabled = True
            except Exception:
                pass

    if not (missing_whisper or missing_ffmpeg or missing_ollama or missing_cuda_support):
        gpu_status = " (GPU enabled)" if is_gpu_enabled else ""
        if not is_ollama_service_running() and not missing_ollama:
            print(f"[OK] Whisper: Found{gpu_status}")
            print("[OK] FFmpeg: Found")
            print("[WARN] Ollama: CLI found, but the background service is not running. (Run: ollama serve)")
        else:
            print(f"[OK] Whisper: Found{gpu_status}")
            print("[OK] FFmpeg: Found")
            print("[OK] Ollama: Found and running")
            print("[SUCCESS] All prerequisites met!\n")
        return

    # Print status of what's missing or needs update
    print("\n--- Missing Prerequisites ---")
    if missing_whisper:
        print("[FAIL] Whisper (Python package or CLI tool) is missing.")
    elif missing_cuda_support:
        print("[FAIL] PyTorch is CPU-only, but an NVIDIA GPU is available (GPU support is highly recommended).")
    else:
        print("[OK] Whisper: Found")

    if missing_ffmpeg:
        print("[FAIL] FFmpeg (System audio encoder/decoder) is missing.")
    else:
        print("[OK] FFmpeg: Found")

    if missing_ollama:
        print("[FAIL] Ollama (Local LLM CLI tool) is missing.")
    else:
        print("[OK] Ollama: Found")
    print("-----------------------------\n")

    # Ask the user if they want to attempt auto-installation
    choice = input("Would you like to attempt auto-installing/updating the missing dependencies? (y/n): ").strip().lower()
    if choice not in ('y', 'yes'):
        print("[FAIL] Prerequisites not met. Exiting application.")
        input("Press Enter to exit...")
        sys.exit(1)

    print(f"\nDetecting Operating System: {system}")
    installation_success = True

    if missing_whisper:
        success = install_python_package("openai-whisper")
        if sys.version_info < (3, 11):
            install_python_package("tomli")
        if not success:
            installation_success = False
        else:
            # If we just installed whisper, check if we need to install CUDA support now (via subprocess)
            if is_command_installed("nvidia-smi"):
                try:
                    res = subprocess.run(
                        [sys.executable, "-c", "import torch; print(torch.cuda.is_available())"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if res.stdout.strip() != "True":
                        missing_cuda_support = True
                except Exception:
                    pass

    if missing_cuda_support:
        success = reinstall_pytorch_with_cuda()
        if not success:
            installation_success = False

    if missing_ffmpeg:
        success = install_ffmpeg(system)
        if not success:
            installation_success = False

    if missing_ollama:
        success = install_ollama(system)
        if not success:
            installation_success = False

    if installation_success:
        print("\n[SUCCESS] Auto-installation completed successfully!")
        print("💡 NOTE: If PyTorch CUDA support or system packages (like FFmpeg/Ollama) were installed, you MUST restart your terminal/IDE for changes to take effect.")
        input("\nPress Enter to exit and restart your program...")
        sys.exit(0)
    else:
        print("\n[FAIL] Auto-installation failed for one or more dependencies.")
        print("Please install the remaining tools manually.")
        input("\nPress Enter to exit...")
        sys.exit(1)
