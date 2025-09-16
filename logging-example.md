# Logging Configuration Guide

## Overview
The Traefik HTTP Provider now includes comprehensive logging with both console and file output, structured logging support, and automatic log rotation.

## Log Files

The provider creates several log files in `/var/log/traefik-provider/` (or `./logs` when using Docker Compose):

- **app.log** - Main application log with all messages
- **error.log** - Error messages only (ERROR level and above)
- **access.log** - HTTP request/response logs
- **audit.log** - Security and configuration change audit trail

## Configuration Options

### Environment Variables

```bash
LOG_LEVEL=INFO          # Log level: DEBUG, INFO, WARNING, ERROR
LOG_DIR=/var/log/traefik-provider  # Log directory
LOG_JSON=false          # Enable JSON structured logging
```

### Docker Compose

```yaml
environment:
  - LOG_LEVEL=DEBUG     # More verbose logging
  - LOG_JSON=true       # JSON format for log aggregation
```

### Command Line

```bash
python traefik_http_provider.py \
  --log-level DEBUG \
  --log-dir ./logs \
  --log-json
```

## Log Levels

- **DEBUG**: Detailed information for debugging
  - Container discovery details
  - Label parsing information
  - Configuration generation steps

- **INFO**: General operational information
  - Successful operations
  - Configuration statistics
  - Request handling

- **WARNING**: Warning messages
  - Missing configuration files
  - Failed requests
  - Deprecated features

- **ERROR**: Error messages
  - Connection failures
  - Invalid configurations
  - Exception details

## Viewing Logs

### Real-time Console Output
```bash
docker-compose logs -f traefik-provider
```

### File Logs
```bash
# View main application log
tail -f logs/app.log

# View only errors
tail -f logs/error.log

# View access logs
tail -f logs/access.log

# Filter logs by level
grep "ERROR" logs/app.log

# View JSON logs with jq
cat logs/app.log | jq '.'
```

## Log Rotation

Logs are automatically rotated based on the configuration in `logrotate.conf`:

- **app.log**: Daily rotation, keep 14 days
- **access.log**: Hourly rotation, keep 48 hours
- **error.log**: Daily rotation, keep 30 days
- **audit.log**: Weekly rotation, keep 1 year

Maximum file size triggers rotation even before the scheduled time.

## Structured Logging (JSON)

Enable JSON logging for better integration with log aggregation systems:

```yaml
environment:
  - LOG_JSON=true
```

JSON log format:
```json
{
  "timestamp": "2024-01-15T10:30:45.123456",
  "level": "INFO",
  "logger": "traefik-provider",
  "message": "Configuration generated",
  "module": "traefik_http_provider",
  "function": "generate_config",
  "line": 245,
  "host": "docker-host-1",
  "container_count": 15,
  "duration_seconds": 2.34
}
```

## Custom Logging

### Discovery Events
```python
discovery_logger.log_discovery_start("host-1")
discovery_logger.log_container_found("host-1", "app", "abc123", labels)
discovery_logger.log_discovery_complete("host-1", 10, 1.5)
```

### Configuration Events
```python
config_logger.log_config_generation_start()
config_logger.log_label_parsing("container-1", 5)
config_logger.log_config_generation_complete(stats)
```

### Audit Events
```python
audit_logger.info("Configuration changed", extra={'user': 'admin'})
audit_logger.warning("Unauthorized access attempt", extra={'ip': '1.2.3.4'})
```

## Integration with Monitoring

### Prometheus Metrics
Logs include metrics that can be scraped:
- Request count and duration
- Container discovery time
- Configuration generation time

### ELK Stack Integration
Use JSON logging and Filebeat:
```yaml
filebeat.inputs:
- type: log
  paths:
    - /var/log/traefik-provider/*.log
  json.keys_under_root: true
  json.add_error_key: true
```

### CloudWatch/Datadog
Use JSON format and ship logs using their agents.

## Troubleshooting

### Enable Debug Logging
```bash
docker-compose down
docker-compose up -e LOG_LEVEL=DEBUG
```

### Check Log Permissions
```bash
ls -la logs/
# Should show readable files
```

### Verify Log Rotation
```bash
# Manual rotation test
docker exec traefik-http-provider logrotate -f /etc/logrotate.d/traefik-provider
```

### Clear Old Logs
```bash
# Remove logs older than 7 days
find logs/ -name "*.log*" -mtime +7 -delete
```

## Performance Considerations

- Use INFO level in production
- Enable JSON only if needed for aggregation
- Consider mounting logs as tmpfs for high-traffic scenarios
- Adjust rotation frequency based on volume

## Security

- Audit logs have restricted permissions (0600)
- Sensitive information is sanitized in logs
- SSH keys and passwords are never logged
- IP addresses are logged for security tracking