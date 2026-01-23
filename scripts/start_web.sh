#!/bin/bash
# Boswell Web Server Startup Script
#
# This script:
# 1. Runs database migrations (Alembic)
# 2. Starts the FastAPI server with Uvicorn
#
# Environment variables:
#   PORT - Server port (default: 8000)
#   DATABASE_URL - PostgreSQL connection string (required)
#   SERVICE_TYPE - If "worker", redirects to start_worker.sh

set -e

# Check if we should run as worker instead
if [ "${SERVICE_TYPE}" = "worker" ]; then
    echo "SERVICE_TYPE=worker detected, redirecting to worker..."
    exec "$(dirname "$0")/start_worker.sh"
fi

echo "Starting Boswell web server..."

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the web server
echo "Starting Uvicorn on port ${PORT:-8000}..."
exec uvicorn boswell.server.main:app --host 0.0.0.0 --port ${PORT:-8000}
