# Ubuntu Deployment

## Layout

- Committed releases: `/opt/thinkorswim_bot/releases/<timestamp>-<commit>`
- Active release: `/opt/thinkorswim_bot/current`
- Shared runtime files: `/opt/thinkorswim_bot/shared`
- Non-secret production config: `/etc/thinkorswim_bot/thinkorswim_bot.env`
- Production secrets: `/etc/thinkorswim_bot/thinkorswim_bot.secrets.env`
- Shared Schwab token: `/opt/orfa_bot/shared/secrets/schwab_token.json`
- Shared logs: `/opt/thinkorswim_bot/shared/logs`

The deployer archives committed `HEAD`, refuses dirty deployments by default,
installs dependencies into a shared virtualenv, updates the `current` symlink,
and installs the systemd units and logrotate policy.

## One-Time Setup

Bootstrap the VM before the first deploy. From the workstation:

```bash
ssh ubuntu@YOUR_VM_HOST 'bash -s' < deploy/ubuntu/bootstrap_ubuntu_vm.sh
```

Because ORFA is already deployed under the same `orfa` service account, this
bootstrap is idempotent: it installs Python prerequisites and creates this
bot's directories. It does not replace ORFA code, configuration, service, or
token.

Then create this bot's secret file on the VM:

```bash
ssh ubuntu@YOUR_VM_HOST
sudo cp deploy/ubuntu/thinkorswim_bot.secrets.env.example \
  /etc/thinkorswim_bot/thinkorswim_bot.secrets.env
sudo chown root:orfa /etc/thinkorswim_bot/thinkorswim_bot.secrets.env
sudo chmod 0640 /etc/thinkorswim_bot/thinkorswim_bot.secrets.env
sudoedit /etc/thinkorswim_bot/thinkorswim_bot.secrets.env
```

The template path in the example above exists after a release is deployed. For
the first deployment, create the file directly with `sudoedit` and use the
variable names from `config.secrets.env.example`.

The secret names for this older bot are `API_KEY`, `APP_SECRET`, and
`CALLBACK_URL`. ORFA uses differently prefixed names, so keep both secret env
files even though they contain the same Schwab application credentials.

## Deploy

From the workstation:

```bash
BOT_DEPLOY_HOST=ubuntu@YOUR_VM_HOST bash deploy/ubuntu/deploy.sh
```

The production profile is the default. To deploy the dev profile:

```bash
BOT_DEPLOY_HOST=ubuntu@YOUR_VM_HOST \
BOT_DEPLOY_PROFILE=dev \
bash deploy/ubuntu/deploy.sh
```

The deployer does not start the trading bot unless
`BOT_DEPLOY_RESTART=1`. Normally ORFA's successful completion triggers the
five-minute delayed handoff.

## Credential Refresh

Create local `config.secrets.env` from `config.secrets.env.example`, then run:

```bash
BOT_DEPLOY_HOST=ubuntu@YOUR_VM_HOST \
bash scripts/refresh_and_sync_credentials.sh
```

This command:

1. Performs fresh interactive Gmail and Schwab authorization.
2. Updates `~/.config/orfa_bot/schwab_token.json` locally.
3. Installs the Schwab token in ORFA's shared VM secrets directory.
4. Installs the Gmail token in this bot's shared VM secrets directory.

If `BOT_DEPLOY_HOST` is omitted, only local credentials are refreshed and the
ORFA local token is updated. Remote synchronization refuses to replace tokens
while either ORFA or this bot is active.

## Service Handoff

The deploy installs:

- `thinkorswim-bot.service`: the trading bot itself.
- `thinkorswim-bot-after-orfa.service`: a five-minute delay followed by start.
- `thinkorswim-bot-stop.timer`: stops the bot at 4:00 PM Eastern on weekdays.
- An ORFA service drop-in with
  `OnSuccess=thinkorswim-bot-after-orfa.service`.

The bot service also checks that ORFA is inactive before starting. The launcher
skips weekends and dates in `config/no_trade_dates.txt`. The ORFA drop-in also
declares a conflict with this bot, so starting the next ORFA session first
stops this bot and waits for its graceful shutdown. Together, the start guard
and ORFA conflict enforce a single Schwab session.

Inspect the chain:

```bash
systemctl cat orfa-bot-live-paper.service
systemctl status thinkorswim-bot-after-orfa.service
systemctl status thinkorswim-bot.service
systemctl status thinkorswim-bot-stop.timer
systemctl list-timers 'thinkorswim-bot*'
journalctl -u thinkorswim-bot.service -f
```

Direct service control:

```bash
sudo systemctl start thinkorswim-bot.service
sudo systemctl stop thinkorswim-bot.service
```

After verifying the ORFA handoff and the 4:00 PM Eastern stop timer for a full
session, remove the old cron entries that start or stop this bot:

```bash
crontab -l
crontab -e
```

Do not enable `thinkorswim-bot.service` at boot. It is started by the ORFA
handoff or manually by an operator.

## Live Trading Interlock

Production deploys with live opening orders disabled:

```dotenv
LIVE_OPENING_ORDERS_ENABLED=False
MAX_LIVE_SESSION_OPEN_NOTIONAL=1000
```

Mongo's `Account_Position=Live` is not sufficient to open a new live position.
The environment switch must also be exactly `True`, and cumulative opening
notional during that bot process must remain within the configured ceiling.
Live closing orders remain permitted while opening orders are disarmed.

For an initial observation session, leave the switch disabled and inspect the
logs for blocked opening orders. Arm it only by editing
`config/env_profiles/.env.prod`, committing the deliberate change, and
redeploying.

## Logs

The application writes severity-specific logs under:

```text
/opt/thinkorswim_bot/shared/logs/
```

The deploy installs `/etc/logrotate.d/thinkorswim-bot`. Logs rotate daily,
retain 30 rotations, compress older files, and use `copytruncate` so the
running bot can continue writing without reopening file handles.

Validate the policy without rotating:

```bash
sudo logrotate -d /etc/logrotate.d/thinkorswim-bot
```

## Updating Holidays

Maintain `config/no_trade_dates.txt` in source control and deploy the change.
The launcher reads the active release's copy before every start.
