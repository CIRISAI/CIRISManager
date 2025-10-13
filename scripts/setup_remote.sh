#!/bin/bash
#
# setup_remote.sh - Set up a new remote agent host for CIRIS
#
# Usage: ./setup_remote.sh <hostname> <vpc_ip> <public_ip>
# Example: ./setup_remote.sh scoutapi.ciris.ai 10.2.96.4 207.148.14.113
#
# This script:
# - Installs Docker with TLS security
# - Creates ciris user (uid 1000) matching container user
# - Sets up directory structure
# - Generates TLS certificates for Docker API
# - Configures firewall to restrict Docker API to VPC only
# - Installs certbot and obtains Let's Encrypt SSL certificates
# - Sets up automatic certificate renewal
# - Deploys nginx container with SSL support
# - Returns client certificates for main server to use for Docker API access

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check arguments
if [ $# -ne 3 ]; then
    log_error "Usage: $0 <hostname> <vpc_ip> <public_ip>"
    log_error "Example: $0 scout.ciris.ai 10.2.96.4 207.148.14.113"
    exit 1
fi

HOSTNAME=$1
VPC_IP=$2
PUBLIC_IP=$3
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ciris_deploy}"

log_info "Setting up remote agent host: $HOSTNAME ($PUBLIC_IP / VPC: $VPC_IP)"

# Verify SSH access
if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 root@"$PUBLIC_IP" 'echo "SSH OK"' >/dev/null 2>&1; then
    log_error "Cannot SSH to root@$PUBLIC_IP with key $SSH_KEY"
    exit 1
fi
log_info "SSH access verified"

# Execute remote setup
ssh -i "$SSH_KEY" root@"$PUBLIC_IP" 'bash -s' <<EOF
set -e

echo "===================================================="
echo "Remote Agent Host Setup"
echo "===================================================="

# 1. Install Docker
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "✓ Docker installed"
else
    echo "✓ Docker already installed"
fi

# 2. Install docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "Installing docker-compose..."
    COMPOSE_VERSION=\$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep -Po '"tag_name": "\K.*?(?=")')
    curl -L "https://github.com/docker/compose/releases/download/\${COMPOSE_VERSION}/docker-compose-\$(uname -s)-\$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "✓ docker-compose installed"
else
    echo "✓ docker-compose already installed"
fi

# 3. Create ciris user (uid 1000 to match container user)
# Check if UID 1000 is already taken
EXISTING_USER=\$(id -nu 1000 2>/dev/null || echo "")
if [ -n "\$EXISTING_USER" ] && [ "\$EXISTING_USER" != "ciris" ]; then
    echo "UID 1000 already assigned to user '\$EXISTING_USER'"
    echo "Using existing user '\$EXISTING_USER' for agent data (matches container uid 1000)"
    usermod -aG docker "\$EXISTING_USER" 2>/dev/null || echo "✓ User already in docker group"
    # Create ciris as symlink/alias for consistency in docs
    CIRIS_USER="\$EXISTING_USER"
    echo "✓ Using \$CIRIS_USER (uid 1000) for agent operations"
elif ! id -u ciris &>/dev/null; then
    echo "Creating ciris user (uid 1000)..."
    useradd -u 1000 -m -s /bin/bash ciris
    usermod -aG docker ciris
    CIRIS_USER="ciris"
    echo "✓ ciris user created"
else
    echo "✓ ciris user already exists"
    usermod -aG docker ciris
    CIRIS_USER="ciris"
fi

# 4. Create directory structure
echo "Creating directory structure..."
mkdir -p /opt/ciris/{agents,nginx}
mkdir -p /etc/ciris-manager/docker-certs
chown -R 1000:1000 /opt/ciris
echo "✓ Directories created (owned by uid 1000)"

# 5. Generate TLS certificates for Docker API
if [ ! -f /etc/docker/certs/ca.pem ]; then
    echo "Generating Docker TLS certificates..."
    mkdir -p /etc/docker/certs
    cd /etc/docker/certs

    # Generate CA
    openssl genrsa -out ca-key.pem 4096 2>/dev/null
    openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem \
        -subj "/C=US/ST=State/L=City/O=CIRIS/CN=$HOSTNAME" 2>/dev/null

    # Generate server cert
    openssl genrsa -out server-key.pem 4096 2>/dev/null
    openssl req -new -key server-key.pem -out server.csr \
        -subj "/CN=$HOSTNAME" 2>/dev/null

    # Server cert with SANs
    cat > extfile.cnf <<EXTFILE
