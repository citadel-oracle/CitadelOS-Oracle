#!/bin/bash
set -e

PLIST_DIR="$HOME/Library/LaunchAgents"
BACKEND_PLIST="$PLIST_DIR/com.citadel.backend.plist"
FRONTEND_PLIST="$PLIST_DIR/com.citadel.frontend.plist"
LOG_DIR="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend/logs"

mkdir -p "$LOG_DIR"

echo "[CITADEL OS] Loading LaunchAgents..."
launchctl load "$BACKEND_PLIST" 2>/dev/null || true
launchctl load "$FRONTEND_PLIST" 2>/dev/null || true

sleep 2
exec "/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend/status-citadel.sh"
