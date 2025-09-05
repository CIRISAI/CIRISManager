# CIRISManager Production Deployment - Quick Start

## Prerequisites
- Ubuntu/Debian server with Docker installed
- Domain name pointing to your server
- Let's Encrypt SSL already configured (certificates at `/etc/letsencrypt/`)

## Deploy in 3 Steps

### 1. Clone and Configure
```bash
# Clone the repository
cd /opt
sudo git clone https://github.com/CIRISAI/CIRISManager.git ciris-manager
cd ciris-manager

# Copy production config
sudo cp deployment/config.production.yml /etc/ciris-manager/config.yml

# Create environment file with your secrets
sudo nano /etc/ciris-manager/environment
```

Add to environment file:
```bash
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
MANAGER_JWT_SECRET=your-random-jwt-secret
```

### 2. Run Deployment Script
```bash
# Replace with your domain and email
sudo ./deployment/deploy-production.sh \
  --domain your-domain.com \
  --email your-email@example.com \
  --skip-ssl  # Since SSL is already configured
```

### 3. Verify
```bash
# Check services
docker ps | grep ciris
systemctl status ciris-manager-api

# Test endpoints
curl https://your-domain.com/manager/v1/health
```

## What Gets Deployed

- **CIRISManager API** - SystemD service on port 8888
- **Nginx Container** - Docker container handling all HTTP/HTTPS traffic
- **Auto-updates** - Disabled by default in production
- **Monitoring** - Health checks and systemd journal logging

## Quick Commands

```bash
# View logs
sudo journalctl -u ciris-manager-api -f
docker logs ciris-nginx -f

# Restart services
sudo systemctl restart ciris-manager-api
docker-compose restart nginx

# Update CIRISManager
cd /opt/ciris-manager
sudo git pull
sudo systemctl restart ciris-manager-api
```

## Troubleshooting

### Nginx container won't start
```bash
# Check if port 80/443 are free
sudo lsof -i :80
sudo lsof -i :443

# If system nginx is running, stop it
sudo systemctl stop nginx
sudo systemctl disable nginx
```

### SSL certificate issues
```bash
# Verify certificates exist
ls -la /etc/letsencrypt/live/your-domain.com/

# Check certificate expiry
sudo certbot certificates
```

### Manager API not responding
```bash
# Check if running
sudo systemctl status ciris-manager-api

# Check configuration
sudo /opt/ciris-manager/venv/bin/python -m ciris_manager.config.settings
```

## Next Steps

1. Configure Google OAuth for production
2. Create your first agent
3. Set up monitoring alerts
4. Join our Discord for support

---

For detailed documentation, see `docs/PRODUCTION_DEPLOYMENT.md`