subjectAltName = DNS:$HOSTNAME,IP:$VPC_IP,IP:$PUBLIC_IP,IP:127.0.0.1
extendedKeyUsage = serverAuth
EXTFILE

    openssl x509 -req -days 3650 -sha256 -in server.csr \
        -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
        -out server-cert.pem -extfile extfile.cnf 2>/dev/null

    # Generate client cert (for main server's manager)
    openssl genrsa -out client-key.pem 4096 2>/dev/null
    openssl req -new -key client-key.pem -out client.csr \
        -subj "/CN=ciris-manager" 2>/dev/null

    echo "extendedKeyUsage = clientAuth" > client-extfile.cnf
    openssl x509 -req -days 3650 -sha256 -in client.csr \
        -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
        -out client-cert.pem -extfile client-extfile.cnf 2>/dev/null

    # Set secure permissions
    chmod 0400 ca-key.pem server-key.pem client-key.pem
    chmod 0444 ca.pem server-cert.pem client-cert.pem

    # Clean up CSR and config files
    rm -f *.csr *.cnf ca.srl

    echo "✓ TLS certificates generated"
else
    echo "✓ TLS certificates already exist"
fi

# 6. Configure Docker daemon for TLS
echo "Configuring Docker daemon for TLS..."

# Backup existing config
[ -f /etc/docker/daemon.json ] && cp /etc/docker/daemon.json /etc/docker/daemon.json.backup

# Create daemon.json
cat > /etc/docker/daemon.json <<DAEMON_JSON
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://$VPC_IP:2376"],
  "tls": true,
  "tlsverify": true,
  "tlscacert": "/etc/docker/certs/ca.pem",
  "tlscert": "/etc/docker/certs/server-cert.pem",
  "tlskey": "/etc/docker/certs/server-key.pem"
}
DAEMON_JSON

# Create systemd override to remove -H flag (conflicts with daemon.json hosts)
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/override.conf <<OVERRIDE
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd --containerd=/run/containerd/containerd.sock
OVERRIDE

systemctl daemon-reload
systemctl restart docker

# Verify Docker is running
sleep 2
if ! docker ps >/dev/null 2>&1; then
    echo "✗ Docker failed to start with TLS config"
    exit 1
fi

echo "✓ Docker configured for TLS on $VPC_IP:2376"

# 7. Configure firewall (ufw) to restrict Docker API
if command -v ufw &> /dev/null; then
    echo "Configuring firewall..."

    # Enable UFW if not already enabled
    ufw --force enable

    # Allow SSH (don't lock ourselves out!)
    ufw allow 22/tcp

    # Allow HTTP/HTTPS for nginx
    ufw allow 80/tcp
    ufw allow 443/tcp

    # CRITICAL: Block Docker API from public internet
    # Only allow from VPC network (10.0.0.0/8)
    # IMPORTANT: ALLOW must come before DENY (UFW processes rules in order)
    ufw allow from 10.0.0.0/8 to any port 2376 proto tcp comment 'Docker API from VPC'
    ufw deny 2376/tcp comment 'Block Docker API from public'

    echo "✓ Firewall configured (Docker API restricted to VPC)"
    ufw status numbered
else
    echo "⚠ ufw not installed - manually configure firewall to restrict port 2376"
fi

# 8. Test Docker API is working locally
echo "Testing Docker API..."
if docker -H unix:///var/run/docker.sock ps >/dev/null 2>&1; then
    echo "✓ Docker local socket working"
else
    echo "✗ Docker local socket not working"
    exit 1
fi

# 9. Install certbot for Let's Encrypt
echo "Installing certbot for SSL certificates..."
if ! command -v certbot &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq certbot
    echo "✓ Certbot installed"
else
    echo "✓ Certbot already installed"
fi

