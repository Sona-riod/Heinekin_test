#!/bin/bash
# start_app.sh

# 1. Move to the project directory
cd "$(dirname "$0")"

# 2. Ensure application has X server access
export DISPLAY=:0

# 3. ACTIVATE VIRTUAL ENVIRONMENT (Crucial Step)
# This handles the "ModuleNotFoundError" issues
if [[ -d "venv" ]]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
elif [[ -d "../venv" ]]; then
    echo "Activating virtual environment (parent dir)..."
    source ../venv/bin/activate
else
    echo "WARNING: No 'venv' found. Using system python."
fi

# 4. Run the application
echo "Launching Top Camera System..."
python3 main.py

# 5. Prevent window from closing instantly on error
if [[ $? -ne 0 ]]; then
    echo "------------------------------------------------" >&2
    echo "ERROR: Application exited with a non-zero code." >&2
    echo "Check the detailed logs above." >&2
    echo "------------------------------------------------" >&2
    read -p "Press Enter to exit..."
fi