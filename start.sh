#!/bin/bash

# Always start in the script's own directory
cd "$(dirname "$0")"

today=$(date +%F)
schedule_file="./schedule.txt"

if grep -Fxq "$today" "$schedule_file"; then
  echo "🛑 Market closed today ($today) — skipping bot start."
  exit 0
fi

echo "✅ Market open ($today) — starting bot..."

source venv/bin/activate

echo "⏳ Launching bot with nohup..."
nohup python main.py > /dev/null 2>&1 &

PID=$!
sleep 1

if ps -p $PID > /dev/null; then
  echo "✅ Bot launched in background (PID: $PID)"
else
  echo "❌ Bot exited immediately — check internal logs or nohup.out"
fi
