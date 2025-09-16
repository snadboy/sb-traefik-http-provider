# Traefik HTTP Provider with snadboy-ssh-docker

A high-performance FastAPI-based HTTP provider for Traefik that discovers Docker containers across multiple SSH-accessible hosts using the snadboy-ssh-docker library. Uses simplified `snadboy.revp` labels instead of complex Traefik label syntax.

## Features

- **Multi-host Docker Discovery**: Discover containers across multiple Docker hosts via SSH
- **Dynamic Configuration**: Automatically generate Traefik routing configuration from container labels
- **Simplified Label Syntax**: Uses `snadboy.revp` labels for easier container configuration
- **FastAPI Framework**: Native async/await support with automatic API documentation
- **Type Safety**: Pydantic models for request/response validation
- **Health Checks**: Endpoints for monitoring provider health
- **Caching Support**: Optional Redis caching for improved performance
- **Prometheus Metrics**: Export metrics for monitoring
- **VSCode Remote Debugging**: Full debugging support with minimal overhead
- **Auto-generated Documentation**: Interactive API docs at `/docs` and `/redoc`

## Quick Start

### 1. Configure SSH Hosts

Copy the example and customize:
```bash
cp config/ssh-hosts.example.yaml config/ssh-hosts.yaml
```

Edit `config/ssh-hosts.yaml` to define your Docker hosts:

```yaml
hosts:
  dev:
    hostname: host-dev.example.com
    user: docker
    port: 22
    description: Development Docker host
    enabled: true
  prod:
    hostname: host-prod.example.com
    user: docker
    port: 22
    description: Production Docker host
    enabled: true
```

### 2. Configure Provider

Copy the example and customize:
```bash
cp config/provider-config.example.yaml config/provider-config.yaml
```

Edit `config/provider-config.yaml` to customize provider behavior:

```yaml
default_host: dev
label_prefix: snadboy.revp
refresh_interval: 30
```

### 3. Run with Docker Compose

```bash
docker-compose up -d
```

This will start:
- The HTTP provider on port 8080
- Traefik on ports 80/443
- An example Nginx container

### 4. Access Services

- Provider API: http://localhost:8081/api/traefik/config
- API Documentation: http://localhost:8081/docs
- Traefik Dashboard: http://localhost:8080
- Test App: http://test.localhost (or configure your own domain)

## Container Labels

The provider uses simplified `snadboy.revp.{PORT}.{SETTING}` labels for automatic Traefik configuration.

### Required Labels

- **`snadboy.revp.{PORT}.domain`** - The domain for accessing the service
  - Example: `snadboy.revp.80.domain=myapp.example.com`

### Optional Labels (with defaults)

- **`snadboy.revp.{PORT}.backend-proto`** - Backend protocol
  - **Default:** `http`
  - **Options:** `http`, `https`
  - Example: `snadboy.revp.80.backend-proto=https`

- **`snadboy.revp.{PORT}.backend-path`** - Backend path
  - **Default:** `/`
  - Example: `snadboy.revp.80.backend-path=/api/v1`

### Label Format

```
snadboy.revp.{INTERNAL_PORT}.{SETTING}={VALUE}
```

- **`{INTERNAL_PORT}`**: Container's internal port (e.g., `80`, `8080`, `3000`)
- **`{SETTING}`**: Configuration setting (`domain`, `backend-proto`, `backend-path`)
- **`{VALUE}`**: Setting value

### Examples

#### Basic Web Application
```yaml
labels:
  - "snadboy.revp.80.domain=myapp.example.com"
  # Uses defaults: backend-proto=http, backend-path=/
```

#### API with Custom Path
```yaml
labels:
  - "snadboy.revp.8080.domain=api.example.com"
  - "snadboy.revp.8080.backend-path=/api/v1"
  - "snadboy.revp.8080.backend-proto=https"
```

#### Multiple Ports
```yaml
labels:
  - "snadboy.revp.80.domain=app.example.com"
  - "snadboy.revp.9090.domain=metrics.example.com"
  - "snadboy.revp.9090.backend-path=/metrics"
```

