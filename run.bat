@echo off

:: Create a VENV for this - it was getting messy. And seemingly this is best practice.. 
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    
    echo Activating environment and installing requirements...
    call .venv\Scripts\activate.bat
    pip install torch faster-whisper requests tomli
) else (
    call .venv\Scripts\activate.bat
)

:: Now we can start
python main.py