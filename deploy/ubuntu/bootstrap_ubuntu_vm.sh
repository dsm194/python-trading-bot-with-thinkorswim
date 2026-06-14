#!/usr/bin/env bash
set -euo pipefail

app_user="${BOT_SERVICE_USER:-orfa}"
app_root="${BOT_DEPLOY_ROOT:-/opt/thinkorswim_bot}"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip logrotate

if ! id "$app_user" >/dev/null 2>&1; then
  sudo useradd --system --create-home --shell /usr/sbin/nologin "$app_user"
fi

sudo mkdir -p \
  "$app_root/releases" \
  "$app_root/shared/logs" \
  "$app_root/shared/run" \
  "$app_root/shared/secrets" \
  /opt/orfa_bot/shared/secrets \
  /etc/thinkorswim_bot

sudo chown -R "$app_user:$app_user" "$app_root" /opt/orfa_bot/shared/secrets
sudo chown root:"$app_user" /etc/thinkorswim_bot
sudo chmod 0750 /etc/thinkorswim_bot

echo "Bootstrap complete."
echo "Create /etc/thinkorswim_bot/thinkorswim_bot.secrets.env, then deploy."