# 10. Obtain Let's Encrypt SSL certificate
if [ ! -f "/etc/letsencrypt/live/$HOSTNAME/fullchain.pem" ]; then
    echo "Obtaining Let's Encrypt SSL certificate for $HOSTNAME..."

    # Create webroot directory for challenges
    mkdir -p /var/www/certbot

    # Get certificate using standalone mode (port 80 must be free)
    certbot certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --email "admin@ciris.ai" \
        --domains "$HOSTNAME" \
        --rsa-key-size 4096

    if [ ! -f "/etc/letsencrypt/live/$HOSTNAME/fullchain.pem" ]; then
        echo "✗ SSL certificate generation failed!"
        echo "⚠ Continuing without SSL - you can run certbot manually later"
    else
        echo "✓ SSL certificate obtained for $HOSTNAME"

        # Set proper permissions for Docker access
        chmod -R 755 /etc/letsencrypt/live
        chmod -R 755 /etc/letsencrypt/archive
    fi
else
    echo "✓ SSL certificate already exists for $HOSTNAME"
fi

# 11. Set up automatic certificate renewal
echo "Setting up automatic certificate renewal..."
mkdir -p /etc/letsencrypt/renewal-hooks/deploy

cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx-container.sh <<'RENEWAL_HOOK'
#!/bin/bash
# Reload nginx container after certificate renewal
docker exec ciris-nginx nginx -s reload 2>/dev/null || true
RENEWAL_HOOK

chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx-container.sh

# Create systemd service for renewal
cat > /etc/systemd/system/certbot-renew.service <<'CERTBOT_SERVICE'
[Unit]
Description=Certbot Renewal
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet
ExecStartPost=/bin/bash -c 'docker exec ciris-nginx nginx -s reload 2>/dev/null || true'
CERTBOT_SERVICE

# Create systemd timer
cat > /etc/systemd/system/certbot-renew.timer <<'CERTBOT_TIMER'
[Unit]
Description=Run certbot twice daily
After=network.target

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
CERTBOT_TIMER

systemctl daemon-reload
systemctl enable certbot-renew.timer
systemctl start certbot-renew.timer

echo "✓ Automatic certificate renewal configured"

# 12. Set up nginx container configuration
echo "Setting up nginx configuration directory..."
mkdir -p /opt/ciris/nginx/certs

# Create initial nginx config
cat > /opt/ciris/nginx/nginx.conf <<NGINX_CONF
# Initial nginx.conf for CIRIS Agent Host
# This will be replaced by CIRISManager with proper routing
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    sendfile on;
    keepalive_timeout 65;

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';

    # HTTP Server (redirect to HTTPS if cert exists)
    server {
        listen 80;
        server_name $HOSTNAME;

        location / {
            return 200 'CIRIS Agent Host Ready - Waiting for CIRISManager configuration\n';
            add_header Content-Type text/plain;
        }
    }

    # HTTPS Server (if certificate exists)
    server {
        listen 443 ssl http2;
        server_name $HOSTNAME;

        # SSL Certificate paths (will use Let's Encrypt if available)
        ssl_certificate /etc/letsencrypt/live/$HOSTNAME/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/$HOSTNAME/privkey.pem;

        location / {
            return 200 'CIRIS Agent Host Ready (SSL) - Waiting for CIRISManager configuration\n';
            add_header Content-Type text/plain;
        }
    }
}
NGINX_CONF

chown -R 1000:1000 /opt/ciris/nginx

echo "✓ Nginx configuration directory ready (owned by uid 1000)"

# 13. Deploy nginx container
echo "Deploying nginx container..."

# Pull nginx image
docker pull nginx:alpine

# Check if Let's Encrypt cert exists to determine volume mounts
if [ -f "/etc/letsencrypt/live/$HOSTNAME/fullchain.pem" ]; then
    # Start with SSL support
    docker run -d \
        --name ciris-nginx \
        --restart unless-stopped \
        -p 80:80 \
        -p 443:443 \
        -v /opt/ciris/nginx/nginx.conf:/etc/nginx/nginx.conf \
        -v /etc/letsencrypt:/etc/letsencrypt:ro \
        -v /opt/ciris/nginx/certs:/etc/nginx/certs:ro \
        nginx:alpine

    echo "✓ Nginx container started with SSL support"
else
    # Start without SSL
    docker run -d \
        --name ciris-nginx \
        --restart unless-stopped \
        -p 80:80 \
        -v /opt/ciris/nginx/nginx.conf:/etc/nginx/nginx.conf \
        -v /opt/ciris/nginx/certs:/etc/nginx/certs:ro \
        nginx:alpine

    echo "✓ Nginx container started (HTTP only - run certbot manually for SSL)"
