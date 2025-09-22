#!/bin/bash
# Docker entrypoint script with log rotation support

set -e

# Create log directory if it doesn't exist
mkdir -p ${LOG_DIR:-/var/log/sb-traefik-provider}

# Setup SSH keys with proper permissions
echo "Setting up SSH keys..."
mkdir -p /app/ssh-keys
chmod 700 /app/ssh-keys

# Copy SSH keys from mounted source and set proper permissions
if [ -d "/mnt/ssh-keys" ]; then
    echo "Copying SSH keys from /mnt/ssh-keys to /app/ssh-keys"

    # Look for SSH keys in multiple locations (prefer root directory)
    SSH_KEY_COPIED=false

    # First priority: id_ssh in mount root
    if [ -f "/mnt/ssh-keys/id_ssh" ]; then
        SOURCE_SIZE=$(stat -c%s /mnt/ssh-keys/id_ssh)
        if [ "$SOURCE_SIZE" -gt 0 ]; then
            echo "Found SSH key: /mnt/ssh-keys/id_ssh (${SOURCE_SIZE} bytes)"
            cp /mnt/ssh-keys/id_ssh /app/ssh-keys/
            chmod 600 /app/ssh-keys/id_ssh
            COPIED_SIZE=$(stat -c%s /app/ssh-keys/id_ssh)
            echo "Copied id_ssh successfully (${COPIED_SIZE} bytes)"
            SSH_KEY_COPIED=true
        else
            echo "Warning: /mnt/ssh-keys/id_ssh is empty, skipping"
        fi
    fi

    # Second priority: ssh-keys subdirectory (only if not already copied)
    if [ "$SSH_KEY_COPIED" = false ] && [ -d "/mnt/ssh-keys/ssh-keys" ]; then
        echo "Checking ssh-keys subdirectory"
        if [ -f "/mnt/ssh-keys/ssh-keys/id_ssh" ]; then
            SOURCE_SIZE=$(stat -c%s /mnt/ssh-keys/ssh-keys/id_ssh)
            if [ "$SOURCE_SIZE" -gt 0 ]; then
                echo "Found SSH key: /mnt/ssh-keys/ssh-keys/id_ssh (${SOURCE_SIZE} bytes)"
                cp /mnt/ssh-keys/ssh-keys/id_ssh /app/ssh-keys/
                chmod 600 /app/ssh-keys/id_ssh
                COPIED_SIZE=$(stat -c%s /app/ssh-keys/id_ssh)
                echo "Copied id_ssh successfully (${COPIED_SIZE} bytes)"
                SSH_KEY_COPIED=true
            else
                echo "Warning: /mnt/ssh-keys/ssh-keys/id_ssh is empty, skipping"
            fi
        fi
    fi

    if [ "$SSH_KEY_COPIED" = false ]; then
        echo "ERROR: No valid SSH key found in mounted directories"
    fi

    echo "SSH keys setup completed"
else
    echo "ERROR: SSH keys directory /mnt/ssh-keys not found!"
    echo "Please mount your SSH keys directory to /mnt/ssh-keys:ro"
    exit 1
fi

# Validate SSH keys exist and are readable
if [ ! -f "/app/ssh-keys/id_ssh" ]; then
    echo "ERROR: SSH private key /app/ssh-keys/id_ssh not found!"
    echo "Expected SSH key file in mounted directory: ./ssh-keys/id_ssh"
    exit 1
fi

# Check SSH key permissions
KEY_PERMS=$(stat -c %a /app/ssh-keys/id_ssh)
if [ "$KEY_PERMS" != "600" ]; then
    echo "Warning: SSH key permissions are $KEY_PERMS, fixing to 600"
    chmod 600 /app/ssh-keys/id_ssh
fi

echo "SSH key validation completed successfully"

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