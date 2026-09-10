#!/bin/bash
set -euo pipefail

SOURCE="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend"
ENV_FILE="$SOURCE/.env"
PYTHON="/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python"
RUNTIME="$SOURCE/logs/supervisor"
LOCK="$RUNTIME/backend.lock"
LOG="$RUNTIME/backend.log"

mkdir -p "$RUNTIME"
[ -f "$LOG" ] && [ "$(stat -f %z "$LOG")" -gt 10485760 ] && mv "$LOG" "$LOG.1"
if ! mkdir "$LOCK" 2>/dev/null; then
  owner="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then exit 0; fi
  rm -rf "$LOCK" && mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM

[ -f "$ENV_FILE" ] || { echo "canonical environment unavailable" >&2; exit 64; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[ -n "${DHAN_ACCESS_TOKEN:-}" ] || { echo "DHAN_ACCESS_TOKEN missing" >&2; exit 65; }

fingerprint="$(printf %s "$DHAN_ACCESS_TOKEN" | shasum -a 256 | cut -c1-12)"
printf '%s env_source=%s token_length=%s token_sha256_prefix=%s\n' "$(date -u +%FT%TZ)" "$ENV_FILE" "${#DHAN_ACCESS_TOKEN}" "$fingerprint" >> "$LOG"

cd "$SOURCE"
exec env HF_HUB_OFFLINE=1 \
  CITADEL_ENV_SOURCE="$ENV_FILE" \
  CITADEL_PAPER_STATE_PATH="$SOURCE/logs/paper_state.json" \
  CITADEL_PERSONAL_ORACLE_LEDGER_PATH="$SOURCE/logs/personal_oracle_rc2.json" \
  CITADEL_STRATEGY_LAB_ROOT="$SOURCE/logs/strategy_lab" \
  CITADEL_PERSONAL_ORACLE_MIN_EXIT_AT="2026-07-16T14:35:00+00:00" \
  "$PYTHON" -m uvicorn --app-dir "$SOURCE" app.main:app --host 127.0.0.1 --port 8000
