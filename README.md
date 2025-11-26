# SB Traefik HTTP Provider

A high-performance FastAPI HTTP provider for Traefik that discovers Docker containers across multiple SSH-accessible hosts. Uses simplified `snadboy.revp` labels instead of complex Traefik syntax.

## Key Features

- **Event-Driven**: Real-time Docker event streams with intelligent caching and 2s debouncing
- **Multi-Host Discovery**: Monitor containers across multiple Docker hosts via Tailscale SSH
- **Simplified Labels**: `snadboy.revp.PORT.domain=example.com` instead of 10+ Traefik labels
- **Zero-Config SSH**: Tailscale authentication - no key management required
- **HTTPS by Default**: Automatic Let's Encrypt with wildcard certificate support
- **Static Routes**: Route non-Docker services (network devices, VMs, etc.)
- **FastAPI**: Native async/await with auto-generated docs at `/docs`

## Quick Start

### 1. Setup Tailscale

Install Tailscale on all Docker hosts and enable SSH:
```bash
tailscale up --ssh
```

### 2. Configure Hosts

Create `config/ssh-hosts.yaml`:
```yaml
defaults:
  user: root
  port: 22
  enabled: true

hosts:
  dev:
    hostname: dev.tail-scale.ts.net
    description: Development server

  prod:
    hostname: prod.tail-scale.ts.net
    description: Production server
```

### 3. Deploy

```bash
docker compose up -d
```

## Container Labels

### Basic Usage

```yaml
services:
  myapp:
    image: myapp:latest
    labels:
      - "snadboy.revp.80.domain=myapp.example.com"
```

Result: `https://myapp.example.com` → container port 80 (HTTPS with auto-redirect)

### All Options

```yaml
labels:
  # Required
  - "snadboy.revp.PORT.domain=myapp.example.com"

  # Optional (defaults shown)
  - "snadboy.revp.PORT.https=true"              # Enable HTTPS
  - "snadboy.revp.PORT.redirect-https=true"     # HTTP→HTTPS redirect
  - "snadboy.revp.PORT.backend-proto=http"      # Backend protocol
  - "snadboy.revp.PORT.backend-path=/"          # Backend path
```

### Examples

**HTTP Only (internal services):**
```yaml
- "snadboy.revp.80.domain=internal.local"
- "snadboy.revp.80.https=false"
```

**HTTPS without redirect:**
```yaml
- "snadboy.revp.80.domain=api.example.com"
- "snadboy.revp.80.redirect-https=false"
```

**Custom backend:**
```yaml
- "snadboy.revp.8080.domain=api.example.com"
- "snadboy.revp.8080.backend-proto=https"
- "snadboy.revp.8080.backend-path=/v1"
```

**Multiple ports:**
```yaml
- "snadboy.revp.80.domain=web.example.com"
- "snadboy.revp.9090.domain=metrics.example.com"
- "snadboy.revp.9090.https=false"
```

### Multi-Route Labels

Route different domains to different paths on the same port using `.N` suffix:

```yaml
labels:
  # Route 1: API at root path (no suffix = .1)
  - "snadboy.revp.8080.domain=api.example.com"

  # Route 2: Dashboard at /static path
  - "snadboy.revp.8080.domain.2=dashboard.example.com"
  - "snadboy.revp.8080.backend-path.2=/static"

  # Route 3: Docs at /docs path with different settings
  - "snadboy.revp.8080.domain.3=docs.example.com"
  - "snadboy.revp.8080.backend-path.3=/docs"
  - "snadboy.revp.8080.https.3=false"
```

Result:
- `https://api.example.com` → container:8080/
- `https://dashboard.example.com` → container:8080/static
- `http://docs.example.com` → container:8080/docs

**Key points:**
- No suffix is equivalent to `.1` (backwards compatible)
- Each route inherits from code defaults, not from other routes
- Routes can be sparse (e.g., only `.2` and `.5` defined)
- All settings support the `.N` suffix: `domain`, `backend-path`, `backend-proto`, `https`, `redirect-https`, `https-certresolver`

## Static Routes

For services outside Docker (network devices, VMs), create `config/static-routes.yaml`:

```yaml
static_routes:
  - domain: router.example.com
    target: https://192.168.1.1
    description: "Network Router"
    https: true
    redirect-https: true

  - domain: proxmox.example.com
    target: https://192.168.1.100:8006
    description: "Proxmox VE"
```

