#!/usr/bin/env bash
set -euo pipefail

app_dir="${BOT_APP_DIR:-/opt/thinkorswim_bot/current}"
shared_dir="${BOT_SHARED_DIR:-/opt/thinkorswim_bot/shared}"
python_bin="${BOT_PYTHON_BIN:-$shared_dir/.venv/bin/python}"
stop_file="${STOP_SIGNAL_FILE:-$shared_dir/run/stop_signal.txt}"
no_trade_dates="${NO_TRADE_DATES_FILE:-$app_dir/config/no_trade_dates.txt}"

cd "$app_dir"

today="$(TZ=America/New_York date +%F)"
weekday="$(TZ=America/New_York date +%u)"

if (( weekday > 5 )); then
  echo "Skipping bot start on weekend date $today."
  exit 0
fi

if [[ -f "$no_trade_dates" ]] && grep -Eq "^[[:space:]]*$today([[:space:]]|$)" "$no_trade_dates"; then
  echo "Skipping bot start on configured no-trade date $today."
  exit 0
fi

mkdir -p "$shared_dir/logs" "$shared_dir/run"
rm -f "$stop_file"

if [[ -e "$app_dir/logs" && ! -L "$app_dir/logs" ]]; then
  mv "$app_dir/logs" "$shared_dir/logs/release-$(date -u +%Y%m%dT%H%M%SZ)"
fi
if [[ -L "$app_dir/logs" ]]; then
  rm "$app_dir/logs"
fi
ln -s "$shared_dir/logs" "$app_dir/logs"

export PYTHONUNBUFFERED=1
export PYTHONPATH="$app_dir${PYTHONPATH:+:$PYTHONPATH}"

exec "$python_bin" main.py
