#!/bin/bash
#
# IBKR Dashboard Launcher
#
# Automatically finds available ports and starts both
# the FastAPI backend and Vite React frontend.
#
# Usage:
#   bash dashboard/start.sh
#   bash dashboard/start.sh --backend-port 9000
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─── Parse Args ──────────────────────────────────────────────
PREFERRED_BACKEND_PORT=8888
PREFERRED_FRONTEND_PORT=5173

while [[ $# -gt 0 ]]; do
  case $1 in
    --backend-port) PREFERRED_BACKEND_PORT=$2; shift 2;;
    --frontend-port) PREFERRED_FRONTEND_PORT=$2; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

# ─── Find Available Port ─────────────────────────────────────
find_available_port() {
  local port=$1
  local max_attempts=20
  local attempt=0

  while [ $attempt -lt $max_attempts ]; do
    if ! lsof -i ":$port" >/dev/null 2>&1; then
      echo $port
      return 0
    fi
    port=$((port + 1))
    attempt=$((attempt + 1))
  done

  echo "ERROR: Could not find available port starting from $1" >&2
  exit 1
}

BACKEND_PORT=$(find_available_port $PREFERRED_BACKEND_PORT)
FRONTEND_PORT=$(find_available_port $PREFERRED_FRONTEND_PORT)

# Ensure frontend port is different from backend
if [ "$FRONTEND_PORT" -eq "$BACKEND_PORT" ]; then
  FRONTEND_PORT=$(find_available_port $((BACKEND_PORT + 1)))
fi

echo "============================================================"
echo "  IBKR Dashboard"
echo "============================================================"
echo "  Backend port:  $BACKEND_PORT"
echo "  Frontend port: $FRONTEND_PORT"
echo "============================================================"

# ─── Install Dependencies ────────────────────────────────────
echo ""
echo "Checking dependencies..."

# Python deps
pip install -q fastapi uvicorn websockets python-dotenv 2>/dev/null || true

# Frontend deps
if [ ! -d "$SCRIPT_DIR/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  cd "$SCRIPT_DIR/frontend"
  npm install --silent
  cd "$PROJECT_ROOT"
fi

# ─── Start Backend ───────────────────────────────────────────
echo ""
echo "Starting backend on port $BACKEND_PORT..."
cd "$PROJECT_ROOT"
DASHBOARD_PORT=$BACKEND_PORT python "$SCRIPT_DIR/server.py" &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 30); do
  if curl -s "http://localhost:$BACKEND_PORT/api/status" >/dev/null 2>&1; then
    echo "Backend ready."
    break
  fi
  sleep 1
done

# ─── Start Frontend ──────────────────────────────────────────
echo "Starting frontend on port $FRONTEND_PORT..."
cd "$SCRIPT_DIR/frontend"
VITE_API_PORT=$BACKEND_PORT npx vite --port $FRONTEND_PORT --host &
FRONTEND_PID=$!
cd "$PROJECT_ROOT"

# ─── Print Access Info ───────────────────────────────────────
sleep 2
echo ""
echo "============================================================"
echo "  Dashboard is running!"
echo ""
echo "  Open:     http://localhost:$FRONTEND_PORT"
echo "  API:      http://localhost:$BACKEND_PORT/api/status"
echo ""
echo "  Press Ctrl+C to stop both servers"
echo "============================================================"

# ─── Cleanup on Exit ─────────────────────────────────────────
cleanup() {
  echo ""
  echo "Shutting down..."
  kill $BACKEND_PID 2>/dev/null
  kill $FRONTEND_PID 2>/dev/null
  wait $BACKEND_PID 2>/dev/null
  wait $FRONTEND_PID 2>/dev/null
  echo "Stopped."
}

trap cleanup INT TERM

# Wait for either process to exit
wait
