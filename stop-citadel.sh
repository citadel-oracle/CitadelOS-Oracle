#!/bin/bash

PLIST_DIR="$HOME/Library/LaunchAgents"
BACKEND_PLIST="$PLIST_DIR/com.citadel.backend.plist"
FRONTEND_PLIST="$PLIST_DIR/com.citadel.frontend.plist"

echo "[CITADEL OS] Unloading LaunchAgents..."
launchctl unload "$FRONTEND_PLIST" 2>/dev/null || true
launchctl unload "$BACKEND_PLIST" 2>/dev/null || true

pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true

lsof -tiTCP:3000 | xargs kill -9 2>/dev/null || true
lsof -tiTCP:8000 | xargs kill -9 2>/dev/null || true

echo "[CITADEL OS] Citadel OS services stopped."
