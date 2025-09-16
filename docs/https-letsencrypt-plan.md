# HTTPS and Let's Encrypt Implementation Plan

## Current Status
- Provider generates HTTP-only routes (port 80)
- No TLS configuration in generated routes
- No certificate resolver configured
- Caddy currently handling production traffic with HTTPS

## Implementation Phases

### Phase 1: Traefik Let's Encrypt Configuration
Update compose.yml to add:
```yaml
command:
  # Add to existing Traefik command section:
  - "--certificatesresolvers.letsencrypt.acme.email=your-email@example.com"
  - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
  - "--certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web"
  - "--certificatesresolvers.letsencrypt.acme.caserver=https://acme-staging-v02.api.letsencrypt.org/directory"  # Staging for testing
  # For production, use: https://acme-v02.api.letsencrypt.org/directory

volumes:
  - ./letsencrypt:/letsencrypt  # Certificate storage
```

### Phase 2: Provider HTTPS Support
Update app/core/provider.py build_traefik_config():
```python
# Line 246 - Update router configuration:
config['http']['routers'][router_name] = {
    'rule': f"Host(`{service_config['domain']}`)",
    'service': service_name,
    'entryPoints': ['web', 'websecure'],  # Add websecure
    'tls': {
        'certResolver': 'letsencrypt'  # Add TLS with Let's Encrypt
    }
}

# Add HTTP to HTTPS redirect middleware
if service_config.get('redirect_https', True):
    middleware_name = f"{service_name}-redirect-https"
    config['http']['middlewares'][middleware_name] = {
        'redirectScheme': {
            'scheme': 'https',
            'permanent': True
        }
    }
    # Add middleware to HTTP router
    http_router_name = f"{service_name}-http-router"
    config['http']['routers'][http_router_name] = {
        'rule': f"Host(`{service_config['domain']}`)",
        'service': service_name,
        'entryPoints': ['web'],
        'middlewares': [middleware_name]
    }
```

### Phase 3: Enhanced Labels (Optional)
Add support in extract_snadboy_revp_labels() for:
- `snadboy.revp.80.tls=true` (default: true)
- `snadboy.revp.80.redirect-https=true` (default: true)
- `snadboy.revp.80.tls-certresolver=letsencrypt` (default: letsencrypt)

### Phase 4: Testing Support
1. Use Let's Encrypt staging for testing
2. Test commands:
```bash
# Test HTTP routing
curl -H "Host: traefik-provider-api.isnadboy.com" http://localhost:80

# Test HTTPS (once configured)
curl -k -H "Host: traefik-provider-api.isnadboy.com" https://localhost:443

# Check certificate
openssl s_client -connect localhost:443 -servername traefik-provider-api.isnadboy.com
```

## Migration Strategy
1. Implement and test with Let's Encrypt staging
2. Verify all services get certificates
3. Switch to Let's Encrypt production
4. Test with local hosts file before DNS change
5. Update DNS from Caddy to Traefik

## Notes
- Let's Encrypt rate limits: 50 certificates per domain per week
- Use staging for all testing to avoid rate limits
- Certificates auto-renew 30 days before expiration
- Store acme.json securely (contains private keys)