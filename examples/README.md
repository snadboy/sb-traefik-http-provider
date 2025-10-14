# SB Traefik HTTP Provider - Deployment Example

This directory contains a complete production deployment example using the published Docker image.

## Quick Start

### 1. Prepare Configuration

Copy the example configurations and customize them:

```bash
# Create config directory
mkdir -p config ssh-keys traefik-dynamic logs

# Copy example configurations
cp ../config/ssh-hosts.example.yaml config/ssh-hosts.yaml
cp ../config/static-routes.example.yaml config/static-routes.yaml

# Copy Traefik dynamic config examples
cp ../traefik-dynamic/wildcard-cert.yml.example traefik-dynamic/wildcard-cert.yml

# Copy environment file
cp ../.env.example .env
```

### 2. Configure SSH Access

Add your SSH key for accessing remote Docker hosts:

```bash
# Copy your SSH private key
cp ~/.ssh/id_rsa ssh-keys/
chmod 600 ssh-keys/id_rsa
```

Edit `config/ssh-hosts.yaml` to define your Docker hosts:

```yaml
hosts:
  production:
    hostname: docker-host.example.com
    user: docker
    port: 22
    key_file: /app/ssh-keys/id_rsa
    enabled: true
    description: Production Docker host
```

### 3. Configure DNS and Certificates

Edit `.env` and add your Cloudflare API token:

```bash
CF_DNS_API_TOKEN=your-cloudflare-api-token-here
```

Edit `traefik-dynamic/wildcard-cert.yml` and update the domain:

```yaml
domains:
  - main: "yourdomain.com"
    sans:
      - "*.yourdomain.com"
```

### 4. Update Domain Configuration

Edit `docker-compose.yml` and update:
- Email address in Traefik command
- Domain names in provider labels
- Any other domain-specific settings

### 5. Deploy

```bash
docker-compose up -d
```

### 6. Verify Deployment

Check that services are running:

```bash
# Check container status
docker-compose ps

# Check provider API
curl http://localhost:8081/health

# Check Traefik dashboard
curl http://localhost:8080/ping

# View logs
docker-compose logs -f sb-traefik-http-provider
```

## Configuration Files

- **`docker-compose.yml`** - Main deployment file
- **`config/ssh-hosts.yaml`** - Define your Docker hosts
- **`config/static-routes.yaml`** - Routes for non-Docker services
- **`traefik-dynamic/wildcard-cert.yml`** - Wildcard certificate configuration
- **`.env`** - Environment variables (Cloudflare API token)

## Container Labels

Label your containers on remote Docker hosts using the `snadboy.revp` format:

```yaml
labels:
  - "snadboy.revp.80.domain=myapp.yourdomain.com"
  # Automatically gets HTTPS + redirect
```

## Monitoring

- **Provider API**: http://localhost:8081/api/traefik/config
- **Provider Health**: http://localhost:8081/health
- **Prometheus Metrics**: http://localhost:9090
- **Traefik Dashboard**: http://localhost:8080

## Security Notes

- Change default ports if needed
- Remove Traefik dashboard in production
- Use strong SSH keys
- Keep Cloudflare API token secure
- Review firewall rules

## Troubleshooting

Check logs for issues:

```bash
# Provider logs
docker-compose logs sb-traefik-http-provider

# Traefik logs
docker-compose logs traefik

# Test SSH connectivity
docker-compose exec sb-traefik-http-provider ssh -i /app/ssh-keys/id_rsa user@host
```