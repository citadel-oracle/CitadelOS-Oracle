#!/bin/bash
set -e

DIR="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend"

echo "[CITADEL OS] Restarting Citadel OS persistent services..."
"$DIR/stop-citadel.sh"
sleep 2
"$DIR/start-citadel.sh"
