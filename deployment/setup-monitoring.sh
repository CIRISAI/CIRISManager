#!/bin/bash
# Setup monitoring for CIRIS Manager
# Configures log aggregation and health monitoring

set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "Setting up monitoring for CIRIS Manager..."

# Create log directories
echo "Creating log directories..."
mkdir -p /var/log/ciris-manager
chown ciris-manager:ciris-manager /var/log/ciris-manager

# Setup journald configuration
echo "Configuring systemd journal..."
mkdir -p /etc/systemd/journald.conf.d/
cp /opt/ciris-manager/deployment/journald-ciris.conf /etc/systemd/journald.conf.d/ciris-manager.conf
systemctl restart systemd-journald

# Create log export script
echo "Creating log export script..."
cat > /usr/local/bin/ciris-export-logs.sh << 'EOF'
#!/bin/bash
# Export CIRIS Manager logs for analysis

EXPORT_DIR="/var/log/ciris-manager/exports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$EXPORT_DIR"

# Export last 24 hours of logs
echo "Exporting CIRIS Manager logs..."
journalctl -u ciris-manager --since "24 hours ago" > "$EXPORT_DIR/ciris-manager_$TIMESTAMP.log"

# Compress logs
gzip "$EXPORT_DIR"/*.log

# Keep only last 30 days of exports
find "$EXPORT_DIR" -name "*.log.gz" -mtime +30 -delete

echo "Logs exported to: $EXPORT_DIR"
EOF

chmod +x /usr/local/bin/ciris-export-logs.sh

# Create health check script
echo "Creating health check script..."
cat > /usr/local/bin/ciris-health-check.sh << 'EOF'
#!/bin/bash
# Health check script for CIRIS Manager

HEALTH_ENDPOINT="http://localhost:8888/manager/v1/health"
TIMEOUT=5
LOG_FILE="/var/log/ciris-manager/health-check.log"

# Perform health check
response=$(curl -s -w "\n%{http_code}" --connect-timeout $TIMEOUT "$HEALTH_ENDPOINT" 2>/dev/null)
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | head -n -1)

timestamp=$(date '+%Y-%m-%d %H:%M:%S')

if [ "$http_code" = "200" ]; then
    echo "[$timestamp] Health check passed: $body" >> "$LOG_FILE"
    exit 0
else
    echo "[$timestamp] Health check failed: HTTP $http_code" >> "$LOG_FILE"
    
    # Check if services are running
    systemctl is-active --quiet ciris-manager || echo "[$timestamp] ciris-manager service is not running" >> "$LOG_FILE"
        
    exit 1
fi
EOF

chmod +x /usr/local/bin/ciris-health-check.sh

# Create monitoring systemd timer
echo "Setting up health check timer..."
cat > /etc/systemd/system/ciris-health-check.timer << EOF
[Unit]
Description=Run CIRIS health check every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/ciris-health-check.service << EOF
[Unit]
Description=CIRIS Manager Health Check
After=ciris-manager.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ciris-health-check.sh
User=ciris-manager
StandardOutput=journal
StandardError=journal
EOF

# Enable health check timer
systemctl daemon-reload
systemctl enable ciris-health-check.timer
systemctl start ciris-health-check.timer

# Create disk space monitoring
echo "Setting up disk space monitoring..."
cat > /usr/local/bin/ciris-disk-check.sh << 'EOF'
#!/bin/bash
# Check disk space for CIRIS Manager

THRESHOLD=90  # Alert if disk usage exceeds 90%
LOG_FILE="/var/log/ciris-manager/disk-check.log"

# Check main partition
usage=$(df / | awk 'NR==2 {print int($5)}')
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

if [ "$usage" -gt "$THRESHOLD" ]; then
    echo "[$timestamp] WARNING: Disk usage at $usage% (threshold: $THRESHOLD%)" >> "$LOG_FILE"
    
    # Log top space consumers
    echo "[$timestamp] Top directories by size:" >> "$LOG_FILE"
    du -h /opt/ciris/agents 2>/dev/null | sort -hr | head -5 >> "$LOG_FILE"
fi

# Check Docker disk usage
docker_usage=$(docker system df --format "table {{.Type}}\t{{.Size}}\t{{.Reclaimable}}" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "[$timestamp] Docker disk usage:" >> "$LOG_FILE"
    echo "$docker_usage" >> "$LOG_FILE"
fi
EOF

chmod +x /usr/local/bin/ciris-disk-check.sh

# Create log rotation configuration
echo "Setting up log rotation..."
cat > /etc/logrotate.d/ciris-manager << EOF
/var/log/ciris-manager/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 ciris-manager ciris-manager
    sharedscripts
    postrotate
        # Signal any processes that need to reopen log files
            endscript
}

/var/log/nginx/ciris-manager-*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 $(cat /var/run/nginx.pid)
    endscript
}
EOF

# Create monitoring dashboard script
echo "Creating monitoring dashboard..."
cat > /usr/local/bin/ciris-status.sh << 'EOF'
#!/bin/bash
# Display CIRIS Manager status

echo "=== CIRIS Manager Status ==="
echo

echo "Services:"
systemctl status ciris-manager --no-pager | grep -E "(Active:|Main PID:)"
echo

echo "Health Check:"
/usr/local/bin/ciris-health-check.sh && echo "API Health: OK" || echo "API Health: FAILED"
echo

echo "Resource Usage:"
echo -n "Memory: "
ps aux | grep -E "(ciris-manager|uvicorn)" | grep -v grep | awk '{sum+=$6} END {printf "%.1f MB\n", sum/1024}'
echo -n "Disk: "
df -h / | awk 'NR==2 {print $3 " / " $2 " (" $5 " used)"}'
echo

echo "Docker Containers:"
docker ps --filter "label=ciris.agent" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No agent containers running"
echo

echo "Recent Logs:"
journalctl -u ciris-manager --since "10 minutes ago" --no-pager | tail -10
EOF

chmod +x /usr/local/bin/ciris-status.sh

# Create alert script (can be integrated with monitoring systems)
echo "Creating alert script..."
cat > /usr/local/bin/ciris-alert.sh << 'EOF'
#!/bin/bash
# Send alerts for CIRIS Manager issues
# This is a template - integrate with your alerting system

ALERT_TYPE=$1
MESSAGE=$2
SEVERITY=${3:-warning}

# Example: Send to system log
logger -t ciris-alert -p user.$SEVERITY "$ALERT_TYPE: $MESSAGE"

# Example: Send email (configure mail system first)
# echo "$MESSAGE" | mail -s "CIRIS Alert: $ALERT_TYPE" ops@your-domain.com

# Example: Send to Slack webhook
# curl -X POST -H 'Content-type: application/json' \
#   --data "{\"text\":\"CIRIS Alert [$SEVERITY]: $ALERT_TYPE - $MESSAGE\"}" \
#   https://hooks.slack.com/services/YOUR/WEBHOOK/URL
EOF

chmod +x /usr/local/bin/ciris-alert.sh

echo ""
echo "Monitoring setup complete!"
echo ""
echo "Available commands:"
echo "  ciris-status.sh        - View current status"
echo "  ciris-health-check.sh  - Run health check"
echo "  ciris-export-logs.sh   - Export logs for analysis"
echo "  ciris-disk-check.sh    - Check disk usage"
echo "  ciris-alert.sh         - Send alerts (configure for your system)"
echo ""
echo "Health checks run automatically every 5 minutes"
echo "Logs are rotated daily and kept for 30 days"