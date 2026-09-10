#!/bin/bash
set -euo pipefail

FRONTEND="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend/citadel-dashboard"
RUNTIME="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend/logs/supervisor"
LOCK="$RUNTIME/frontend.lock"
mkdir -p "$RUNTIME"
[ -f "$RUNTIME/frontend.stdout.log" ] && [ "$(stat -f %z "$RUNTIME/frontend.stdout.log")" -gt 10485760 ] && mv "$RUNTIME/frontend.stdout.log" "$RUNTIME/frontend.stdout.log.1"
if ! mkdir "$LOCK" 2>/dev/null; then
  owner="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then exit 0; fi
  rm -rf "$LOCK" && mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM
cd "$FRONTEND"
exec env PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  NEXT_PUBLIC_CITADEL_API_URL="http://127.0.0.1:8000" \
  NEXT_PUBLIC_CITADEL_DATA_MODE="rest" npm run start -- -p 3000
