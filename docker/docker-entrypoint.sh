#!/bin/bash
# Docker entrypoint script with log rotation support

set -e

# Create log directory if it doesn't exist
mkdir -p ${LOG_DIR:-/var/log/sb-traefik-provider}

# Tailscale authentication with MagicDNS
echo "Using Tailscale SSH authentication with MagicDNS resolution"
echo "Ensure Tailscale is installed and SSH is enabled on all Docker hosts:"
echo "  tailscale up --ssh"
echo "MagicDNS (100.100.100.100) will resolve Tailscale hostnames automatically"

# Pre-populate SSH known_hosts for Tailscale hosts
echo "Pre-populating SSH known_hosts for configured Tailscale hosts..."
mkdir -p /root/.ssh
touch /root/.ssh/known_hosts
chmod 600 /root/.ssh/known_hosts

# Parse ssh-hosts.yaml to get enabled hostnames
if [ -f "/app/config/ssh-hosts.yaml" ]; then
    # Extract hostname values for enabled hosts
    HOSTNAMES=$(awk '
        /^[[:space:]]*[a-zA-Z0-9_-]+:/ { current_host = $1; gsub(/:$/, "", current_host) }
        /^[[:space:]]*hostname:/ { hostname = $2 }
        /^[[:space:]]*enabled:[[:space:]]*true/ { if (hostname) print hostname; hostname = "" }
    ' /app/config/ssh-hosts.yaml)

    for hostname in $HOSTNAMES; do
        if [ -n "$hostname" ]; then
            echo "Scanning SSH host keys for $hostname..."
            timeout 10 ssh-keyscan -H "$hostname" >> /root/.ssh/known_hosts 2>/dev/null || echo "Warning: Could not scan keys for $hostname"
        fi
    done

    echo "SSH known_hosts populated with $(wc -l < /root/.ssh/known_hosts) host key entries"
else
    echo "Warning: SSH hosts config file not found at /app/config/ssh-hosts.yaml"
fi

# Set up logrotate if config exists
if [ -f /app/config/logrotate.conf ]; then
    echo "Setting up log rotation..."
    cp /app/config/logrotate.conf /etc/logrotate.d/sb-traefik-provider
    
    # Create logrotate state file
    touch /var/lib/logrotate/status
    
    # Run logrotate in background
    (while true; do
        logrotate /etc/logrotate.d/sb-traefik-provider
        sleep 3600  # Check every hour
    done) &
    
    echo "Log rotation configured and running"
fi

# Handle different run modes
case "${1}" in
    "debug")
        echo "Starting in debug mode with VSCode debugpy..."
        echo "Log directory: ${LOG_DIR}"
        echo "Log level: ${LOG_LEVEL}"
        echo "JSON logging: ${LOG_JSON}"
        echo "Debug port: 5678 (waiting for VSCode to attach)"
        export PYDEVD_DISABLE_FILE_VALIDATION=1
        exec python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:5678 --wait-for-client app/main.py
        ;;
    "dev"|"development")
        echo "Starting in development mode with FastAPI..."
        echo "Log directory: ${LOG_DIR}"
        echo "Log level: ${LOG_LEVEL}"
        echo "JSON logging: ${LOG_JSON}"
        exec python app/main.py --reload --log-level ${LOG_LEVEL:-DEBUG}
        ;;
    "shell")
        echo "Starting shell..."
        exec /bin/bash
        ;;
    *)
        echo "Starting in production mode with FastAPI..."
        echo "Log directory: ${LOG_DIR}"
        echo "Log level: ${LOG_LEVEL}"
        echo "JSON logging: ${LOG_JSON}"

        # Start the live application with uvicorn
        # Convert log level to lowercase for uvicorn
        UVICORN_LOG_LEVEL=$(echo ${LOG_LEVEL:-info} | tr '[:upper:]' '[:lower:]')
        exec uvicorn \
            app.main:app \
            --host 0.0.0.0 \
            --port 8080 \
            --workers ${WORKERS:-2} \
            --log-level ${UVICORN_LOG_LEVEL} \
            --access-log
        ;;
esac