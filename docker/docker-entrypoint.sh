#!/bin/bash
# Docker entrypoint script for SB Traefik HTTP Provider

set -e

# Create log directory if it doesn't exist
mkdir -p ${LOG_DIR:-/var/log/sb-traefik-provider}

# Ensure .ssh directory exists for SSH known_hosts (populated by Python app)
mkdir -p /root/.ssh
chmod 700 /root/.ssh

echo "SB Traefik HTTP Provider - Starting"
echo "SSH known_hosts will be initialized by the Python application after networking is ready"

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
            --workers ${WORKERS:-1} \
            --log-level ${UVICORN_LOG_LEVEL} \
            --access-log
        ;;
esac