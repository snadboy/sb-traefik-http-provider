# Docker Image Status

## Current Status: Building from Source

The Docker image is currently configured to **build from source** rather than pull from a registry.

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

## Current Working Solution

The compose files are configured to build locally:

```yaml
build:
  context: .
  dockerfile: docker/Dockerfile.production
```

This works immediately without requiring published images.

## Next Steps

1. Publish image to GHCR or Docker Hub
2. Update compose files to use published image
3. Remove build context and use `image:` directive