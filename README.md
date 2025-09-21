# SB Traefik HTTP Provider

A high-performance FastAPI-based HTTP provider for Traefik that discovers Docker containers across multiple SSH-accessible hosts using the snadboy-ssh-docker library. Uses simplified `snadboy.revp` labels instead of complex Traefik label syntax.

## Features

- **Multi-host Docker Discovery**: Discover containers across multiple Docker hosts via SSH
- **Dynamic Configuration**: Automatically generate Traefik routing configuration from container labels
- **Simplified Label Syntax**: Uses `snadboy.revp` labels for easier container configuration
- **FastAPI Framework**: Native async/await support with automatic API documentation
- **Type Safety**: Pydantic models for request/response validation
- **Health Checks**: Endpoints for monitoring provider health
- **Real-time Monitoring**: SSHDockerClient monitors Docker events continuously
- **Prometheus Metrics**: Export metrics for monitoring
- **VSCode Remote Debugging**: Full debugging support with minimal overhead
- **Auto-generated Documentation**: Interactive API docs at `/docs` and `/redoc`

## Quick Deploy (Production)

Deploy the published Docker image in minutes:

### 1. Download Example Configuration

```bash
# Download the deployment example
wget https://github.com/snadboy/sb-traefik-http-provider/archive/refs/heads/main.zip
unzip main.zip
cd sb-traefik-http-provider-main/examples/

# Or clone the repository
git clone https://github.com/snadboy/sb-traefik-http-provider.git
cd sb-traefik-http-provider/examples/
```

### 2. Set Up Configuration

```bash
# Create required directories
mkdir -p config ssh-keys traefik-dynamic logs

# Copy and customize configuration files
cp ../config/*.example.yaml config/
cp ../traefik-dynamic/*.example.yml traefik-dynamic/
cp ../.env.example .env

# Edit configurations for your setup
nano config/ssh-hosts.yaml     # Define your Docker hosts
nano .env                       # Add Cloudflare API token
nano docker-compose.yml        # Update domain names
```

### 3. Deploy

```bash
docker-compose up -d
```

### 4. Verify

```bash
# Check provider health
curl http://localhost:8081/health

# View configuration
curl http://localhost:8081/api/traefik/config
```

That's it! Your containers with `snadboy.revp` labels will now be automatically routed with HTTPS.

## Development Setup

For development or building from source:

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
- The HTTP provider on port 8081
- Traefik on ports 80/443
- Example containers (whoami, test-revp-app)

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

#### Backend Configuration
- **`snadboy.revp.{PORT}.backend-proto`** - Backend protocol
  - **Default:** `http`
  - **Options:** `http`, `https`
  - Example: `snadboy.revp.80.backend-proto=https`

- **`snadboy.revp.{PORT}.backend-path`** - Backend path
  - **Default:** `/`
  - Example: `snadboy.revp.80.backend-path=/api/v1`

#### HTTPS/TLS Configuration
- **`snadboy.revp.{PORT}.https`** - Enable HTTPS with automatic Let's Encrypt certificates
  - **Default:** `true`
  - **Options:** `true`, `false`
  - Example: `snadboy.revp.80.https=false` (HTTP only)

- **`snadboy.revp.{PORT}.redirect-https`** - Automatically redirect HTTP to HTTPS
  - **Default:** `true`
  - **Options:** `true`, `false`
  - Example: `snadboy.revp.80.redirect-https=false` (allow both HTTP and HTTPS)

### Label Format

```
snadboy.revp.{INTERNAL_PORT}.{SETTING}={VALUE}
```

- **`{INTERNAL_PORT}`**: Container's internal port (e.g., `80`, `8080`, `3000`)
- **`{SETTING}`**: Configuration setting (see labels above)
- **`{VALUE}`**: Setting value

## HTTPS and SSL/TLS

By default, all services automatically get:
- ✅ **HTTPS enabled** with Let's Encrypt certificates
- ✅ **HTTP to HTTPS redirect** for security
- ✅ **Automatic certificate renewal**

### Examples

#### Basic Web Application (HTTPS by default)
```yaml
labels:
  - "snadboy.revp.80.domain=myapp.example.com"
  # Automatically gets: HTTPS + HTTP redirect + Let's Encrypt certificate
```
**Result**:
- `http://myapp.example.com` → redirects to HTTPS
- `https://myapp.example.com` → serves the application

#### HTTP-Only Service (internal/development)
```yaml
labels:
  - "snadboy.revp.80.domain=internal-api.example.com"
  - "snadboy.revp.80.https=false"
```
**Result**: Only `http://internal-api.example.com` (no HTTPS)

