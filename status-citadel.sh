#!/bin/bash

LOG_DIR="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend/logs"

echo "=========================================================="
echo "CITADEL OS — PERSISTENT SERVICE STATUS"
echo "=========================================================="

echo ""
echo "--- 1. PROCESS LISTENING AUDIT ---"
lsof -nP -iTCP:3000 -sTCP:LISTEN || echo "Port 3000: NOT LISTENING"
lsof -nP -iTCP:8000 -sTCP:LISTEN || echo "Port 8000: NOT LISTENING"

echo ""
echo "--- 2. SERVICE HEALTH VERIFICATION (curl) ---"
echo -n "Frontend (http://127.0.0.1:3000): "
curl -I -s --max-time 3 http://127.0.0.1:3000 | head -n 1 || echo "UNREACHABLE"

echo -n "Backend  (http://127.0.0.1:8000/v1/argus/oi?symbol=NIFTY): "
curl -I -s --max-time 3 "http://127.0.0.1:8000/v1/argus/oi?symbol=NIFTY" | head -n 1 || echo "UNREACHABLE"

echo ""
echo "--- 3. LOG FILE LOCATIONS ---"
echo "Backend stdout:  $LOG_DIR/backend.stdout.log"
echo "Backend stderr:  $LOG_DIR/backend.stderr.log"
echo "Frontend stdout: $LOG_DIR/frontend.stdout.log"
echo "Frontend stderr: $LOG_DIR/frontend.stderr.log"
echo "=========================================================="
