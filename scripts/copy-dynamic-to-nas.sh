#!/bin/bash

# Copy local Traefik dynamic config files to NAS volume
set -e

# Configuration
LOCAL_DIR="./traefik-dynamic"
CONTAINER="traefik"
NAS_PATH="/etc/traefik/dynamic"  # Path inside container that maps to NAS

echo "Copying Traefik dynamic configs to NAS..."

# Check if local directory exists
if [ ! -d "$LOCAL_DIR" ]; then
    echo "Error: Local directory $LOCAL_DIR not found"
    exit 1
fi

# Check if Traefik container is running
if ! docker ps | grep -q "$CONTAINER"; then
    echo "Error: Traefik container not running"
    echo "Start it with: docker-compose -f compose.production-nas.yml up -d"
    exit 1
fi

# Create temp directory in container
docker exec "$CONTAINER" mkdir -p /tmp/dynamic-configs

# Copy files to temp location first
for file in $LOCAL_DIR/*.yml $LOCAL_DIR/*.yaml; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        echo "Copying $filename..."
        docker cp "$file" "$CONTAINER:/tmp/dynamic-configs/$filename"
    fi
done

# Move files to NAS mount with proper permissions
docker exec "$CONTAINER" sh -c "cp -f /tmp/dynamic-configs/* $NAS_PATH/ 2>/dev/null || true"
docker exec "$CONTAINER" rm -rf /tmp/dynamic-configs

# Show what's now on the NAS
echo -e "\nFiles now on NAS:"
docker exec "$CONTAINER" ls -la "$NAS_PATH"

echo -e "\nDone! Traefik will auto-reload (file watcher enabled)"