#### Both HTTP and HTTPS (no redirect)
```yaml
labels:
  - "snadboy.revp.80.domain=api.example.com"
  - "snadboy.revp.80.redirect-https=false"
```
**Result**: Both protocols work without redirect
- `http://api.example.com` → serves HTTP
- `https://api.example.com` → serves HTTPS

#### API with Custom Backend
```yaml
labels:
  - "snadboy.revp.8080.domain=api.example.com"
  - "snadboy.revp.8080.backend-path=/api/v1"
  - "snadboy.revp.8080.backend-proto=https"
```
**Result**: HTTPS frontend → HTTPS backend

#### Multiple Ports with Different Configs
```yaml
labels:
  - "snadboy.revp.80.domain=app.example.com"
  - "snadboy.revp.9090.domain=metrics.example.com"
  - "snadboy.revp.9090.backend-path=/metrics"
  - "snadboy.revp.9090.https=false"  # Internal metrics, HTTP only
```

#### Complete Example from compose.yml
```yaml
my-app:
  image: nginx:alpine
  labels:
    - "snadboy.revp.80.domain=myapp.example.com"
    # Gets HTTPS + redirect automatically
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

#### Advanced Traditional Example (HTTPS with redirect)
```yaml
labels:
  - "traefik.enable=true"
  # HTTPS router
  - "traefik.http.routers.api-https.rule=Host(`api.example.com`)"
  - "traefik.http.routers.api-https.entrypoints=websecure"
  - "traefik.http.routers.api-https.tls=true"
  - "traefik.http.routers.api-https.tls.certresolver=letsencrypt"
  - "traefik.http.routers.api-https.service=api-service"
  # HTTP redirect router
  - "traefik.http.routers.api-http.rule=Host(`api.example.com`)"
  - "traefik.http.routers.api-http.entrypoints=web"
  - "traefik.http.routers.api-http.middlewares=api-redirect"
  - "traefik.http.middlewares.api-redirect.redirectscheme.scheme=https"
  # Service
  - "traefik.http.services.api-service.loadbalancer.server.port=8080"
  - "traefik.http.services.api-service.loadbalancer.server.scheme=https"
```

#### snadboy.revp Equivalent
```yaml
labels:
  - "snadboy.revp.8080.domain=api.example.com"
  - "snadboy.revp.8080.backend-proto=https"
  # HTTPS + redirect are automatic defaults!
```

**Benefits of snadboy.revp:**
- 🎯 **Simpler**: 1-2 labels instead of 10+ labels
- 🚀 **Faster setup**: Less configuration needed
- 🔒 **HTTPS by default**: Automatic Let's Encrypt certificates
- 🐛 **Fewer errors**: Less complex syntax to get wrong
- 📖 **More readable**: Clear, intuitive label names

## Let's Encrypt Configuration

The provider uses **Cloudflare DNS challenge** for Let's Encrypt SSL certificates. This method works behind firewalls, doesn't require port 80, and can issue wildcard certificates.

### Setup

1. **Create Cloudflare API Token**:
   - Go to [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)
   - Create token with permissions:
     - `Zone:DNS:Edit`
     - `Zone:Zone:Read`
   - Include all zones or specifically your domain

2. **Configure API Token**:
   ```bash
   # Copy the example file
   cp .env.example .env

   # Edit .env and add your token
   CF_DNS_API_TOKEN=your-actual-cloudflare-api-token
   ```

3. **Update Email in compose.yml**:
   Replace `your-email@example.com` with your actual email address

4. **Switch to Production** (after testing):
   ```yaml
   # For production (in compose.yml):
   - "--certificatesresolvers.letsencrypt.acme.caserver=https://acme-v02.api.letsencrypt.org/directory"

   # For staging/testing (default):
   - "--certificatesresolvers.letsencrypt.acme.caserver=https://acme-staging-v02.api.letsencrypt.org/directory"
   ```

### Wildcard Certificate

This setup uses a **single wildcard certificate** for all subdomains:
- Main domain: `isnadboy.com`
- Wildcard: `*.isnadboy.com`

This means:
- One certificate covers ALL subdomains
- No rate limit issues with many services
- New services automatically use the existing certificate
- Faster startup (no per-service cert requests)

### Benefits of DNS Challenge
- ✅ Works behind firewalls/NAT
- ✅ No need for port 80 to be open
- ✅ Enables wildcard certificates (`*.isnadboy.com`)
- ✅ Works while migrating from other reverse proxies

### Important Notes
- **Never commit .env file** - It contains your API token
- Let's Encrypt rate limits: 50 certificates per domain per week
- Always test with staging server first
- Certificates auto-renew 30 days before expiration

## Static Routes

For services outside of Docker containers (e.g., network devices, VMs), you can define static routes that work alongside container-based routes.

### Configuration

1. **Enable static routes** in `config/provider-config.yaml`:
   ```yaml
   static_routes_file: config/static-routes.yaml
   enable_static_routes: true
   ```

2. **Define routes** in `config/static-routes.yaml`:
   ```yaml
   static_routes:
     - domain: unifi-gateway.isnadboy.com
       target: https://192.168.86.78:8006
       description: "UniFi Network Gateway"
       https: true          # Optional: Enable HTTPS (default: true)
       redirect-https: true # Optional: HTTP→HTTPS redirect (default: true)

     - domain: proxmox.isnadboy.com
       target: https://192.168.1.100:8006
       description: "Proxmox Virtual Environment"

     - domain: internal-api.isnadboy.com
       target: http://192.168.1.200:8080
       description: "Internal API Server"
       https: false         # HTTP only
   ```

### Features

- ✅ **Same HTTPS behavior** as container services
- ✅ **Wildcard certificate** automatically applied
- ✅ **HTTP redirects** by default
- ✅ **Mixed protocols** - route HTTPS domains to HTTP backends
- ✅ **IP addresses or hostnames** supported in targets
- ✅ **Custom paths** supported (e.g., `http://host:3000/grafana`)

