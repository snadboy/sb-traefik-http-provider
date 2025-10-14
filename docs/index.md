# SB Traefik HTTP Provider

A high-performance FastAPI-based HTTP provider for Traefik that discovers Docker containers across multiple SSH-accessible hosts.

## Key Features

- 🚀 **Multi-host Docker Discovery** - Monitor containers across multiple Docker hosts via SSH
- 🏷️ **Simplified Labels** - Use intuitive `snadboy.revp` labels instead of complex Traefik syntax
- 🔒 **HTTPS by Default** - Automatic Let's Encrypt certificates with wildcard support
- ⚡ **Real-time Updates** - Dynamic configuration updates as containers start/stop
- 📊 **Prometheus Metrics** - Built-in metrics export for monitoring
- 🛠️ **Easy Debugging** - VSCode remote debugging support

## Quick Start

### 1. Basic Setup

```bash
# Clone the repository
git clone https://github.com/snadboy/sb-traefik-http-provider.git
cd sb-traefik-http-provider

# Copy configuration examples
cp config/ssh-hosts.example.yaml config/ssh-hosts.yaml
cp .env.example .env

# Edit configurations with your settings
```

### 2. Run with Docker Compose

```bash
docker-compose up -d
```

### 3. Label Your Containers

```yaml
labels:
  - "snadboy.revp.80.domain=myapp.example.com"
  # That's it! HTTPS and redirect are automatic
```

## Label Reference

### Basic Web Application
```yaml
labels:
  - "snadboy.revp.80.domain=app.example.com"
```
Result: HTTPS with automatic redirect from HTTP

### HTTP-Only Service
```yaml
labels:
  - "snadboy.revp.80.domain=internal.example.com"
  - "snadboy.revp.80.https=false"
```

### Custom Backend Protocol
```yaml
labels:
  - "snadboy.revp.8080.domain=api.example.com"
  - "snadboy.revp.8080.backend-proto=https"
  - "snadboy.revp.8080.backend-path=/api/v1"
```

## Documentation

- [Installation Guide](installation.md) - Complete deployment instructions
- [Configuration Reference](configuration.md) - All configuration options
- [Label Documentation](labels.md) - Container labeling guide
- [API Reference](api.md) - REST API documentation
- [Troubleshooting](troubleshooting.md) - Common issues and solutions

## Links

- [GitHub Repository](https://github.com/snadboy/sb-traefik-http-provider)
- [Docker Hub](https://hub.docker.com/r/snadboy/sb-traefik-http-provider)
- [Issue Tracker](https://github.com/snadboy/sb-traefik-http-provider/issues)