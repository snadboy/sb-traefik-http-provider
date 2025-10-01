#!/bin/bash
# Fix script for NAS volume structure after removing SSH key requirements

echo "Fixing NAS volume structure for Tailscale SSH migration..."

# Check if the volume exists
if ! docker volume inspect nas-data &>/dev/null; then
    echo "Error: nas-data volume doesn't exist. Run compose.volume-init.yml first."
    exit 1
fi

echo "Checking current volume structure..."
docker run --rm -v nas-data:/data alpine sh -c "
    echo 'Current structure:'
    ls -la /data/sb-traefik-http-provider/ 2>/dev/null || echo 'sb-traefik-http-provider directory not found'

    # Remove old SSH keys directory if it exists
    if [ -d '/data/sb-traefik-http-provider/ssh-keys' ]; then
        echo 'Removing obsolete ssh-keys directory...'
        rm -rf /data/sb-traefik-http-provider/ssh-keys
        echo 'SSH keys directory removed'
    fi

    # Ensure required directories exist
    echo 'Ensuring required directories exist...'
    mkdir -p /data/sb-traefik-http-provider/config
    mkdir -p /data/sb-traefik-http-provider/logs
    mkdir -p /data/traefik/traefik-dynamic

    echo ''
    echo 'Final structure:'
    ls -la /data/sb-traefik-http-provider/
"

echo ""
echo "✅ NAS volume structure fixed!"
echo ""
echo "Required directories:"
echo "  - sb-traefik-http-provider/config (for provider config files)"
echo "  - sb-traefik-http-provider/logs (for provider logs)"
echo "  - traefik/traefik-dynamic (for Traefik dynamic config)"
echo ""
echo "No SSH keys directory needed - using Tailscale authentication!"