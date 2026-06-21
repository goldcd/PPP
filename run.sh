#!/bin/bash

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    
    echo "Activating environment and installing requirements..."
    source .venv/bin/activate
    pip install openai-whisper requests tomli
else
    source .venv/bin/activate
fi
python3 main.py
