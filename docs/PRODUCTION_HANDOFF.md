# CIRISManager Production Deployment Handoff

## Executive Summary

CIRISManager is a lightweight container orchestration service that manages CIRIS AI agents. This document provides everything needed for a smooth production deployment handoff.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Production Server                          │
├─────────────────────┬──────────────────┬──────────────────────────┤
│   Nginx (80/443)    │  CIRISManager    │    Docker Daemon         │
│   - SSL Termination │  - Port 8888     │    - CIRIS Agents        │
│   - Reverse Proxy   │  - OAuth/JWT     │    - Containers          │
│   - Rate Limiting   │  - API Service   │    - Networks            │
└─────────────────────┴──────────────────┴──────────────────────────┘
```

## Pre-Production Validation

### 1. Infrastructure Validation

```bash
# System requirements check
cat > check_requirements.sh << 'EOF'
#!/bin/bash
echo "=== System Requirements Check ==="

# OS Check
echo -n "OS Version: "
lsb_release -d 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME

# Python Check
echo -n "Python Version: "
python3 --version

# Docker Check
echo -n "Docker Version: "
docker --version

# Memory Check
echo -n "Available Memory: "
free -h | grep Mem | awk '{print $7}'

# Disk Check
echo -n "Available Disk: "
df -h / | tail -1 | awk '{print $4}'

# Systemd Check
echo -n "Systemd Version: "
systemctl --version | head -1

# Port Check
echo "Port 8888 Status:"
netstat -tuln | grep 8888 || echo "Port 8888 is free"
EOF

chmod +x check_requirements.sh
./check_requirements.sh
```

### 2. Security Hardening

```bash
# Create security setup script
cat > security_setup.sh << 'EOF'
#!/bin/bash
# CIRISManager Security Hardening

# 1. Create dedicated user
sudo useradd -r -s /bin/false ciris-manager

# 2. Set file permissions
sudo chown -R ciris-manager:ciris-manager /opt/ciris-manager
sudo chmod 750 /opt/ciris-manager
sudo chmod 640 /etc/ciris-manager/config.yml

# 3. Configure firewall
sudo ufw allow 8888/tcp comment "CIRISManager API"
sudo ufw allow 22/tcp comment "SSH"
sudo ufw --force enable

# 4. Set up fail2ban for API
cat > /etc/fail2ban/jail.d/ciris-manager.conf << 'F2B'
[ciris-manager]
enabled = true
port = 8888
filter = ciris-manager
logpath = /var/log/ciris-manager/api.log
maxretry = 5
bantime = 3600
F2B

# 5. Configure AppArmor/SELinux (if applicable)
# Add profiles based on your security requirements
EOF

chmod +x security_setup.sh
```

## Production Deployment Steps

### Step 1: Initial Setup

```bash
# 1. Clone repository to production location
sudo git clone https://github.com/CIRISAI/ciris-manager.git /opt/ciris-manager
cd /opt/ciris-manager

# 2. Run production deployment script
sudo ./deployment/deploy.sh

# 3. Configure OAuth
sudo cat > /etc/ciris-manager/oauth_config.json << 'EOF'
{
  "client_id": "YOUR_OAUTH_CLIENT_ID",
  "client_secret": "YOUR_OAUTH_CLIENT_SECRET",
  "redirect_uri": "https://your-domain.com/manager/v1/auth/callback"
}
EOF

