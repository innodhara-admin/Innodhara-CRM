#!/usr/bin/env bash
#
# Voice mode (Jarvis) — the two deployment steps that need root.
#
#   sudo bash /home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/restart_script/deploy_voice_mode.sh
#
# 1. nginx: pass WebSocket upgrades to the backend, so
#    wss://<public host>/api/v1/assistant/voice reaches uvicorn.
#    - adds /etc/nginx/conf.d/websocket-upgrade.conf (the $connection_upgrade map)
#    - adds two proxy_set_header lines to `location /` in salesforce-public
#    - backs the site file up first, and restores everything if `nginx -t` fails
# 2. restarts salesforce-app-restart.service (backend + ngrok) and waits for
#    /health, so the new code — voice endpoints, the client agent, the
#    assistant_pending_actions table — is loaded.
#
# Safe to run twice: each nginx change is skipped when already present.

set -euo pipefail

SITE_LINK=/etc/nginx/sites-enabled/salesforce-public
SITE=$(readlink -f "$SITE_LINK")
MAP_CONF=/etc/nginx/conf.d/websocket-upgrade.conf
SERVICE=salesforce-app-restart.service
HEALTH=http://127.0.0.1:8010/health
STAMP=$(date +%Y%m%d%H%M%S)

log() { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*"; }

[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }
[[ -f "$SITE" ]] || { echo "No nginx site at $SITE"; exit 1; }

# ── 1. nginx ─────────────────────────────────────────────────────────────────
BACKUP="$SITE.bak-voice-$STAMP"
cp -a "$SITE" "$BACKUP"
log "backed up $SITE -> $BACKUP"

MAP_ADDED=false
if grep -rqs 'connection_upgrade' /etc/nginx/nginx.conf /etc/nginx/conf.d/; then
    log "a \$connection_upgrade map already exists; not adding another"
else
    cat > "$MAP_CONF" <<'EOF'
# WebSocket upgrade support — added for Jarvis voice mode (WS /api/v1/assistant/voice).
# "upgrade" when the client asks for it; a plain keep-alive-free request otherwise.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
EOF
    MAP_ADDED=true
    log "wrote $MAP_CONF"
fi

if grep -q 'proxy_set_header Upgrade' "$SITE"; then
    log "salesforce-public already passes Upgrade headers; unchanged"
else
    python3 - "$SITE" <<'EOF'
import sys
path = sys.argv[1]
text = open(path).read()
anchor = "        proxy_pass http://127.0.0.1:8010;\n        proxy_http_version 1.1;\n"
if text.count(anchor) != 1:
    sys.exit("could not find the backend location block to edit")
insert = (
    "\n"
    "        # WebSocket upgrade for Jarvis voice mode (WS /api/v1/assistant/voice).\n"
    "        proxy_set_header Upgrade    $http_upgrade;\n"
    "        proxy_set_header Connection $connection_upgrade;\n"
)
open(path, "w").write(text.replace(anchor, anchor + insert))
EOF
    log "added Upgrade/Connection headers to location /"
fi

if ! nginx -t; then
    log "nginx -t FAILED — restoring the previous configuration"
    cp -a "$BACKUP" "$SITE"
    $MAP_ADDED && rm -f "$MAP_CONF"
    nginx -t && log "restored; nginx unchanged" || log "restore check failed — inspect nginx now"
    exit 1
fi
systemctl reload nginx
log "nginx reloaded"

# ── 2. backend restart ───────────────────────────────────────────────────────
log "restarting $SERVICE"
systemctl restart "$SERVICE"
for i in $(seq 1 90); do
    if curl -fsS --max-time 5 "$HEALTH" >/dev/null 2>&1; then
        log "backend healthy after ~$((i * 2))s: $(curl -fsS "$HEALTH")"
        systemctl --no-pager --lines=0 status "$SERVICE" | head -4
        exit 0
    fi
    sleep 2
done
log "backend did not answer $HEALTH within 180s — check: journalctl -u $SERVICE -n 100"
exit 1