### Examples

#### Basic Static Route
```yaml
- domain: router.isnadboy.com
  target: http://192.168.1.1
  description: "Home Router Interface"
# Gets HTTPS + redirect automatically
```

#### HTTP-only Internal Service
```yaml
- domain: prometheus.isnadboy.com
  target: http://192.168.1.50:9090
  description: "Prometheus Metrics"
  https: false  # No HTTPS, HTTP only
```

#### HTTPS Backend with Custom Path
```yaml
- domain: grafana.isnadboy.com
  target: https://192.168.1.50:3000/grafana
  description: "Grafana Dashboard"
```

Static routes are processed alongside container routes and appear in the same configuration output.

## API Endpoints

### Core Endpoints
- `GET /health` - Health check
- `GET /api/traefik/config` - Get Traefik configuration with enhanced metadata
- `GET /api/containers` - List discovered containers with exclusion info and diagnostics

### Diagnostic Endpoints
- `GET /api/status` - Comprehensive system status including SSH host health
- `GET /api/hosts` - SSH host connection statuses
- `GET /api/debug` - Detailed debugging information (label parsing, static routes, SSH diagnostics)

### Documentation
- `GET /docs` - Interactive Swagger UI documentation
- `GET /redoc` - Alternative ReDoc documentation
- `GET /openapi.json` - OpenAPI specification

### API Response Features

#### Enhanced Configuration Metadata
The `/api/traefik/config` endpoint now returns enhanced metadata including:
- Processing time in milliseconds
- Successful vs failed SSH hosts
- Number of excluded containers
- Static route count
- Diagnostic information

#### Container Exclusion Tracking
The `/api/containers` endpoint provides detailed information about:
- **Included containers**: Successfully configured containers with valid `snadboy.revp` labels
- **Excluded containers**: Containers excluded from routing with reasons:
  - `No snadboy.revp labels` - Container has no routing labels
  - `Invalid label configuration` - Container has labels but configuration is invalid
  - `Label processing error` - Exception occurred while processing labels
  - `Label extraction error` - Error extracting labels from container

#### SSH Host Health Monitoring
Monitor the health of all configured SSH hosts:
- Connection status (connected, unreachable, error)
- Last successful connection timestamp
- Connection time in milliseconds
- Docker version information
- Container counts (total and running) - accurately detects containers with status "Up"

#### Debug Information
Comprehensive debugging data including:
- **Label Parsing**: Containers with snadboy labels, valid configurations, parsing errors
- **Static Routes**: Loaded routes and configuration errors
- **SSH Diagnostics**: Key files, connection timeouts, permission errors

### Example API Usage

```bash
# Check system health and SSH host status
curl http://localhost:8081/api/status

# List all containers with exclusion information
curl http://localhost:8081/api/containers

# Get SSH host connection statuses
curl http://localhost:8081/api/hosts

# Get detailed debugging information
curl http://localhost:8081/api/debug

# Get Traefik configuration with enhanced metadata
curl http://localhost:8081/api/traefik/config
```

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
   docker-compose run --rm --service-ports sb-traefik-http-provider debug
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
- Use `docker-compose logs sb-traefik-http-provider` to see container output
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