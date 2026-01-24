#!/bin/bash
set -e

echo "Building room-ui..."

cd "$(dirname "$0")/../room-ui"

# Install dependencies
npm ci

# Build
npm run build

# Copy to static folder
cp -r dist/* ../src/boswell/server/static/room-ui/

echo "room-ui built and copied to static folder"
