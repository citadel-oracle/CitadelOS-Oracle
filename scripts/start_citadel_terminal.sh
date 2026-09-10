#!/bin/bash
# scripts/start_citadel_terminal.sh
# Runs CITADEL on port 8000 from normal macOS Terminal after ensuring OpenAlgo is healthy.

set -euo pipefail

CITADEL_DIR="/Users/ayushmudgal/Developer/CitadelOS"
GATE_SCRIPT="${CITADEL_DIR}/scripts/start_citadel.sh"

echo "[CITADEL-START] Running secure startup checks and starting CITADEL..."
export OPENALGO_BASE_URL="http://127.0.0.1:5001/api/v1"

exec bash "${GATE_SCRIPT}"
