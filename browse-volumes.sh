#!/bin/bash

echo "=== Docker Volumes Overview ==="
docker volume ls

echo -e "\n=== nas-data Volume Contents ==="
docker run --rm -v nas-data:/data alpine tree /data 2>/dev/null || docker run --rm -v nas-data:/data alpine find /data -type f

echo -e "\n=== letsencrypt Volume Contents ==="
docker run --rm -v traekik_letsencrypt-data:/data alpine tree /data 2>/dev/null || docker run --rm -v traekik_letsencrypt-data:/data alpine find /data -type f