#!/bin/bash
# Boswell Jobs Worker Startup Script
#
# This script starts the jobs worker process that:
# - Polls the job_queue table for pending jobs
# - Processes background tasks (analysis generation, email, question generation)
# - Retries failed jobs up to max_attempts
#
# Environment variables:
#   DATABASE_URL - PostgreSQL connection string (required)
#   CLAUDE_API_KEY - Anthropic Claude API key (required for analysis)
#   RESEND_API_KEY - Resend API key (required for email)

set -e

echo "Starting Boswell jobs worker..."

# Start the jobs worker
exec python -m boswell.server.jobs_main