#### Complete Example from compose.yml
```yaml
test-revp-app:
  image: nginx:alpine
  labels:
    - "snadboy.revp.80.domain=test.localhost"
    - "snadboy.revp.80.backend-proto=http"
    - "snadboy.revp.80.backend-path=/"
```

### Comparison: snadboy.revp vs Traditional Traefik Labels

The simplified `snadboy.revp` labels provide a much cleaner alternative to traditional Traefik labels:

#### Traditional Traefik Labels (Complex)
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.myapp.rule=Host(`myapp.example.com`)"
  - "traefik.http.routers.myapp.service=myapp-service"
  - "traefik.http.routers.myapp.entrypoints=web"
  - "traefik.http.services.myapp-service.loadbalancer.server.port=8080"
  - "traefik.http.services.myapp-service.loadbalancer.server.scheme=http"
```

#### snadboy.revp Labels (Simple)
```yaml
labels:
  - "snadboy.revp.8080.domain=myapp.example.com"
  # That's it! backend-proto=http and backend-path=/ are defaults
```

#### Advanced Traditional Example
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.api.rule=Host(`api.example.com`) && PathPrefix(`/v1`)"
  - "traefik.http.routers.api.service=api-service"
  - "traefik.http.routers.api.entrypoints=web,websecure"
  - "traefik.http.routers.api.tls=true"
  - "traefik.http.services.api-service.loadbalancer.server.port=8080"
  - "traefik.http.services.api-service.loadbalancer.server.scheme=https"
```

#### snadboy.revp Equivalent
```yaml
labels:
  - "snadboy.revp.8080.domain=api.example.com"
  - "snadboy.revp.8080.backend-proto=https"
  - "snadboy.revp.8080.backend-path=/v1"
```

**Benefits of snadboy.revp:**
- 🎯 **Simpler**: 1-3 labels instead of 6+ labels
- 🚀 **Faster setup**: Less configuration needed
- 🐛 **Fewer errors**: Less complex syntax to get wrong
- 📖 **More readable**: Clear, intuitive label names

## API Endpoints

- `GET /health` - Health check
- `GET /api/traefik/config` - Get Traefik configuration
- `GET /api/containers` - List discovered containers (debug)
- `GET /docs` - Interactive Swagger UI documentation
- `GET /redoc` - Alternative ReDoc documentation
- `GET /openapi.json` - OpenAPI specification

## Development

### Project Structure

```
traekik/
├── app/
│   ├── api/           # FastAPI routes
│   ├── core/          # Core provider logic
│   ├── models.py      # Pydantic models
│   └── main.py        # FastAPI application
├── config/            # Configuration files
├── docker/            # Docker files
└── compose.yml        # Docker Compose setup
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Locally

```bash
python app/main.py
```

Or with uvicorn:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### Debug with VSCode

#### Quick Start

1. **Start container in debug mode:**
   ```bash
   docker-compose run --rm --service-ports traefik-provider debug
   ```

2. **In VSCode:**
   - Open this project folder
   - Go to Run and Debug (Ctrl+Shift+D)
   - Select "Python: Remote Attach (Docker)"
   - Click Start Debugging (F5)

3. **Set breakpoints** in your Python code and test!

#### How It Works

- **Debug Port:** 5678 (exposed from container)
- **Source Mapping:** Local files are mounted to `/app` in container
- **Live Editing:** Changes to source files are immediately reflected
- **Debugpy:** Python debug server waits for VSCode to attach

#### Available Container Modes

- `debug` - Start with debugpy server waiting for VSCode
- `dev` - Direct Python execution with debug logging
- `shell` - Open bash shell for inspection
- Default - Production mode with Uvicorn

#### Tips

- Container will wait for debugger to attach before starting
- You can edit code while debugging (live reload)
- Use `docker-compose logs traefik-provider` to see container output
- Set breakpoints in key functions like `generate_config` for inspection

## Logging

The provider includes comprehensive logging with console and file output, structured logging support, and automatic log rotation.

### Log Files

When using Docker Compose, logs are stored in `./logs/`:

- **app.log** - Main application log with all messages
- **error.log** - Error messages only (ERROR level and above)
- **access.log** - HTTP request/response logs
- **audit.log** - Security and configuration change audit trail

### Configuration

#### Environment Variables
```bash
LOG_LEVEL=INFO          # Log level: DEBUG, INFO, WARNING, ERROR
LOG_DIR=/var/log/traefik-provider  # Log directory
LOG_JSON=false          # Enable JSON structured logging
```

#### Docker Compose
```yaml
environment:
  - LOG_LEVEL=DEBUG     # More verbose logging
  - LOG_JSON=true       # JSON format for log aggregation
