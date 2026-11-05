#!/usr/bin/env bash
#
# Hourly watchdog, run by salesforce-app-healthcheck.timer.
#
# Reachable  -> do nothing.
# Unreachable-> systemctl restart salesforce-app-restart.service
#
# Two probes, because "unreachable" has two different causes and only one of
# them is worth a restart on its own:
#
#   1. local  http://127.0.0.1:PORT/health  — is the backend process alive?
#   2. public https://<ngrok domain>/health — is the tunnel carrying traffic?
#
# A failure of either means the service is not doing its job, so either
# triggers a restart. Checking local FIRST means the log says which one broke,
# instead of blaming the tunnel for a dead backend.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.env"

SERVICE="salesforce-app-restart.service"
URL_FILE="${SCRIPT_DIR}/run/public_url.txt"
LOCAL_HEALTH="http://127.0.0.1:${PORT}${HEALTH_PATH}"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

restart_service() {
    log "restarting ${SERVICE} (reason: $*)"
    if systemctl restart "${SERVICE}"; then
        log "restart issued successfully"
    else
        log "ERROR: systemctl restart failed"
        exit 1
    fi
}

# ── probe 1: the backend itself ──────────────────────────────────────────────
if ! curl -fsS --max-time 10 "${LOCAL_HEALTH}" >/dev/null 2>&1; then
    restart_service "local ${LOCAL_HEALTH} did not respond"
    exit 0
fi
log "local OK   ${LOCAL_HEALTH}"

# ── probe 2: the public tunnel ───────────────────────────────────────────────
if [[ "${NGROK_ENABLED}" != "true" ]]; then
    log "ngrok disabled — nothing further to check"
    exit 0
fi

PUBLIC_URL=""
[[ -f "${URL_FILE}" ]] && PUBLIC_URL="$(cat "${URL_FILE}" 2>/dev/null)"
[[ -z "${PUBLIC_URL}" ]] && PUBLIC_URL="https://${NGROK_DOMAIN}"

# Retried: a single timeout over the public internet is not proof of an outage,
# and a needless restart drops in-flight work and re-warms the Whisper model.
for attempt in 1 2 3; do
    if curl -fsS --max-time 20 "${PUBLIC_URL}${HEALTH_PATH}" >/dev/null 2>&1; then
        log "public OK  ${PUBLIC_URL}${HEALTH_PATH}"
        exit 0
    fi
    log "public probe ${attempt}/3 failed"
    [[ ${attempt} -lt 3 ]] && sleep 10
done

restart_service "public ${PUBLIC_URL}${HEALTH_PATH} failed 3 probes"
