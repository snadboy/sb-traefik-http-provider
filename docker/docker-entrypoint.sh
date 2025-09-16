#!/bin/bash
# Docker entrypoint script with log rotation support

set -e

# Create log directory if it doesn't exist
mkdir -p ${LOG_DIR:-/var/log/traefik-provider}

# Set up logrotate if config exists
if [ -f /app/config/logrotate.conf ]; then
    echo "Setting up log rotation..."
    cp /app/config/logrotate.conf /etc/logrotate.d/traefik-provider
    
    # Create logrotate state file
    touch /var/lib/logrotate/status
    
    # Run logrotate in background
    (while true; do
        logrotate /etc/logrotate.d/traefik-provider
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
        echo "Starting in development mode with live SSH Docker provider..."
        echo "Log directory: ${LOG_DIR}"
        echo "Log level: ${LOG_LEVEL}"
        echo "JSON logging: ${LOG_JSON}"
        exec python app/main.py --debug
        ;;
    "shell")
        echo "Starting shell..."
        exec /bin/bash
        ;;
    *)
        echo "Starting in production mode with live SSH Docker provider..."
        echo "Log directory: ${LOG_DIR}"
        echo "Log level: ${LOG_LEVEL}"
        echo "JSON logging: ${LOG_JSON}"

        # Start the live application with gunicorn
        exec gunicorn \
            --bind 0.0.0.0:8080 \
            --workers ${WORKERS:-2} \
            --threads ${THREADS:-1} \
            --timeout ${TIMEOUT:-120} \
            --access-logfile - \
            --error-logfile - \
            --log-level ${LOG_LEVEL:-info} \
            app.main:app
        ;;
esac