```

### Log Levels

- **DEBUG**: Container discovery details, label parsing, configuration steps
- **INFO**: Successful operations, configuration statistics, request handling
- **WARNING**: Missing files, failed requests, deprecated features
- **ERROR**: Connection failures, invalid configurations, exceptions

### Viewing Logs

```bash
# Real-time console output
docker-compose logs -f traefik-provider

# File logs
tail -f logs/app.log
tail -f logs/error.log

# Filter by level
grep "ERROR" logs/app.log

# JSON logs with jq
cat logs/app.log | jq '.'
```

### Log Rotation

Logs are automatically rotated:
- **app.log**: Daily, keep 14 days
- **access.log**: Hourly, keep 48 hours
- **error.log**: Daily, keep 30 days
- **audit.log**: Weekly, keep 1 year

### Structured Logging (JSON)

Enable with `LOG_JSON=true` for log aggregation systems:

```json
{
  "timestamp": "2025-01-15T10:30:45.123456",
  "level": "INFO",
  "logger": "traefik-provider",
  "message": "Configuration generated",
  "container_count": 15,
  "duration_seconds": 2.34
}
```

## Architecture

```
┌─────────────────┐     SSH      ┌──────────────┐
│                 ├─────────────► │ Docker Host1 │
│ FastAPI Provider│               └──────────────┘
│   (Async)       │     SSH      ┌──────────────┐
│                 ├─────────────► │ Docker Host2 │
└────────┬────────┘               └──────────────┘
         │
         │ HTTP (Async)
         │ /api/traefik/config
         ▼
   ┌──────────┐
   │ Traefik  │
   └──────────┘
```

### Technology Stack

- **FastAPI**: Modern async web framework with automatic API documentation
- **Uvicorn**: Lightning-fast ASGI server
- **Pydantic**: Data validation using Python type annotations
- **snadboy-ssh-docker**: SSH-based Docker client for remote container management

## Configuration Options

### Provider Configuration (`config/provider-config.yaml`)

- `ssh_hosts_file`: Path to SSH hosts configuration
- `default_host`: Default host to query (e.g., 'dev')
- `label_prefix`: Label prefix (snadboy.revp)
- `refresh_interval`: How often Traefik polls for updates
- `enable_tls`: Enable TLS support
- `discovery`: Container discovery filters
- `service_defaults`: Default service configuration
- `advanced`: Debug and performance settings

### SSH Hosts Configuration (`config/ssh-hosts.yaml`)

- `hostname`: Host address or domain
- `user`: SSH username
- `port`: SSH port (default 22)
- `key_file`: Path to SSH private key
- `enabled`: Whether host is active
- `description`: Human-readable description

## Troubleshooting

### Connection Issues

1. Verify SSH connectivity:
```bash
ssh -i ~/.ssh/docker_key ubuntu@192.168.1.100
```

2. Check Docker permissions:
```bash
ssh user@host docker ps
```

### Discovery Issues

1. Check container labels:
```bash
docker inspect <container> | grep -A 10 Labels
```

2. View provider logs:
```bash
docker-compose logs traefik-provider
```

## License

MIT

## Contributing

Pull requests welcome! Please ensure all tests pass and add tests for new features.