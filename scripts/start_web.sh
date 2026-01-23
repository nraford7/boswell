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

set -e

echo "Starting Boswell web server..."

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the web server
echo "Starting Uvicorn on port ${PORT:-8000}..."
exec uvicorn boswell.server.main:app --host 0.0.0.0 --port ${PORT:-8000}
