#!/bin/bash

# Quick Docker Volume Browser
# Usage: ./browse-volume.sh <volume_name> [path]

if [ $# -eq 0 ]; then
    echo "Usage: $0 <volume_name> [path]"
    echo "Available volumes:"
    docker volume ls --format "table {{.Name}}\t{{.Driver}}"
    exit 1
fi

VOLUME_NAME=$1
PATH_IN_VOLUME=${2:-"/"}

echo "Browsing volume: $VOLUME_NAME"
echo "Path: $PATH_IN_VOLUME"
echo "=========================="

# Show tree structure if available, otherwise use ls
docker run --rm -v "$VOLUME_NAME:/data" alpine sh -c "
    if command -v tree >/dev/null 2>&1; then
        tree /data$PATH_IN_VOLUME
    else
        find /data$PATH_IN_VOLUME -type d -exec echo 'DIR: {}' \; -o -type f -exec echo 'FILE: {}' \; | sort
    fi
"