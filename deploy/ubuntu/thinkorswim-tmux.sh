#!/usr/bin/env bash
set -euo pipefail

session_name="${THINKORSWIM_TMUX_SESSION:-thinkorswim}"
logs_dir="${THINKORSWIM_LOGS_DIR:-/opt/thinkorswim_bot/shared/logs}"

if tmux has-session -t "$session_name" 2>/dev/null; then
  exec tmux attach-session -t "$session_name"
fi

tmux new-session -d -s "$session_name" -n monitor
tmux send-keys -t "$session_name:monitor.0" \
  "sudo journalctl -u thinkorswim-bot.service -f" C-m

tmux split-window -v -t "$session_name:monitor.0"
tmux send-keys -t "$session_name:monitor.1" \
  "less +F '$logs_dir/info.log' '$logs_dir/warning.log' '$logs_dir/error.log'" C-m

tmux select-layout -t "$session_name:monitor" even-vertical
tmux select-pane -t "$session_name:monitor.1"

exec tmux attach-session -t "$session_name"
