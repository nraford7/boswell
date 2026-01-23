#!/bin/bash
# Boswell entrypoint - runs web or worker based on SERVICE_TYPE env var

set -e

echo "=== BOSWELL ENTRYPOINT ==="
echo "SERVICE_TYPE=${SERVICE_TYPE:-web}"
echo "=========================="

case "${SERVICE_TYPE:-web}" in
  worker)
    echo "Starting WORKER mode..."
    exec ./scripts/start_worker.sh
    ;;
  *)
    echo "Starting WEB mode..."
    exec ./scripts/start_web.sh
    ;;
esac
