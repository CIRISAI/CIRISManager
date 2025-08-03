#!/bin/bash
# Setup Let's Encrypt SSL certificates for CIRIS Manager
# Usage: ./setup-letsencrypt.sh your-domain.com your-email@domain.com

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

echo "Setting up Let's Encrypt SSL for domain: $DOMAIN"

# Install certbot and nginx plugin
echo "Installing certbot..."
apt-get update
apt-get install -y certbot python3-certbot-nginx

# Create webroot directory for challenges
mkdir -p /var/www/certbot

# Stop nginx if running (to avoid conflicts)
systemctl stop nginx || true

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

echo "Certificate obtained successfully!"

# Set up auto-renewal
echo "Setting up auto-renewal..."

# Create renewal hook script
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh << 'EOF'
#!/bin/bash
# Reload nginx after certificate renewal
systemctl reload nginx
EOF

chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

# Test renewal
echo "Testing certificate renewal..."
certbot renew --dry-run

# Create systemd timer for renewal (runs twice daily)
cat > /etc/systemd/system/certbot-renewal.timer << EOF
[Unit]
Description=Run certbot twice daily

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/certbot-renewal.service << EOF
[Unit]
Description=Renew Let's Encrypt certificates
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --deploy-hook "systemctl reload nginx"
EOF

# Enable and start the timer
systemctl daemon-reload
systemctl enable certbot-renewal.timer
systemctl start certbot-renewal.timer

echo "Auto-renewal configured successfully!"

# Update nginx configuration
echo "Updating nginx configuration..."

# Copy nginx config template and update domain
cp /opt/ciris-manager/deployment/nginx-ciris-manager.conf /etc/nginx/sites-available/ciris-manager
sed -i "s/your-domain.com/$DOMAIN/g" /etc/nginx/sites-available/ciris-manager

# Create directory for agent configs
mkdir -p /etc/nginx/ciris-agents

# Enable the site
ln -sf /etc/nginx/sites-available/ciris-manager /etc/nginx/sites-enabled/

# Disable default site if exists
rm -f /etc/nginx/sites-enabled/default

# Test nginx configuration
nginx -t

# Start nginx
systemctl start nginx
systemctl enable nginx

echo "Nginx configured and started!"

# Create security.txt
mkdir -p /opt/ciris-manager/static
cat > /opt/ciris-manager/static/security.txt << EOF
Contact: security@$DOMAIN
Expires: $(date -d '+1 year' --iso-8601)
Preferred-Languages: en
EOF

echo ""
echo "SSL setup complete! Your CIRIS Manager is now available at:"
echo "  https://$DOMAIN"
echo ""
echo "Certificate details:"
echo "  Certificate: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
echo "  Private Key: /etc/letsencrypt/live/$DOMAIN/privkey.pem"
echo ""
echo "Auto-renewal is configured to run twice daily."
echo "Check renewal status with: systemctl status certbot-renewal.timer"
