#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  jobs -p | xargs kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$PROJECT_DIR/backend" && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
(cd "$PROJECT_DIR/frontend" && npm run dev -- --host 127.0.0.1) &

wait
