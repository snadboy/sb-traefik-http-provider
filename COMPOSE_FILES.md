# Docker Compose Files Guide

## Production Setup (NAS-based)

### 1. Initialize NAS Volume (run once)
```bash
docker-compose -f volume-init-compose.yml up
```
This creates the `nas-data` NFS volume that connects to your NAS.

### 2. Deploy Production Stack
```bash
docker-compose -f compose.production-nas.yml up -d
```

## File Structure

### Production Files
- **`volume-init-compose.yml`** - Creates NAS volume (run once)
- **`compose.production-nas.yml`** - Production deployment with NAS storage
- **`.env`** - Contains `CF_DNS_API_TOKEN` for Cloudflare

### Development Files
- **`compose.development.yml`** - Local development with build context
- **`compose.production.yml`** - Legacy production file (deprecated)

## Key Differences

### Production (compose.production-nas.yml)
- Uses pre-built image from GHCR
- All config/logs/ssh-keys on NAS via subpaths
- Let's Encrypt certs in local volume (permission requirements)
- Requires NAS volume initialization

### Development (compose.development.yml)
- Builds image locally
- Mounts source code for live editing
- Uses local directories
- Includes debug port (5679)

## Storage Layout

### NAS Storage (`nas-data` volume)
```
/var/nfs/shared/docker/switchboard/data/
├── sb-traefik-http-provider/
│   ├── config/          # Provider config files
│   ├── logs/            # Application logs
│   └── ssh-keys/        # SSH keys (read-only)
└── traefik/
    └── traefik-dynamic/ # Dynamic config files
```

### Local Storage
```
letsencrypt-data         # Docker volume for acme.json (local only)
```

## Important Notes

1. **Let's Encrypt certificates** are stored locally, not on NAS, due to ACME's strict permission requirements (600 on acme.json)
2. **SSH keys** are copied from NAS to container during startup
3. **Cloudflare token** must be set in `.env` file
4. **NAS volume** must be created before first deployment

## Migration from Old Setup

If migrating from local directories to NAS:
1. Copy your config files to NAS paths
2. Copy SSH keys to NAS
3. Run volume init
4. Deploy with production-nas compose
5. Let's Encrypt certs will regenerate automatically