#!/bin/bash

# Move to the directory where the script is located
cd "$(dirname "$0")" || { echo "Failed to change directory"; exit 1; }

echo "Starting Front Camera Application..."
source venv/bin/activate
python3 main.py

exit_code=$?

if [[ $exit_code -ne 0 ]]; then
    echo "==========================================" >&2
    echo "Application crashed or exited with error code: $exit_code" >&2
    echo "This might be due to missing dependencies, camera issues, or code errors." >&2
    echo "==========================================" >&2
    echo "Press ENTER to close this window..."
    read -r
fi