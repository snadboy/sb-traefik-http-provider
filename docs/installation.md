# Installation Guide

## Production Deployment (Recommended)

The easiest way to deploy SB Traefik HTTP Provider is using the published Docker image.

### Prerequisites

- Docker and Docker Compose
- SSH access to your Docker hosts
- Cloudflare account with API token (for HTTPS certificates)
- Domain name configured in Cloudflare

### Step 1: Download Deployment Files

Choose one of these methods:

#### Option A: Download Release
```bash
wget https://github.com/snadboy/sb-traefik-http-provider/archive/refs/heads/main.zip
unzip main.zip
cd sb-traefik-http-provider-main/examples/
```

#### Option B: Clone Repository
```bash
git clone https://github.com/snadboy/sb-traefik-http-provider.git
cd sb-traefik-http-provider/examples/
```

### Step 2: Prepare Directory Structure

```bash
# Create required directories
mkdir -p config ssh-keys traefik-dynamic logs

# Copy example configurations
cp ../config/ssh-hosts.example.yaml config/ssh-hosts.yaml
cp ../config/static-routes.example.yaml config/static-routes.yaml
cp ../traefik-dynamic/wildcard-cert.yml.example traefik-dynamic/wildcard-cert.yml
cp ../.env.example .env
```

### Step 3: Configure SSH Access

Add your SSH private key for accessing Docker hosts:

```bash
# Copy your SSH key
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

  staging:
    hostname: staging.example.com
    user: docker
    port: 22
    key_file: /app/ssh-keys/id_rsa
    enabled: true
    description: Staging environment
```

### Step 4: Configure DNS and Certificates

#### 4.1 Create Cloudflare API Token

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click "Create Token"
3. Use "Custom token" template
4. Set permissions:
   - Zone:DNS:Edit
   - Zone:Zone:Read
5. Include your domain zone
6. Copy the token

#### 4.2 Set Environment Variables

Edit `.env`:

```bash
# Cloudflare API Token for Let's Encrypt DNS Challenge
CF_DNS_API_TOKEN=your-actual-cloudflare-api-token
```

#### 4.3 Configure Wildcard Certificate

Edit `traefik-dynamic/wildcard-cert.yml`:

```yaml
http:
  routers:
    wildcard-trigger:
      rule: "Host(`yourdomain.com`)"
      service: noop-service
      priority: 1
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt
        domains:
          - main: "yourdomain.com"
            sans:
              - "*.yourdomain.com"
```

### Step 5: Update Configuration

Edit `docker-compose.yml` and update:

1. **Email address** in Traefik command:
   ```yaml
   - "--certificatesresolvers.letsencrypt.acme.email=your-email@example.com"
   ```

2. **Domain names** in provider labels:
   ```yaml
   labels:
     - "snadboy.revp.8080.domain=traefik-provider.yourdomain.com"
     - "snadboy.revp.9090.domain=traefik-metrics.yourdomain.com"
   ```

### Step 6: Deploy

```bash
# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f sb-traefik-http-provider
```

### Step 7: Verify Installation

#### Check Health
```bash
# Provider health
curl http://localhost:8081/health

# Traefik ping
curl http://localhost:8080/ping
```

#### Test Configuration
```bash
# View generated Traefik config
curl http://localhost:8081/api/traefik/config | jq .

# Check discovered containers
curl http://localhost:8081/api/containers | jq .
```

#### Access Dashboards
- **Provider API Docs**: http://localhost:8081/docs
- **Traefik Dashboard**: http://localhost:8080

### Step 8: Label Your Containers

On your Docker hosts, add labels to containers:

```yaml
# Basic web app with HTTPS
labels:
  - "snadboy.revp.80.domain=myapp.yourdomain.com"

# API with custom path
labels:
  - "snadboy.revp.8080.domain=api.yourdomain.com"
  - "snadboy.revp.8080.backend-path=/api/v1"

# Internal service (HTTP only)
labels:
  - "snadboy.revp.9000.domain=internal.yourdomain.com"
  - "snadboy.revp.9000.https=false"
```

## Development Setup

For development or contributing to the project:

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Git

### Setup

```bash
# Clone repository
git clone https://github.com/snadboy/sb-traefik-http-provider.git
cd sb-traefik-http-provider

# Install dependencies
pip install -r requirements.txt

# Copy configurations
cp config/ssh-hosts.example.yaml config/ssh-hosts.yaml
cp .env.example .env

# Edit configurations for your setup
```

### Run Locally

```bash
# Run with Python
python app/main.py

# Or with Docker Compose (builds from source)
docker-compose up --build
```

### Debug with VSCode

```bash
# Start in debug mode
docker-compose run --rm --service-ports sb-traefik-http-provider debug

# In VSCode:
# 1. Open this project
# 2. Go to Run and Debug (Ctrl+Shift+D)
# 3. Select "Python: Remote Attach (Docker)"
# 4. Click Start Debugging (F5)
```

## Troubleshooting

### Common Issues

#### Provider Can't Connect to Docker Hosts
```bash
# Test SSH connectivity
docker-compose exec sb-traefik-http-provider ssh -i /app/ssh-keys/id_rsa user@host

# Check SSH key permissions
ls -la ssh-keys/
```

#### Certificate Generation Fails
```bash
# Check Cloudflare API token
docker-compose logs traefik | grep -i acme

# Verify DNS configuration
dig yourdomain.com
```

#### No Containers Discovered
```bash
# Check provider logs
docker-compose logs sb-traefik-http-provider

# Test API endpoint
curl http://localhost:8081/api/containers
```

### Log Levels

For debugging, increase log verbosity:

```bash
# In docker-compose.yml
environment:
  - LOG_LEVEL=DEBUG
```

### Getting Help

- [GitHub Issues](https://github.com/snadboy/sb-traefik-http-provider/issues)
- [Documentation](https://snadboy.github.io/sb-traefik-http-provider/)
- [API Reference](http://localhost:8081/docs) (when running)