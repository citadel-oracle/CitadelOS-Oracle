#!/bin/bash
# scripts/start_openalgo_terminal.sh
# Runs OpenAlgo on port 5001 in Analyzer Mode from normal macOS Terminal.

set -euo pipefail

OPENALGO_DIR="/Users/ayushmudgal/openalgo"
VENV_PYTHON="${OPENALGO_DIR}/.venv/bin/python3"

echo "[OPENALGO-START] Navigating to ${OPENALGO_DIR}..."
cd "${OPENALGO_DIR}"

echo "[OPENALGO-START] Starting OpenAlgo on port 5001 in Analyzer Mode..."
export FLASK_PORT=5001
export HOST_SERVER='http://127.0.0.1:5001'

exec "${VENV_PYTHON}" app.py
