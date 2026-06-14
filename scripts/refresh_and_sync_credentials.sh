#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(git rev-parse --show-toplevel)"
cd "$repo_dir"

python_bin="${BOT_LOCAL_PYTHON_BIN:-$repo_dir/.venv/bin/python}"
schwab_token="${SCHWAB_TOKEN_PATH:-$repo_dir/tmp/token.json}"
gmail_token="${GMAIL_TOKEN_PATH:-$repo_dir/gmail/creds/token.json}"
orfa_local_token="${ORFA_LOCAL_SCHWAB_TOKEN_PATH:-$HOME/.config/orfa_bot/schwab_token.json}"
deploy_host="${BOT_DEPLOY_HOST:-}"
remote_schwab_token="${ORFA_REMOTE_SCHWAB_TOKEN_PATH:-/opt/orfa_bot/shared/secrets/schwab_token.json}"
remote_gmail_token="${BOT_REMOTE_GMAIL_TOKEN_PATH:-/opt/thinkorswim_bot/shared/secrets/gmail_token.json}"

SCHWAB_TOKEN_PATH="$schwab_token" \
GMAIL_TOKEN_PATH="$gmail_token" \
"$python_bin" scripts/refresh_credentials.py --force

mkdir -p "$(dirname "$orfa_local_token")"
install -m 0600 "$schwab_token" "$orfa_local_token"
echo "Updated ORFA local Schwab token: $orfa_local_token"

if [[ -z "$deploy_host" ]]; then
  echo "BOT_DEPLOY_HOST is not set; refreshed local credentials only."
  exit 0
fi

if ssh "$deploy_host" \
  "systemctl is-active --quiet orfa-bot-live-paper.service || systemctl is-active --quiet thinkorswim-bot.service"; then
  echo "ERROR: A Schwab-using service is active on $deploy_host." >&2
  echo "Stop ORFA and the Thinkorswim bot before installing refreshed credentials." >&2
  exit 1
fi

scp "$schwab_token" "$deploy_host:/tmp/schwab_token.json"
scp "$gmail_token" "$deploy_host:/tmp/gmail_token.json"
ssh "$deploy_host" \
  "sudo install -m 0660 -o orfa -g orfa /tmp/schwab_token.json '$remote_schwab_token' && \
   sudo install -m 0600 -o orfa -g orfa /tmp/gmail_token.json '$remote_gmail_token' && \
   rm -f /tmp/schwab_token.json /tmp/gmail_token.json"

echo "Installed refreshed Schwab and Gmail tokens on $deploy_host."
