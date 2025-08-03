# Nginx Container Migration Guide

This guide explains how CIRISManager uses containerized nginx for production deployments.

## Overview

CIRISManager uses the pre-built nginx container from CIRISAgent (`ghcr.io/cirisai/ciris-nginx:latest`) to handle all HTTP/HTTPS routing. This provides:

- Consistent nginx configuration across deployments
- Easy SSL certificate management
- Dynamic routing updates for agents
- Better isolation and security

## Architecture

```
Internet → Nginx Container (80/443) → Routes:
  /manager/v1/*     → CIRISManager API (host:8888)
  /v1/*             → Default Agent (container:8080)
  /api/{agent}/v1/* → Other Agents (container:80XX)
  /                 → GUI (container:3000)
```

## Quick Start

1. **Deploy CIRISManager with nginx container:**
   ```bash
   cd /opt/ciris-manager
   sudo ./deployment/deploy-production.sh --domain your-domain.com --email your-email@example.com
   ```

2. **Verify nginx container is running:**
   ```bash
   docker ps | grep ciris-nginx
   ```

3. **Test the setup:**
   ```bash
   curl https://your-domain.com/manager/v1/health
   ```

## Manual Deployment

If you prefer manual setup:

1. **Ensure Docker is installed:**
   ```bash
   docker --version
   docker-compose --version
   ```

2. **Create Docker network:**
   ```bash
   docker network create ciris-network
   ```

3. **Start nginx container:**
   ```bash
   cd /opt/ciris-manager
   docker-compose up -d nginx
   ```

4. **Verify logs:**
   ```bash
   docker logs ciris-nginx
   ```

## Configuration

The nginx container expects:

1. **SSL Certificates** mounted at:
   - `/etc/letsencrypt:/etc/letsencrypt:ro`

2. **Manager routing config** at:
   - `/etc/nginx/conf.d/00-manager.conf`

3. **Environment variables:**
   - `MANAGER_HOST=host.docker.internal:8888`

See `docker-compose.yml` for the complete configuration.

## Migrating from System Nginx

If you have an existing system nginx installation:

1. **Stop system nginx:**
   ```bash
   sudo systemctl stop nginx
   sudo systemctl disable nginx
   ```

2. **Start container nginx:**
   ```bash
   docker-compose up -d nginx
   ```

3. **Update any custom configurations:**
   - Copy custom configs to `deployment/nginx-manager-routes.conf`
   - Restart container: `docker-compose restart nginx`

## Troubleshooting

### Container won't start
- Check ports 80/443 are free: `sudo lsof -i :80`
- Verify Docker network exists: `docker network ls`
- Check logs: `docker logs ciris-nginx`

### SSL certificate issues
- Ensure Let's Encrypt certificates exist
- Check mount paths in docker-compose.yml
- Verify certificate permissions

### Routing problems
- Check manager is running on port 8888
- Verify nginx config: `docker exec ciris-nginx nginx -t`
- Test from inside container: `docker exec ciris-nginx curl http://host.docker.internal:8888/manager/v1/health`

## Advanced Configuration

### Custom nginx configuration
Add custom location blocks to `deployment/nginx-manager-routes.conf`:

```nginx
location /custom-path/ {
    proxy_pass http://host.docker.internal:9000;
    proxy_set_header Host $host;
}
```

### Using a different nginx image
Update `docker-compose.yml`:

```yaml
services:
  nginx:
    image: your-registry/your-nginx:tag
    # ... rest of config
```

## Security Considerations

- SSL certificates are mounted read-only
- Container runs with minimal privileges
- Network isolation via Docker networks
- No direct host network access

## Contributing

When contributing nginx-related changes:

1. Update `docker-compose.yml` for container config
2. Update `deployment/nginx-manager-routes.conf` for routing
3. Test with both new and existing deployments
4. Document any new environment variables

## Support

For issues related to nginx container:
- Check [CIRISManager Issues](https://github.com/CIRISAI/CIRISManager/issues)
- Review [CIRISAgent nginx docs](https://github.com/CIRISAI/CIRISAgent/tree/main/docker/nginx)
- Join our Discord community
