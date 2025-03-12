#!/bin/bash

# Ensure tmux is installed
if ! command -v tmux &> /dev/null; then
    echo "tmux not found! Please install it."
    exit 1
fi

# Define user-specific paths
USER_HOME=$(eval echo ~"$USER")  # Dynamically get the home directory
VENV_PATH="$USER_HOME/mothics/.venv/bin/activate"
CLI_PATH="$USER_HOME/mothics/cli.py"

# Check if a tmux session named 'mothics' is already running
if tmux has-session -t mothics 2>/dev/null; then
    echo "tmux session 'mothics' already running."
    exit 0
fi

# Start a new tmux session and run the CLI inside the virtual environment
tmux new-session -d -s mothics "bash -c 'source $VENV_PATH && python $CLI_PATH start live && exec bash'"
