FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssh-client \
    curl \
    git \
    vim \
    logrotate \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Copy configuration files (will be overridden by volumes in production)
COPY config/ ./config/

# Copy entrypoint script
COPY docker/docker-entrypoint.sh /entrypoint.sh

# Create directories for SSH keys and logs, make entrypoint executable
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh && \
    mkdir -p /var/log/traefik-provider && \
    chmod 755 /var/log/traefik-provider && \
    chmod +x /entrypoint.sh

# Expose port
EXPOSE 8080 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Set environment variables for logging
ENV LOG_DIR=/var/log/traefik-provider \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

# Use entrypoint script
ENTRYPOINT ["/entrypoint.sh"]

# Default command (can be overridden)
CMD ["production"]