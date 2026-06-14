#!/bin/bash

cd "$(dirname "$0")"

# Define paths
STOP_FILE="tmp/stop_signal.txt"
BOT_SCRIPT="main.py"

# Make sure tmp folder exists
mkdir -p tmp

echo "🛑 Placing stop signal at $STOP_FILE..."
touch "$STOP_FILE"

# Wait up to 10 seconds for clean shutdown
for i in {1..10}; do
    sleep 1
    if ! pgrep -f "$BOT_SCRIPT" > /dev/null; then
        echo "✅ Bot exited gracefully after $i seconds."
        exit 0
    fi
done

# If still running, force kill
echo "⚠️ Bot still running. Sending pkill..."
pkill -f "$BOT_SCRIPT"

# Confirm shutdown
if pgrep -f "$BOT_SCRIPT" > /dev/null; then
    echo "❌ Bot still running after pkill. Manual intervention may be needed."
else
    echo "✅ Bot was forcefully stopped with pkill."
fi

