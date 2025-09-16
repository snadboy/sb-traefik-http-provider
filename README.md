# Traefik HTTP Provider with snadboy-ssh-docker

A Python-based HTTP provider for Traefik that discovers Docker containers across multiple SSH-accessible hosts using the snadboy-ssh-docker library. Uses simplified `snadboy.revp` labels instead of complex Traefik label syntax.

## Features

- **Multi-host Docker Discovery**: Discover containers across multiple Docker hosts via SSH
- **Dynamic Configuration**: Automatically generate Traefik routing configuration from container labels
- **Simplified Label Syntax**: Uses `snadboy.revp` labels for easier container configuration
- **Health Checks**: Endpoints for monitoring provider health
- **Caching Support**: Optional Redis caching for improved performance
- **Prometheus Metrics**: Export metrics for monitoring
- **VSCode Remote Debugging**: Full debugging support with minimal overhead

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
- Traefik Dashboard: http://localhost:8080
- Test App: http://test.isnadboy.com

## Container Labels

Add these simplified snadboy.revp labels to your containers:

```yaml
labels:
  - "snadboy.revp.80.domain=myapp.example.com"
  - "snadboy.revp.80.backend-proto=http"
  - "snadboy.revp.80.backend-path=/"
```

Example from compose.yml:
```yaml
test-revp-app:
  image: nginx:alpine
  labels:
    - "snadboy.revp.80.domain=test.isnadboy.com"
    - "snadboy.revp.80.backend-proto=http"
    - "snadboy.revp.80.backend-path=/"
```

## API Endpoints

- `GET /health` - Health check
- `GET /api/traefik/config` - Get Traefik configuration
- `GET /api/containers` - List discovered containers (debug)
- `GET /api/config` - Get provider configuration

## Development

### Project Structure

```
traekik/
├── app/
│   ├── api/           # Flask API routes
│   ├── core/          # Core provider logic
│   └── main.py        # Application entry point
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

### Debug with VSCode

1. Stop production container:
```bash
docker-compose stop traefik-provider
```

2. Start in debug mode:
```bash
docker-compose run --rm --service-ports traefik-provider debug
```

3. Attach VSCode debugger to localhost:5679

## Architecture

```
┌─────────────────┐     SSH      ┌──────────────┐
│                 ├─────────────► │ Docker Host1 │
│  HTTP Provider  │               └──────────────┘
│                 │     SSH      ┌──────────────┐
│                 ├─────────────► │ Docker Host2 │
└────────┬────────┘               └──────────────┘
         │
         │ HTTP
         │ /api/traefik/config
         ▼
   ┌──────────┐
   │ Traefik  │
   └──────────┘
```

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