#!/usr/bin/env bash
# Deploy the washing_machine custom component to a Home Assistant host over SSH.
#
# Usage:
#   HA_HOST=10.0.5.12 HA_SSH_USER=root HA_SSH_PASS=password ./scripts/deploy.sh
#
# Prereqs on local machine:
#   - sshpass (brew install hudochenkov/sshpass/sshpass  OR  apt-get install sshpass)
#   - OR: set up ssh key auth and omit HA_SSH_PASS
#
# What it does:
#   1. Rsync/scp the custom_components/washing_machine folder to /config/custom_components/
#   2. Call HA service homeassistant.reload_config_entry for the integration (no full restart)
#      Falls back to full restart if --restart flag is passed.
set -euo pipefail

HA_HOST="${HA_HOST:?HA_HOST env var required (e.g. 10.0.5.12)}"
HA_SSH_USER="${HA_SSH_USER:-root}"
HA_TOKEN="${HA_TOKEN:-}"
HA_URL="${HA_URL:-https://${HA_HOST}}"
RESTART=0

for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=1 ;;
    *) echo "Unknown flag: $arg"; exit 2 ;;
  esac
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SRC="${SCRIPT_DIR}/../custom_components/washing_machine"
[ -d "$SRC" ] || { echo "source not found: $SRC"; exit 2; }

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5)
if [ -n "${HA_SSH_PASS:-}" ]; then
  SSH="sshpass -p $HA_SSH_PASS ssh ${SSH_OPTS[*]}"
  SCP="sshpass -p $HA_SSH_PASS scp ${SSH_OPTS[*]}"
else
  SSH="ssh ${SSH_OPTS[*]}"
  SCP="scp ${SSH_OPTS[*]}"
fi

echo "==> copying to ${HA_SSH_USER}@${HA_HOST}:/config/custom_components/"
# Ensure target dir exists and clean old install (preserves storage file outside component dir)
$SSH "${HA_SSH_USER}@${HA_HOST}" "mkdir -p /config/custom_components && rm -rf /config/custom_components/washing_machine"
$SCP -r "$SRC" "${HA_SSH_USER}@${HA_HOST}:/config/custom_components/"
$SSH "${HA_SSH_USER}@${HA_HOST}" "rm -rf /config/custom_components/washing_machine/__pycache__ /config/custom_components/washing_machine/**/__pycache__" 2>/dev/null || true
echo "==> files deployed"

if [ "$RESTART" = "1" ]; then
  if [ -z "$HA_TOKEN" ]; then echo "ERR: HA_TOKEN required for --restart"; exit 2; fi
  echo "==> triggering HA core restart"
  curl -sk -X POST -H "Authorization: Bearer $HA_TOKEN" \
    "${HA_URL}/api/services/homeassistant/restart" -d '{}' >/dev/null
  echo "==> waiting for HA to come back"
  until curl -sk -H "Authorization: Bearer $HA_TOKEN" "${HA_URL}/api/" 2>/dev/null | grep -q "API running"; do sleep 5; done
  echo "==> HA up"
else
  echo "==> NOT restarting (use --restart to reload). For Python code changes HA needs a restart."
fi
