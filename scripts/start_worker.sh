#!/bin/bash
# Boswell Voice Worker Startup Script
#
# This script starts the voice worker process that:
# - Polls for guests with active interviews
# - Runs Pipecat voice pipelines for each interview
# - Saves transcripts and updates guest status
#
# Environment variables:
#   DATABASE_URL - PostgreSQL connection string (required)
#   DAILY_API_KEY - Daily.co API key (required)
#   DEEPGRAM_API_KEY - Deepgram API key (required)
#   ELEVENLABS_API_KEY - ElevenLabs API key (required)
#   CLAUDE_API_KEY - Anthropic Claude API key (required)

set -e

echo "Starting Boswell voice worker..."

# Start the voice worker
exec python -m boswell.server.worker
