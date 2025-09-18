# Docker Image Status

## Current Status: ✅ Published to GitHub Container Registry

The Docker image is now available at: **`ghcr.io/snadboy/sb-traefik-http-provider:latest`**

## Options to Use Published Image

### Option 1: GitHub Container Registry (Recommended)
```yaml
image: ghcr.io/snadboy/sb-traefik-http-provider:latest
```

**To publish to GHCR:**
1. Create new GitHub Personal Access Token with `write:packages` scope
2. Login: `docker login ghcr.io -u snadboy`
3. Tag: `docker tag snadboy/sb-traefik-http-provider:latest ghcr.io/snadboy/sb-traefik-http-provider:latest`
4. Push: `docker push ghcr.io/snadboy/sb-traefik-http-provider:latest`

### Option 2: Docker Hub
```yaml
image: snadboy/sb-traefik-http-provider:latest
```

**To publish to Docker Hub:**
1. Create Docker Hub account
2. Login: `docker login --username snadboy`
3. Push: `docker push snadboy/sb-traefik-http-provider:latest`

## Usage

The compose files now use the published image:

```yaml
image: ghcr.io/snadboy/sb-traefik-http-provider:latest
```

## Fallback Option

If you need to build locally, uncomment the build section:

```yaml
# build:
#   context: .
#   dockerfile: docker/Dockerfile.production
```

## Available Tags

- `latest` - Latest stable version
- `1.0.0` - Specific version 1.0.0