## HTTPS Configuration

### Wildcard Certificate

Create `traefik-dynamic/wildcard-cert.yml`:
```yaml
tls:
  certificates:
    - certFile: /letsencrypt/wildcard-cert.pem
      keyFile: /letsencrypt/wildcard-key.pem
  stores:
    default:
      defaultCertificate:
        certFile: /letsencrypt/wildcard-cert.pem
        keyFile: /letsencrypt/wildcard-key.pem
```

### Cloudflare DNS Challenge

In `.env`:
```bash
CF_API_TOKEN=your_cloudflare_api_token_here
DOMAIN=example.com
```

Certificates auto-renew 30 days before expiration.

## API Endpoints

- `GET /health` - Health check
- `GET /api/traefik/config` - Current Traefik configuration
- `GET /api/status` - Provider status and diagnostics
- `GET /api/containers` - All discovered containers
- `GET /api/ssh/status` - SSH host health status
- `POST /api/cache/refresh` - Force cache refresh
- `GET /docs` - Interactive API documentation
- `GET /metrics` - Prometheus metrics

## Configuration Files

- `config/ssh-hosts.yaml` - Docker host definitions
- `config/static-routes.yaml` - Static route definitions
- `traefik-dynamic/wildcard-cert.yml` - TLS certificate configuration
- `.env` - Environment variables (Cloudflare API token, domain)

## Architecture

### Event-Driven Updates

1. Provider starts and generates initial config
2. Subscribes to Docker events on all enabled hosts
3. On container start/stop/restart:
   - Debounces events (2s window)
   - Refreshes cache
   - Traefik polls and gets updated config

### Networking

- **Bridge Mode**: Proper container isolation with explicit port mappings
- **Tailscale MagicDNS**: Uses `100.100.100.100` for hostname resolution
- **SSH Access**: Containers use `-H ssh://user@host` for remote Docker access

## Development

### Run Locally

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp config/ssh-hosts.example.yaml config/ssh-hosts.yaml

# Run
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### VSCode Debugging

1. Set breakpoints in code
2. Run container: `docker compose -f compose.development.yml up`
3. Attach: **Run** → **Attach to Docker Container** → Select `sb-traefik-http-provider`
4. Trigger endpoint: Container pauses at breakpoint

### Project Structure

```
app/
├── main.py              # FastAPI application
├── core/
│   └── provider.py      # Traefik configuration generator
├── api/
│   └── routes.py        # API endpoints
└── models.py            # Pydantic models
config/
├── ssh-hosts.yaml       # Host definitions
└── static-routes.yaml   # Static routes
docker/
├── Dockerfile           # Production image
└── docker-entrypoint.sh # Startup script
```

## Logging

### Log Levels

```bash
# Environment variable
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR

# Docker Compose
environment:
  - LOG_LEVEL=DEBUG
```

### View Logs

```bash
# Container logs
docker compose logs -f sb-traefik-http-provider

# File logs (persistent)
tail -f logs/sb-traefik-provider.log

# Specific log file
tail -f logs/sb-traefik-provider-YYYY-MM-DD.log
```

## Troubleshooting

### Tailscale SSH Issues

**"Failed to connect to host"**
```bash
# Verify Tailscale is running
tailscale status

# Enable SSH
tailscale up --ssh

# Test SSH connection
ssh root@hostname.tail-scale.ts.net docker ps
```

**"Host not found"**
```bash
# Check Tailscale hostname
tailscale status | grep hostname

# Use MagicDNS name (without domain)
# ✓ Correct: hostname
# ✗ Wrong: hostname.tail-scale.ts.net
```

### Discovery Issues

**"No containers discovered"**
- Check container has `snadboy.revp.PORT.domain` label
- Verify host is enabled in `config/ssh-hosts.yaml`
- Check container is running: `docker ps`
- Review provider logs for errors

**"Service not routing"**
- Verify domain resolves to Traefik host
- Check Traefik dashboard: `http://traefik-host:8080`
- Confirm service appears in API: `curl http://localhost:8081/api/traefik/config`
- Check Traefik logs for errors

## Technology Stack

- **FastAPI** - Modern async web framework
- **Uvicorn** - ASGI server
- **Pydantic** - Data validation
- **snadboy-ssh-docker** - SSH-based Docker client
- **Traefik** - Reverse proxy and load balancer
- **Tailscale** - Zero-config VPN and SSH

## License

MIT

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.
