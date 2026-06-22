#!/bin/bash

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    
    echo "Activating environment and installing requirements..."
    source .venv/bin/activate
    pip install torch faster-whisper requests tomli
else
    source .venv/bin/activate
fi
if [ ! -f "config.toml" ]; then
    echo "Creating config.toml from example..."
    cp config.toml.EXAMPLE config.toml
fi

python3 main.py
