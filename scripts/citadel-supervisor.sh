#!/bin/bash
set -euo pipefail

SOURCE="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS=(com.citadelos.backend com.citadelos.frontend com.citadelos.env-watcher)

bootstrap_service() {
  local label="$1"
  local plist="$AGENTS/$label.plist"
  local attempt
  for attempt in 1 2 3 4 5; do
    if launchctl bootstrap "$DOMAIN" "$plist" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "unable to bootstrap $label after bounded retry" >&2
  return 1
}

install_services() {
  mkdir -p "$AGENTS" /Users/ayushmudgal/Developer/CitadelOS/logs/supervisor
  if [ -f "$AGENTS/com.citadelos.launcher.plist" ]; then
    launchctl bootout "$DOMAIN/com.citadelos.launcher" >/dev/null 2>&1 || true
    mv "$AGENTS/com.citadelos.launcher.plist" "$AGENTS/com.citadelos.launcher.plist.legacy-disabled"
  fi
  chmod +x "$SOURCE/scripts/run-citadel-backend.sh" "$SOURCE/scripts/run-citadel-frontend.sh" "$SOURCE/scripts/watch-citadel-env.sh"
  for label in "${LABELS[@]}"; do
    cp "$SOURCE/ops/launchd/$label.plist" "$AGENTS/$label.plist"
    launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
    bootstrap_service "$label"
  done
}

uninstall_services() {
  for label in "${LABELS[@]}"; do
    launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
    rm -f "$AGENTS/$label.plist"
  done
  if [ -f "$AGENTS/com.citadelos.launcher.plist.legacy-disabled" ]; then
    mv "$AGENTS/com.citadelos.launcher.plist.legacy-disabled" "$AGENTS/com.citadelos.launcher.plist"
  fi
}

status_services() {
  for label in "${LABELS[@]}"; do
    launchctl print "$DOMAIN/$label" 2>/dev/null | awk -v label="$label" '/state =|pid =/{printf "%s %s\n",label,$0}' || printf '%s NOT_INSTALLED\n' "$label"
  done
  curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:8000/v2/dashboard?symbol=NIFTY && echo 'backend HTTP 200' || echo 'backend unavailable'
  curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:3000 && echo 'frontend HTTP 200' || echo 'frontend unavailable'
}

case "${1:-status}" in
  install) install_services ;;
  uninstall) uninstall_services ;;
  restart) for label in "${LABELS[@]}"; do launchctl kickstart -k "$DOMAIN/$label"; done ;;
  status) status_services ;;
  *) echo "usage: $0 {install|uninstall|restart|status}" >&2; exit 64 ;;
esac
