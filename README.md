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
  - "snadboy.revp.PORT.backend-proto=http"      # Backend protocol (http or https)
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

**HTTPS backend (e.g., self-signed cert):**
```yaml
- "snadboy.revp.8080.domain=api.example.com"
- "snadboy.revp.8080.backend-proto=https"
```

**Multiple ports:**
```yaml
- "snadboy.revp.80.domain=web.example.com"
- "snadboy.revp.9090.domain=metrics.example.com"
- "snadboy.revp.9090.https=false"
```

### Multiple Domains per Port

You can route multiple domains to the same container port using comma-separated values:

```yaml
labels:
  - "snadboy.revp.8080.domain=app.example.com,app2.example.com"
```

Result: Both `https://app.example.com` and `https://app2.example.com` → container:8080

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
    insecure-skip-verify: true  # Skip TLS verification for self-signed certs
```

### Static Route Options

| Option | Default | Description |
|--------|---------|-------------|
| `domain` | (required) | Domain name to route |
| `target` | (required) | Backend URL (http:// or https://) |
| `description` | `""` | Optional description |
| `https` | `true` | Enable HTTPS on frontend |
| `redirect-https` | `true` | Redirect HTTP to HTTPS |
| `insecure-skip-verify` | `false` | Skip TLS verification for self-signed backend certs |
| `pass-host-header` | `true` | Pass original Host header to backend. Set to `false` to send backend's own hostname (useful for external services that validate the Host header) |

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

## TLS/SSL Verification

### Self-Signed Backend Certificates (Static Routes)

When routing to backend services with self-signed certificates (e.g., Proxmox, iDRAC, network devices), Traefik will reject the connection by default. Use the `insecure-skip-verify` option to bypass certificate verification:

```yaml
static_routes:
  - domain: proxmox.example.com
    target: https://192.168.1.100:8006
    description: "Proxmox VE with self-signed cert"
    https: true
    redirect-https: true
    insecure-skip-verify: true
```

This creates a Traefik `serversTransport` with `insecureSkipVerify: true` for that backend. The dashboard will display an **INSECURE** badge for routes using this option.

**Use cases:**
- Proxmox/Proxmox Backup Server web interfaces
- Network device management pages (routers, switches, UPS)
- Internal services with self-signed certificates
- Development/staging environments

### Cloudflare Tunnel TLS Verification

When using Cloudflare Tunnels (`cloudflared`) to expose services, the tunnel must connect to your origin server (Traefik). If the tunnel connects via HTTPS, certificate verification can fail in two scenarios:

**Scenario 1: Using IP address as origin**
```
Error: x509: cannot validate certificate for 192.168.1.100 because it doesn't contain any IP SANs
```
The tunnel is configured with an IP address, but certificates are issued for domain names.

**Scenario 2: Certificate not yet issued**
Let's Encrypt certificates may not exist yet for new domains, causing connection failures.

**Solution: Disable TLS verification in Cloudflare Tunnel**

In your Cloudflare Tunnel config (`config.yml`):
```yaml
ingress:
  - hostname: myapp.example.com
    service: https://192.168.1.100
    originRequest:
      noTLSVerify: true
  - hostname: another.example.com
    service: https://traefik-host
    originRequest:
      noTLSVerify: true
  - service: http_status:404
```

Or via the Cloudflare Zero Trust Dashboard:
1. Go to **Access** → **Tunnels**
2. Select your tunnel → **Configure**
3. Edit the public hostname
4. Under **Additional application settings** → **TLS**
5. Enable **No TLS Verify**

**Alternative: Use hostname instead of IP**
If your tunnel host can resolve the Traefik hostname, use that instead of an IP:
```yaml
ingress:
  - hostname: myapp.example.com
    service: https://traefik.local
```
This allows the certificate to match the hostname.

## API Endpoints

- `GET /` - Dashboard (web UI)
- `GET /health` - Health check
- `GET /api/traefik/config` - Current Traefik configuration
- `GET /api/status` - Provider status and diagnostics
- `GET /api/containers` - All discovered containers
- `GET /api/hosts` - SSH host health status
- `GET /api/services` - Formatted service list for dashboard
- `GET /api/events` - Recent container events
- `GET /docs` - Interactive API documentation (Swagger UI)

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

### Local Container Network Requirements

For containers running on the **same host as Traefik** (local hosts with `is_local: true`), the provider routes traffic using Docker's internal DNS by container name. This requires that **local containers must be on the same Docker network as Traefik**.

**Example: Add container to Traefik network**

```yaml
services:
  myapp:
    image: myapp:latest
    labels:
      - "snadboy.revp.8080.domain=myapp.example.com"
    networks:
      - traefik

networks:
  traefik:
    external: true
```

**Why this is required:**
- Local containers are routed via `http://container-name:port/`
- Docker DNS only resolves container names within the same network
- Without a shared network, Traefik returns 502 Bad Gateway

**Remote hosts** (via SSH) don't have this requirement - they use the host's IP/hostname and mapped ports.

**Troubleshooting 502 errors for local containers:**
```bash
# Check which network Traefik is on
docker inspect traefik --format '{{range $net, $conf := .NetworkSettings.Networks}}{{$net}} {{end}}'

# Check which network your container is on
docker inspect myapp --format '{{range $net, $conf := .NetworkSettings.Networks}}{{$net}} {{end}}'

# If different, add your container to Traefik's network
docker network connect traefik myapp
```

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