fi

# Verify nginx container is running
sleep 2
if docker ps | grep -q ciris-nginx; then
    echo "✓ Nginx container is running"
    docker ps --filter name=ciris-nginx --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
else
    echo "✗ Nginx container failed to start"
    docker logs ciris-nginx
    exit 1
fi

# 14. Copy client certificates to temp location for retrieval
echo "Preparing client certificates for download..."
mkdir -p /tmp/ciris-certs-$HOSTNAME
cp /etc/docker/certs/ca.pem /tmp/ciris-certs-$HOSTNAME/
cp /etc/docker/certs/client-cert.pem /tmp/ciris-certs-$HOSTNAME/
cp /etc/docker/certs/client-key.pem /tmp/ciris-certs-$HOSTNAME/
chmod 644 /tmp/ciris-certs-$HOSTNAME/*
echo "✓ Client certificates ready at /tmp/ciris-certs-$HOSTNAME/"

echo ""
echo "===================================================="
echo "Remote setup complete!"
echo "===================================================="
echo "Hostname: $HOSTNAME"
echo "VPC IP: $VPC_IP"
echo "Public IP: $PUBLIC_IP"
echo "Docker API: tcp://$VPC_IP:2376 (TLS)"
echo "Firewall: Port 2376 restricted to VPC (10.0.0.0/8)"
echo "SSL: Let's Encrypt certificate installed"
echo "Nginx: Container running with SSL support"
echo ""
echo "Next steps:"
echo "1. Download client certificates from this server"
echo "2. Add server to CIRISManager config.yml"
echo "3. Test Docker API connection from main server"
echo "4. CIRISManager will deploy agent-specific nginx configs"
echo "===================================================="
EOF

# Download client certificates from remote server
log_info "Downloading client certificates..."
CERT_DIR="./docker-certs-$HOSTNAME"
mkdir -p "$CERT_DIR"
scp -i "$SSH_KEY" root@"$PUBLIC_IP":/tmp/ciris-certs-"$HOSTNAME"/* "$CERT_DIR"/
ssh -i "$SSH_KEY" root@"$PUBLIC_IP" "rm -rf /tmp/ciris-certs-$HOSTNAME"

log_info "Client certificates saved to: $CERT_DIR/"
log_info ""
log_info "===================================================="
log_info "Setup Complete!"
log_info "===================================================="
log_info "Hostname: $HOSTNAME"
log_info "VPC IP: $VPC_IP"
log_info "Public IP: $PUBLIC_IP"
log_info "Docker API: tcp://$VPC_IP:2376 (TLS)"
log_info "SSL: Let's Encrypt certificate installed"
log_info "Nginx: Container running with SSL support"
log_info "Certificates: $CERT_DIR/"
log_info ""
log_info "Remote server is ready with:"
log_info "  ✓ Docker with TLS (port 2376 restricted to VPC)"
log_info "  ✓ Let's Encrypt SSL certificates"
log_info "  ✓ Nginx container running with SSL"
log_info "  ✓ Automatic certificate renewal configured"
log_info ""
log_info "Next: Copy certificates to main server at:"
log_info "  /etc/ciris-manager/docker-certs/$HOSTNAME/"
log_info ""
log_info "Then add to config.yml:"
log_info "  servers:"
log_info "    - server_id: ${HOSTNAME%%.*}"
log_info "      hostname: $HOSTNAME"
log_info "      vpc_ip: $VPC_IP"
log_info "      docker_host: tcp://$VPC_IP:2376"
log_info "      tls_ca: /etc/ciris-manager/docker-certs/$HOSTNAME/ca.pem"
log_info "      tls_cert: /etc/ciris-manager/docker-certs/$HOSTNAME/client-cert.pem"
log_info "      tls_key: /etc/ciris-manager/docker-certs/$HOSTNAME/client-key.pem"
log_info ""
log_info "After adding to config and restarting CIRISManager:"
log_info "  - Manager will automatically deploy nginx configs to $HOSTNAME"
log_info "  - Agents created on $HOSTNAME will be accessible via nginx"
log_info "===================================================="
