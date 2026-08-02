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
`BOT_DEPLOY_RESTART=1`. Normally the weekday 12:35 ET start timer launches the
bot independently of ORFA's process lifecycle.

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

## Service Schedule

The deploy installs:

- `thinkorswim-bot.service`: the trading bot itself.
- `thinkorswim-bot-start.timer`: starts the bot at 12:35 PM Eastern on weekdays.
- `thinkorswim-bot-stop.timer`: stops the bot at 4:00 PM Eastern on weekdays.

The launcher skips weekends and dates in `config/no_trade_dates.txt`. ORFA may
remain active after its 12:30 ET production entry lock to consume streaming bars
for shadow strategies. Thinkorswim has streaming quotes disabled in production,
so both processes can run side-by-side without competing for a Schwab streaming
subscription. Deployment removes the former ORFA `OnSuccess` drop-in and delayed
handoff service.

Inspect the chain:

```bash
systemctl cat orfa-bot-live-paper.service
systemctl status thinkorswim-bot.service
systemctl status thinkorswim-bot-start.timer
systemctl status thinkorswim-bot-stop.timer
systemctl list-timers 'thinkorswim-bot*'
journalctl -u thinkorswim-bot.service -f
```

Direct service control:

```bash
sudo systemctl start thinkorswim-bot.service
sudo systemctl stop thinkorswim-bot.service
```

After verifying the 12:35 PM start and 4:00 PM Eastern stop timers for a full
session, remove the old cron entries that start or stop this bot:

```bash
crontab -l
crontab -e
```

Do not enable `thinkorswim-bot.service` at boot. It is started by its timer or
manually by an operator.

## Live Trading Interlock

Production deploys with live opening orders disabled:

```dotenv
LIVE_ORDER_SUBMISSION_ENABLED=False
LIVE_OPENING_ORDERS_ENABLED=False
MAX_LIVE_SESSION_OPEN_NOTIONAL=1000
```

Mongo's `Account_Position=Live` is not sufficient to open a new live position.
With `LIVE_ORDER_SUBMISSION_ENABLED=False`, no live opening or closing order is
sent to Schwab. After that master switch is enabled,
`LIVE_OPENING_ORDERS_ENABLED` must also be exactly `True` for new positions,
and cumulative opening notional during that bot process must remain within the
configured ceiling. This permits a later exits-only mode by enabling the master
switch while leaving opening orders disarmed.

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

Production disables duplicate console logging with `LOG_TO_CONSOLE=False`, so
`journalctl -u thinkorswim-bot.service` should mainly show systemd lifecycle
messages. Tail the shared log files for application behavior:

```bash
less +F \
  /opt/thinkorswim_bot/shared/logs/info.log \
  /opt/thinkorswim_bot/shared/logs/warning.log \
  /opt/thinkorswim_bot/shared/logs/error.log
```

The deploy also installs an operator tmux helper:

```bash
thinkorswim-tmux
```

It attaches to an existing `thinkorswim` tmux session or creates one with two
vertical panes: `journalctl -u thinkorswim-bot.service -f` on top and the
`less +F` shared-log view on the bottom.

Validate the policy without rotating:

```bash
sudo logrotate -d /etc/logrotate.d/thinkorswim-bot
```

## Updating Holidays

Maintain `config/no_trade_dates.txt` in source control and deploy the change.
The launcher reads the active release's copy before every start.
