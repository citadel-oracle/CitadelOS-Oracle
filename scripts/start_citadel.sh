#!/bin/bash
# scripts/start_citadel.sh
#
# CITADEL startup gate: verifies OpenAlgo is healthy and in Analyzer Mode
# BEFORE starting uvicorn. Prevents BROKER_DISCONNECTED kill-switch arm due
# to startup race conditions or port-5000 false positives from macOS services.
#
# Identity check: the response body MUST contain '"mode":"analyze"' to pass.
# A plain HTTP 200 or 403 from another process (e.g. macOS ControlCenter) is
# explicitly rejected.

set -euo pipefail

OPENALGO_URL="${OPENALGO_BASE_URL:-http://127.0.0.1:5001/api/v1}"
CITADEL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="${CITADEL_DIR}/.venv-kronos-alpha/bin/python"

# ── Configuration ─────────────────────────────────────────────────────────────
GRACE_SECONDS=30        # total time to wait for OpenAlgo to become ready
POLL_INTERVAL=2         # poll every N seconds
TIMEOUT_PER_CALL=4      # per-request curl timeout

log() { echo "[CITADEL-GATE $(date '+%H:%M:%S')] $*"; }

# ── Load .env to get API key ──────────────────────────────────────────────────
ENV_FILE="${CITADEL_DIR}/.env"
OPENALGO_API_KEY=""
if [ -f "$ENV_FILE" ]; then
    OPENALGO_API_KEY=$(grep -E '^OPENALGO_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d "'" | tr -d '"' | xargs)
fi

if [ -z "$OPENALGO_API_KEY" ]; then
    log "ERROR: OPENALGO_API_KEY not found in ${ENV_FILE}. Aborting."
    exit 1
fi

# ── OpenAlgo identity + readiness gate ───────────────────────────────────────
log "Waiting for OpenAlgo to be ready at ${OPENALGO_URL}/analyzer ..."
ELAPSED=0
READY=0

while [ $ELAPSED -lt $GRACE_SECONDS ]; do
    # POST to /analyzer and capture raw body
    BODY=$(curl -s --max-time "$TIMEOUT_PER_CALL" \
        -X POST "${OPENALGO_URL}/analyzer" \
        -H "Content-Type: application/json" \
        -d "{\"apikey\": \"${OPENALGO_API_KEY}\"}" 2>/dev/null || true)

    # Identity check: body MUST contain the OpenAlgo analyzer schema fields.
    # A 403 from macOS AirTunes or any other non-OpenAlgo service on port 5000
    # produces an empty body or HTML — neither will pass this grep.
    if echo "$BODY" | grep -q '"mode"' && echo "$BODY" | grep -q '"analyze_mode"'; then
        # Schema present — now confirm Analyzer Mode
        if echo "$BODY" | grep -q '"mode":"analyze"' || echo "$BODY" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    data = d.get('data', d)
    ok = data.get('analyze_mode') is True and data.get('mode') == 'analyze'
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
" <<< "$BODY" 2>/dev/null; then
            log "OpenAlgo identity confirmed. Mode: analyze. Analyzer gate PASSED."
            READY=1
            break
        else
            log "OpenAlgo responded but mode is NOT analyze. Body: ${BODY:0:200}"
            log "HARD STOP: refusing to start CITADEL with OpenAlgo in live mode."
            exit 2
        fi
    else
        log "Port 5000 not yet answering with OpenAlgo schema (elapsed ${ELAPSED}s / ${GRACE_SECONDS}s). Retrying..."
    fi

    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ $READY -eq 0 ]; then
    log "ERROR: OpenAlgo did not become ready within ${GRACE_SECONDS}s. Aborting CITADEL startup."
    log "CITADEL will NOT start. Kill switch will NOT be armed for this startup failure."
    exit 1
fi

# ── Start CITADEL uvicorn ─────────────────────────────────────────────────────
log "OpenAlgo gate passed. Starting CITADEL backend..."
cd "$CITADEL_DIR"
exec "${VENV_PYTHON}" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
