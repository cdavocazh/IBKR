#!/bin/bash
# IB Gateway Health Monitor
#
# Checks if the API is authenticated. If dead, restarts the container.
# With ExistingSessionDetectedAction=secondary, if another session (e.g. mobile)
# is active, the gateway will silently yield — no 2FA sent, no disruption.
# Only when no other session exists does it proceed to 2FA.
#
# Usage: ./ib_health_monitor.sh          (check + auto-restart)
#        ./ib_health_monitor.sh --check  (check only, no restart)

set -euo pipefail

COMPOSE_FILE="/root/ib-gateway/docker-compose.yml"
LOG_FILE="/var/log/ib-health-monitor.log"
LOCKFILE="/tmp/ib-gateway-restart.lock"

# Telegram notifications — hardcoded to authorized chat only
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID="1130846055"
if [[ -f /root/Finl_Agent_CC/.env ]]; then
    TELEGRAM_BOT_TOKEN=$(grep -oP '(?<=^TELEGRAM_BOT_TOKEN=).*' /root/Finl_Agent_CC/.env | tr -d "\"' ")
fi

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

send_telegram() {
    if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="$TELEGRAM_CHAT_ID" \
            -d text="$1" \
            -d parse_mode="Markdown" \
            -d disable_web_page_preview=true > /dev/null 2>&1 || true
    fi
}

# Test if the API is truly alive by attempting an ib_async connection
test_api_alive() {
    /root/IBKR/venv/bin/python3 -c "
import sys
from ib_async import IB
ib = IB()
try:
    ib.connect('127.0.0.1', 4001, clientId=97, readonly=True, timeout=8)
    accts = ib.managedAccounts()
    ib.disconnect()
    if accts:
        print('OK')
        sys.exit(0)
    else:
        print('NO_ACCOUNTS')
        sys.exit(1)
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" 2>/dev/null
}

# Check if container is running
container_running() {
    docker compose -f "$COMPOSE_FILE" ps --format json 2>/dev/null | grep -q '"running"'
}

# ── Main ──
CHECK_ONLY=false
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=true

# Step 1: Is the container running?
if ! container_running; then
    log "WARN: IB Gateway container is NOT running"
    if $CHECK_ONLY; then
        echo "CONTAINER_DOWN"
        exit 1
    fi
    log "Starting IB Gateway container..."
    send_telegram "IB Gateway container was down. Starting it — approve 2FA if prompted."
    docker compose -f "$COMPOSE_FILE" up -d
    sleep 30
    exit 0
fi

# Step 2: Is the API actually authenticated?
API_RESULT=$(test_api_alive 2>&1) || true

if [[ "$API_RESULT" == "OK" ]]; then
    log "OK: IB Gateway API is alive and authenticated"
    echo "OK"
    exit 0
fi

log "DEAD: IB Gateway API not responding ($API_RESULT)"

if $CHECK_ONLY; then
    echo "API_DEAD: $API_RESULT"
    exit 1
fi

# Step 3: Prevent concurrent restarts
if [[ -f "$LOCKFILE" ]]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCKFILE" 2>/dev/null || echo 0) ))
    if (( LOCK_AGE < 300 )); then
        log "SKIP: Restart already in progress (lock age: ${LOCK_AGE}s)"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
touch "$LOCKFILE"

# Step 4: Restart the container
# With ExistingSessionDetectedAction=secondary:
#   - If another session is active (mobile/desktop) → gateway silently yields, no 2FA sent
#   - If no other session → proceeds to 2FA → user approves on phone
log "Restarting IB Gateway container..."
docker compose -f "$COMPOSE_FILE" restart

# Step 5: Wait and check what happened
log "Waiting for login attempt (up to 60s)..."
sleep 30

# Check IBC logs for "Existing session detected" (means another login is active)
EXISTING_SESSION=$(docker logs ib-gateway-ib-gateway-1 2>&1 | tail -30 | grep -c "Existing session detected" || true)

if (( EXISTING_SESSION > 0 )); then
    # Another session is active — gateway yielded silently, no 2FA was sent
    log "Another IBKR session is active — gateway yielded. Will retry next cycle."
    send_telegram "IB Gateway: another session is active (mobile/desktop). VPS yielded. Will auto-retry in 15 min."
    rm -f "$LOCKFILE"
    exit 0
fi

# No other session — gateway should be logging in with 2FA
send_telegram "IB Gateway restarting — approve 2FA on IBKR Mobile."

# Wait for re-auth (up to 90s from restart)
for i in $(seq 1 12); do
    sleep 5
    API_CHECK=$(test_api_alive 2>&1) || true
    if [[ "$API_CHECK" == "OK" ]]; then
        log "SUCCESS: IB Gateway re-authenticated after $((30 + i * 5))s"
        send_telegram "IB Gateway re-authenticated successfully."
        rm -f "$LOCKFILE"
        exit 0
    fi
done

log "TIMEOUT: IB Gateway did not re-authenticate within 90s."
send_telegram "IB Gateway restart timed out. 2FA may not have been approved. Send /relogin_ibkr to retry."
rm -f "$LOCKFILE"
exit 1
