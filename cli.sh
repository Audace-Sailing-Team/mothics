!/bin/bash

# Ensure tmux is installed
if ! command -v tmux &> /dev/null; then
    echo "tmux not found! Please install it."
    exit 1
fi

# Check if a tmux session named 'mothics' is already running
if tmux has-session -t mothics 2>/dev/null; then
    echo "tmux session 'mothics' already running."
    exit 0
fi

# Start a new tmux session and run the CLI inside the virtual environment
tmux new-session -d -s mothics "bash -c 'source /root/central-unit/.venv/bin/activate && python cli.py start live && exec bash'"


