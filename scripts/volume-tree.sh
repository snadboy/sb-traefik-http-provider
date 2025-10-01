#!/bin/bash

# Docker Volume Tree Viewer
# Usage: ./volume-tree.sh <volume_name> [max_depth]

VOLUME_NAME=${1:-"nas-data"}
MAX_DEPTH=${2:-""}

if [ ! -z "$MAX_DEPTH" ]; then
    DEPTH_OPTION="-maxdepth $MAX_DEPTH"
else
    DEPTH_OPTION=""
fi

echo "=== Directory Tree for Volume: $VOLUME_NAME ==="
echo ""

# Method 1: Try tree command first
echo "Using tree command:"
docker run --rm -v "$VOLUME_NAME:/data" alpine sh -c "
    apk add --no-cache tree >/dev/null 2>&1
    if [ \$? -eq 0 ]; then
        tree /data
    else
        echo 'Tree command not available, using alternative method...'
        find /data $DEPTH_OPTION -type d | sed -e 's/[^-][^\/]*\//  /g' -e 's/^  //' -e 's/-/|/'
        echo ''
        echo 'Files:'
        find /data $DEPTH_OPTION -type f | sed 's|^/data/||' | sort
    fi
"

echo ""
echo "=== Summary ==="
docker run --rm -v "$VOLUME_NAME:/data" alpine sh -c "
    echo \"Directories: \$(find /data -type d | wc -l)\"
    echo \"Files: \$(find /data -type f | wc -l)\"
    echo \"Total size: \$(du -sh /data | cut -f1)\"
"