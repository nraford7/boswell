#!/bin/bash
# Boswell entrypoint - runs web or worker based on SERVICE_TYPE env var

set -e

case "${SERVICE_TYPE:-web}" in
  worker)
    exec ./scripts/start_worker.sh
    ;;
  *)
    exec ./scripts/start_web.sh
    ;;
esac
