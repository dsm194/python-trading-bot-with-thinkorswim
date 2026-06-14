#!/usr/bin/env bash
set -euo pipefail

echo "sync_bot_to_vm.sh now uses the immutable release deployer."
exec "$(dirname "$0")/deploy/ubuntu/deploy.sh" "$@"
