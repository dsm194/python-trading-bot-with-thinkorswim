#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(git rev-parse --show-toplevel)"
cd "$repo_dir"

deploy_host="${BOT_DEPLOY_HOST:?Set BOT_DEPLOY_HOST, for example ubuntu@1.2.3.4}"
deploy_root="${BOT_DEPLOY_ROOT:-/opt/thinkorswim_bot}"
deploy_profile="${BOT_DEPLOY_PROFILE:-prod}"
restart_service="${BOT_DEPLOY_RESTART:-0}"
profile_path="config/env_profiles/.env.$deploy_profile"
service_name="thinkorswim-bot.service"

if [[ ! -f "$profile_path" ]]; then
  echo "ERROR: Unknown deploy profile '$deploy_profile': $profile_path" >&2
  exit 1
fi

if [[ "${BOT_DEPLOY_ALLOW_DIRTY:-0}" != "1" ]]; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: Commit or stash changes before deploying." >&2
    git status --short >&2
    exit 1
  fi
fi

commit="$(git rev-parse --short=12 HEAD)"
release_name="$(date -u +%Y%m%dT%H%M%SZ)-$commit"
archive_path="$(mktemp -t thinkorswim_bot_release.XXXXXX.tar.gz)"

cleanup() {
  rm -f "$archive_path"
}
trap cleanup EXIT

git archive --format=tar.gz --output="$archive_path" HEAD

echo "Deploying $commit to $deploy_host:$deploy_root/releases/$release_name"

ssh "$deploy_host" \
  "id orfa >/dev/null 2>&1 || sudo useradd --system --create-home --shell /usr/sbin/nologin orfa"
ssh "$deploy_host" \
  "sudo mkdir -p '$deploy_root/releases/$release_name' '$deploy_root/shared/logs' '$deploy_root/shared/run' '$deploy_root/shared/secrets' /opt/orfa_bot/shared/secrets /etc/thinkorswim_bot /etc/systemd/system/orfa-bot-live-paper.service.d"
scp "$archive_path" "$deploy_host:/tmp/thinkorswim_bot_release.tar.gz"
ssh "$deploy_host" \
  "sudo tar -xzf /tmp/thinkorswim_bot_release.tar.gz -C '$deploy_root/releases/$release_name' && rm -f /tmp/thinkorswim_bot_release.tar.gz"

ssh "$deploy_host" \
  "sudo chown -R orfa:orfa '$deploy_root/releases/$release_name' '$deploy_root/shared' /opt/orfa_bot/shared/secrets"
ssh "$deploy_host" "sudo -u orfa python3 -m venv '$deploy_root/shared/.venv'"
ssh "$deploy_host" \
  "sudo -u orfa '$deploy_root/shared/.venv/bin/python' -m pip install --upgrade pip"
ssh "$deploy_host" \
  "sudo -u orfa '$deploy_root/shared/.venv/bin/python' -m pip install -r '$deploy_root/releases/$release_name/requirements.txt'"

ssh "$deploy_host" \
  "sudo ln -sfn '$deploy_root/releases/$release_name' '$deploy_root/current'"
ssh "$deploy_host" \
  "sudo cp '$deploy_root/current/deploy/ubuntu/thinkorswim-bot.service' /etc/systemd/system/ && \
   sudo cp '$deploy_root/current/deploy/ubuntu/thinkorswim-bot-after-orfa.service' /etc/systemd/system/ && \
   sudo cp '$deploy_root/current/deploy/ubuntu/thinkorswim-bot-stop.service' /etc/systemd/system/ && \
   sudo cp '$deploy_root/current/deploy/ubuntu/thinkorswim-bot-stop.timer' /etc/systemd/system/ && \
   sudo cp '$deploy_root/current/deploy/ubuntu/logrotate.thinkorswim-bot' /etc/logrotate.d/thinkorswim-bot && \
   sudo cp '$deploy_root/current/deploy/ubuntu/orfa-bot-live-paper.service.d/thinkorswim-handoff.conf' /etc/systemd/system/orfa-bot-live-paper.service.d/"

scp "$profile_path" "$deploy_host:/tmp/thinkorswim_bot.env"
ssh "$deploy_host" \
  "sudo install -m 0640 -o root -g orfa /tmp/thinkorswim_bot.env /etc/thinkorswim_bot/thinkorswim_bot.env && rm -f /tmp/thinkorswim_bot.env"

if ! ssh "$deploy_host" "sudo test -f /etc/thinkorswim_bot/thinkorswim_bot.secrets.env"; then
  echo "WARNING: create /etc/thinkorswim_bot/thinkorswim_bot.secrets.env before starting."
fi
if ! ssh "$deploy_host" "sudo test -f /opt/orfa_bot/shared/secrets/schwab_token.json"; then
  echo "WARNING: shared Schwab token is missing; run scripts/refresh_and_sync_credentials.sh."
fi
if ! ssh "$deploy_host" "sudo test -f '$deploy_root/shared/secrets/gmail_token.json'"; then
  echo "WARNING: Gmail token is missing; run scripts/refresh_and_sync_credentials.sh."
fi

ssh "$deploy_host" \
  "sudo systemctl daemon-reload && sudo systemctl enable --now thinkorswim-bot-stop.timer"

if [[ "$restart_service" == "1" ]]; then
  ssh "$deploy_host" "sudo systemctl restart '$service_name'"
else
  echo "Release deployed without starting the bot."
fi

echo "Done."