# 4. Update main configuration
sudo vim /etc/ciris-manager/config.yml
```

### Step 2: SSL/TLS Configuration

```nginx
# /etc/nginx/sites-available/ciris-manager
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    location /manager/ {
        proxy_pass http://localhost:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Step 3: Service Configuration

```bash
# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable ciris-manager.service
sudo systemctl enable ciris-manager-api.service
sudo systemctl start ciris-manager
sudo systemctl start ciris-manager-api

# Verify services
sudo systemctl status ciris-manager
sudo systemctl status ciris-manager-api
```

## Monitoring Setup

### 1. Health Check Monitoring

```bash
# Create health check script
cat > /opt/ciris-manager/monitoring/health_check.sh << 'EOF'
#!/bin/bash
ENDPOINT="http://localhost:8888/manager/v1/health"
SLACK_WEBHOOK="YOUR_SLACK_WEBHOOK_URL"

response=$(curl -s -o /dev/null -w "%{http_code}" $ENDPOINT)

if [ "$response" != "200" ]; then
    curl -X POST $SLACK_WEBHOOK \
      -H 'Content-type: application/json' \
      -d "{\"text\":\"⚠️ CIRISManager health check failed! Status: $response\"}"
fi
EOF

# Add to crontab
echo "*/5 * * * * /opt/ciris-manager/monitoring/health_check.sh" | sudo crontab -
```

### 2. Prometheus Metrics

```yaml
# prometheus.yml addition
scrape_configs:
  - job_name: 'ciris-manager'
    static_configs:
      - targets: ['localhost:8888']
    metrics_path: '/manager/v1/metrics'
```

### 3. Log Aggregation

```bash
# Configure rsyslog
cat > /etc/rsyslog.d/30-ciris-manager.conf << 'EOF'
if $programname == 'ciris-manager' then /var/log/ciris-manager/manager.log
if $programname == 'ciris-manager-api' then /var/log/ciris-manager/api.log
& stop
EOF

# Log rotation
cat > /etc/logrotate.d/ciris-manager << 'EOF'
/var/log/ciris-manager/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 640 ciris-manager ciris-manager
}
EOF
```

## Operational Procedures

### Daily Operations

```bash
# Morning health check
ciris-manager-health-check() {
    echo "=== CIRISManager Health Check ==="
    echo "System Status:"
    systemctl status ciris-manager --no-pager | head -10
    
    echo -e "\nAPI Health:"
    curl -s http://localhost:8888/manager/v1/health | jq .
    
    echo -e "\nActive Agents:"
    curl -s http://localhost:8888/manager/v1/agents | jq '.agents | length'
    
    echo -e "\nResource Usage:"
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"
}
```

### Agent Management

```bash
# Create new agent
create_agent() {
    local name=$1
    local template=${2:-basic}
    
    curl -X POST http://localhost:8888/manager/v1/agents \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"name\": \"$name\", \"template\": \"$template\"}"
}

# Delete agent
delete_agent() {
    local agent_id=$1
    
    curl -X DELETE http://localhost:8888/manager/v1/agents/$agent_id \
      -H "Authorization: Bearer $TOKEN"
}
```

### Backup Procedures

```bash
# Automated backup script
cat > /opt/ciris-manager/backup/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/backup/ciris-manager"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR/$DATE

# Backup agent data
tar -czf $BACKUP_DIR/$DATE/agents.tar.gz /opt/ciris-agents/

# Backup configuration
cp -r /etc/ciris-manager $BACKUP_DIR/$DATE/config

# Backup Docker volumes
for volume in $(docker volume ls -q | grep ciris); do
    docker run --rm -v $volume:/data -v $BACKUP_DIR/$DATE:/backup \
      alpine tar -czf /backup/${volume}.tar.gz -C /data .
done

# Cleanup old backups (keep 30 days)
find $BACKUP_DIR -type d -mtime +30 -exec rm -rf {} +

echo "Backup completed: $BACKUP_DIR/$DATE"
EOF

# Schedule daily backup
echo "0 2 * * * /opt/ciris-manager/backup/backup.sh" | crontab -
```

### Disaster Recovery

```bash
# Recovery procedure
recover_from_backup() {
    local backup_date=$1
    local backup_dir="/backup/ciris-manager/$backup_date"
    
    # Stop services
    sudo systemctl stop ciris-manager
    
    # Restore agent data
    sudo tar -xzf $backup_dir/agents.tar.gz -C /
    
    # Restore configuration
    sudo cp -r $backup_dir/config/* /etc/ciris-manager/
    
    # Restore Docker volumes
    for archive in $backup_dir/*.tar.gz; do
        volume=$(basename $archive .tar.gz)
        if [[ $volume != "agents" ]]; then
            docker volume create $volume
            docker run --rm -v $volume:/data -v $backup_dir:/backup \
              alpine tar -xzf /backup/${volume}.tar.gz -C /data
        fi
    done
    
    # Start services
    sudo systemctl start ciris-manager
}
```

## Performance Tuning

### System Optimization

```bash
# Sysctl tuning for production
cat > /etc/sysctl.d/99-ciris-manager.conf << 'EOF'
# Network performance
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535

# File descriptors
fs.file-max = 65535

# Memory
vm.swappiness = 10
EOF

sudo sysctl -p /etc/sysctl.d/99-ciris-manager.conf
```

### Docker Optimization

```json
# /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  },
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true"
  ]
}
```

## Troubleshooting Playbook

### Issue: Service Won't Start

```bash
# Diagnosis steps
sudo journalctl -u ciris-manager -n 100 --no-pager
sudo systemctl status ciris-manager
docker ps -a | grep ciris

# Common fixes
sudo chown -R ciris-manager:ciris-manager /opt/ciris-manager
sudo chmod 666 /var/run/docker.sock
sudo systemctl restart docker
```

### Issue: Authentication Failures

```bash
# Check OAuth configuration
cat /etc/ciris-manager/oauth_config.json | jq .

# Test OAuth endpoint
curl -I https://accounts.google.com/.well-known/openid-configuration

# Verify redirect URI matches OAuth app settings
grep redirect_uri /etc/ciris-manager/oauth_config.json
```

### Issue: High Memory Usage

```bash
# Identify memory consumers
docker stats --no-stream
ps aux | sort -k 6 -r | head -20

# Restart manager to clear caches
sudo systemctl restart ciris-manager

# Adjust container limits
docker update --memory="1g" --memory-swap="2g" <container_id>
```

## Handoff Checklist

### Documentation
- [ ] This production handoff document
- [ ] Architecture diagrams updated
- [ ] API documentation current
- [ ] Runbooks completed
- [ ] Incident response procedures

### Access & Security
- [ ] Production SSH keys distributed
- [ ] OAuth credentials secured in vault
- [ ] Admin accounts created
- [ ] Firewall rules configured
- [ ] SSL certificates installed

### Monitoring & Alerting
- [ ] Health checks configured
- [ ] Metrics collection active
- [ ] Log aggregation working
- [ ] Alerts configured
- [ ] On-call rotation set

### Operations
- [ ] Backup automation verified
- [ ] Recovery procedures tested
- [ ] Update process documented
- [ ] Performance baseline established
- [ ] Capacity planning completed

### Training
- [ ] Operations team trained
- [ ] Support documentation available
- [ ] Escalation paths defined
- [ ] Common issues documented
- [ ] Emergency contacts listed

## Support Contacts

- **Primary On-Call**: [Contact Info]
- **Escalation**: [Manager Contact]
- **Security Issues**: security@ciris.ai
- **GitHub Issues**: https://github.com/CIRISAI/ciris-manager/issues

## Final Notes

CIRISManager is designed for reliability and ease of operation. Key principles:

1. **Fail-Safe**: Crashes are handled gracefully
2. **Observable**: Comprehensive logging and metrics
3. **Recoverable**: All state can be reconstructed
4. **Scalable**: Handles 50+ agents per instance
5. **Secure**: OAuth + JWT + network isolation

For additional support, consult the CLAUDE.md file in the repository for development-specific guidance.