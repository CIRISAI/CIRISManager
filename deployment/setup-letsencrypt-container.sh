#!/bin/bash
# Setup Let's Encrypt SSL certificates for CIRIS Manager (Container nginx)
# Usage: ./setup-letsencrypt-container.sh your-domain.com your-email@domain.com

set -e

# Check arguments
if [ $# -ne 2 ]; then
    echo "Usage: $0 <domain> <email>"
    echo "Example: $0 ciris.example.com admin@example.com"
    exit 1
fi

DOMAIN=$1
EMAIL=$2

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "Setting up Let's Encrypt SSL for domain: $DOMAIN (container nginx)"

# Install certbot only (no nginx plugin needed)
echo "Installing certbot..."
apt-get update
apt-get install -y certbot

# Create webroot directory for challenges
mkdir -p /var/www/certbot

# Stop nginx container if running (to free port 80)
echo "Stopping nginx container if running..."
docker-compose down nginx 2>/dev/null || true

# Get initial certificate using standalone mode
echo "Obtaining SSL certificate..."
certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    --domains "$DOMAIN" \
    --keep-until-expiring \
    --rsa-key-size 4096

# Check if certificate was obtained
if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo "ERROR: Certificate generation failed!"
    exit 1
fi

echo "✓ SSL certificate obtained successfully!"

# Set proper permissions for Docker access
echo "Setting certificate permissions..."
chmod -R 755 /etc/letsencrypt/live
chmod -R 755 /etc/letsencrypt/archive

# Create renewal script for container nginx
echo "Creating renewal script..."
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx-container.sh << 'EOF'
#!/bin/bash
# Reload nginx container after certificate renewal
docker exec ciris-nginx nginx -s reload 2>/dev/null || true
EOF

chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx-container.sh

# Setup automatic renewal with systemd
echo "Setting up automatic renewal..."

# Create systemd service
cat > /etc/systemd/system/certbot-renew.service << EOF
[Unit]
Description=Certbot Renewal
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet
ExecStartPost=/bin/bash -c 'docker exec ciris-nginx nginx -s reload 2>/dev/null || true'
EOF

# Create systemd timer
cat > /etc/systemd/system/certbot-renew.timer << EOF
[Unit]
Description=Run certbot twice daily
After=network.target

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Enable timer
systemctl daemon-reload
systemctl enable certbot-renew.timer
systemctl start certbot-renew.timer

echo "✓ Automatic renewal configured"

# Start nginx container
echo "Starting nginx container..."
cd "$(dirname "$0")/.."
docker-compose up -d nginx

# Verify nginx is using the certificate
sleep 5
if docker exec ciris-nginx nginx -t 2>&1 | grep -q "syntax is ok"; then
    echo "✓ Nginx container configured correctly"
else
    echo "⚠ Warning: Nginx configuration test failed"
fi

echo ""
echo "=================================================="
echo "SSL Setup Complete!"
echo "=================================================="
echo "Domain: $DOMAIN"
echo "Certificate: /etc/letsencrypt/live/$DOMAIN/"
echo ""
echo "Test your SSL configuration at:"
echo "  https://www.ssllabs.com/ssltest/analyze.html?d=$DOMAIN"
echo ""
echo "Certificate will auto-renew via systemd timer"
echo "Check renewal status: systemctl status certbot-renew.timer"
