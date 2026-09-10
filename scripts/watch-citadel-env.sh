#!/bin/bash
set -euo pipefail

SOURCE="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend"
ENV_FILE="$SOURCE/.env"
STATE="$SOURCE/logs/supervisor/env.signature"
LOG="$SOURCE/logs/supervisor/env-watcher.log"
PYTHON="/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python"
mkdir -p "$(dirname "$STATE")"

signature() { stat -f '%m:%z' "$ENV_FILE" 2>/dev/null || printf missing; }
previous="$(cat "$STATE" 2>/dev/null || signature)"
printf %s "$previous" > "$STATE"

while sleep 15; do
  current="$(signature)"
  [ "$current" = "$previous" ] && continue
  sleep 15
  current="$(signature)"
  [ "$current" = "$previous" ] && continue
  if (
    set -a; source "$ENV_FILE"; set +a
    cd "$SOURCE"
    "$PYTHON" - <<'PY'
from src.broker.dhan_client import DhanClient
client = DhanClient()
profile = client.get_profile()
quote = client.get_quote("IDX_I", "13")
raise SystemExit(0 if isinstance(profile, dict) and not profile.get("error") and quote.get("ltp") else 1)
PY
  ); then
    printf '%s validated environment change; restarting backend once\n' "$(date -u +%FT%TZ)" >> "$LOG"
    launchctl kickstart -k "gui/$(id -u)/com.citadelos.backend"
    previous="$current"
    printf %s "$previous" > "$STATE"
  else
    printf '%s environment validation failed; restart suppressed\n' "$(date -u +%FT%TZ)" >> "$LOG"
    previous="$current"
    printf %s "$previous" > "$STATE"
  fi
done
