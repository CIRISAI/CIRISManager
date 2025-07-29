#!/bin/bash
# Production deployment script for CIRIS Manager
# This script automates the complete deployment process

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/CIRISAI/CIRISManager.git"
INSTALL_DIR="/opt/ciris-manager"
CONFIG_DIR="/etc/ciris-manager"
AGENT_DIR="/opt/ciris/agents"
LOG_DIR="/var/log/ciris-manager"
BACKUP_DIR="/var/backups/ciris-manager"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_error() {
    echo -e "${RED}[!]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[*]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

# Parse command line arguments
DOMAIN=""
EMAIL=""
VERSION="main"
SKIP_SSL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)
            DOMAIN="$2"
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --skip-ssl)
            SKIP_SSL=true
            shift
            ;;
        --help)
            echo "Usage: $0 --domain <domain> --email <email> [options]"
            echo ""
            echo "Options:"
            echo "  --domain <domain>    Your domain name (required)"
            echo "  --email <email>      Email for Let's Encrypt (required)"
            echo "  --version <tag>      Git tag/branch to deploy (default: main)"
            echo "  --skip-ssl           Skip SSL certificate setup"
            echo ""
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    print_error "Domain and email are required. Use --help for usage."
    exit 1
fi

echo "======================================"
echo "CIRIS Manager Production Deployment"
echo "======================================"
echo "Domain: $DOMAIN"
echo "Email: $EMAIL"
echo "Version: $VERSION"
echo "Skip SSL: $SKIP_SSL"
echo ""

read -p "Continue with deployment? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Deployment cancelled."
    exit 0
fi

# Step 1: System Prerequisites
print_status "Installing system prerequisites..."

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
if [[ "$PYTHON_VERSION" < "3.11" ]]; then
    print_error "Python 3.11+ required, found Python $PYTHON_VERSION"
    exit 1
fi

apt-get update
apt-get install -y \
    python3-venv \
    python3-pip \
    git \
    nginx \
    certbot \
    python3-certbot-nginx \
    curl \
    jq \
    logrotate

# Step 2: Create system user
print_status "Creating ciris-manager user..."
if ! id "ciris-manager" &>/dev/null; then
    useradd -r -s /bin/false -d /nonexistent -c "CIRIS Manager Service" ciris-manager
fi

# Add user to docker group
usermod -aG docker ciris-manager

# Step 3: Create directory structure
print_status "Creating directory structure..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$AGENT_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$BACKUP_DIR"
mkdir -p /etc/nginx/ciris-agents

# Set permissions
chown -R ciris-manager:ciris-manager "$INSTALL_DIR"
chown -R ciris-manager:ciris-manager "$CONFIG_DIR"
chown -R ciris-manager:ciris-manager "$AGENT_DIR"
chown -R ciris-manager:ciris-manager "$LOG_DIR"
chown -R ciris-manager:ciris-manager "$BACKUP_DIR"

# Step 4: Clone repository
print_status "Cloning repository..."
if [ -d "$INSTALL_DIR/.git" ]; then
    print_warning "Repository already exists, pulling latest changes..."
    cd "$INSTALL_DIR"
    git fetch --all
    git checkout "$VERSION"
    git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git checkout "$VERSION"
fi

# Fix git safe directory
git config --global --add safe.directory "$INSTALL_DIR"

# Step 5: Create Python virtual environment
print_status "Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/venv"
chown -R ciris-manager:ciris-manager "$INSTALL_DIR/venv"

# Install dependencies
print_status "Installing Python dependencies..."
sudo -u ciris-manager "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
sudo -u ciris-manager "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
sudo -u ciris-manager "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR"

# Step 6: Configure CIRIS Manager
print_status "Configuring CIRIS Manager..."

# Copy configuration template
if [ ! -f "$CONFIG_DIR/config.yml" ]; then
    cp "$INSTALL_DIR/deployment/config.production.yml" "$CONFIG_DIR/config.yml"
    
    # Update domain in config
    sed -i "s/your-domain.com/$DOMAIN/g" "$CONFIG_DIR/config.yml"
    
    print_warning "Please edit $CONFIG_DIR/config.yml with your specific settings"
fi

# Copy environment template
if [ ! -f "$CONFIG_DIR/environment" ]; then
    cp "$INSTALL_DIR/deployment/environment.production" "$CONFIG_DIR/environment"
    
    # Generate JWT secret
    JWT_SECRET=$(openssl rand -base64 32)
    sed -i "s/CHANGE_THIS_TO_RANDOM_SECRET/$JWT_SECRET/g" "$CONFIG_DIR/environment"
    
    print_warning "Please edit $CONFIG_DIR/environment with your OAuth credentials"
fi

# Set secure permissions
chmod 600 "$CONFIG_DIR/environment"
chown ciris-manager:ciris-manager "$CONFIG_DIR/environment"

# Step 7: Install systemd services
print_status "Installing systemd services..."
cp "$INSTALL_DIR/deployment/ciris-manager.service" /etc/systemd/system/
cp "$INSTALL_DIR/deployment/ciris-manager-api.service" /etc/systemd/system/
cp "$INSTALL_DIR/deployment/ciris-backup.service" /etc/systemd/system/
cp "$INSTALL_DIR/deployment/ciris-backup.timer" /etc/systemd/system/

# Copy monitoring services
cp "$INSTALL_DIR/deployment/ciris-health-check.service" /etc/systemd/system/ 2>/dev/null || true
cp "$INSTALL_DIR/deployment/ciris-health-check.timer" /etc/systemd/system/ 2>/dev/null || true

systemctl daemon-reload

# Step 8: Setup SSL (unless skipped)
if [ "$SKIP_SSL" = false ]; then
    print_status "Setting up SSL certificates..."
    
    # Check if certificates already exist
    if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        print_warning "SSL certificates already exist for $DOMAIN"
        print_status "Using existing certificates"
    else
        if [ -x "$INSTALL_DIR/deployment/setup-letsencrypt.sh" ]; then
            "$INSTALL_DIR/deployment/setup-letsencrypt.sh" "$DOMAIN" "$EMAIL"
        else
            print_warning "SSL setup script not found, skipping SSL setup"
        fi
    fi
else
    print_warning "Skipping SSL setup as requested"
fi

# Step 9: Configure nginx
print_status "Configuring nginx..."
if [ ! -f "/etc/nginx/sites-available/ciris-manager" ]; then
    cp "$INSTALL_DIR/deployment/nginx-ciris-manager.conf" /etc/nginx/sites-available/ciris-manager
    sed -i "s/your-domain.com/$DOMAIN/g" /etc/nginx/sites-available/ciris-manager
    ln -sf /etc/nginx/sites-available/ciris-manager /etc/nginx/sites-enabled/
fi

# Test nginx configuration
nginx -t || {
    print_error "Nginx configuration test failed!"
    exit 1
}

# Step 10: Setup monitoring
print_status "Setting up monitoring..."
if [ -x "$INSTALL_DIR/deployment/setup-monitoring.sh" ]; then
    "$INSTALL_DIR/deployment/setup-monitoring.sh"
fi

# Step 11: Setup log rotation
print_status "Configuring log rotation..."
cp "$INSTALL_DIR/deployment/logrotate-ciris" /etc/logrotate.d/ciris-manager 2>/dev/null || true

# Step 12: Copy utility scripts
print_status "Installing utility scripts..."
for script in backup-ciris.sh restore-ciris.sh ciris-status.sh; do
    if [ -f "$INSTALL_DIR/deployment/$script" ]; then
        cp "$INSTALL_DIR/deployment/$script" /usr/local/bin/
        chmod +x "/usr/local/bin/$script"
    fi
done

# Step 13: Enable services
print_status "Enabling services..."
systemctl enable ciris-manager.service
systemctl enable ciris-manager-api.service
systemctl enable ciris-backup.timer
systemctl enable nginx

# Step 14: Pre-flight checks
print_status "Running pre-flight checks..."

# Check configuration
print_status "Validating configuration..."
sudo -u ciris-manager "$INSTALL_DIR/venv/bin/python" -m ciris_manager.config.settings || {
    print_error "Configuration validation failed!"
    print_error "Please check $CONFIG_DIR/config.yml and $CONFIG_DIR/environment"
    exit 1
}

# Step 15: Start services
print_status "Starting services..."
systemctl start ciris-manager
sleep 2
systemctl start ciris-manager-api
systemctl start nginx

# Step 16: Verify deployment
print_status "Verifying deployment..."
sleep 5

# Check service status
SERVICES_OK=true
for service in ciris-manager ciris-manager-api nginx; do
    if systemctl is-active --quiet $service; then
        print_status "$service is running"
    else
        print_error "$service failed to start"
        SERVICES_OK=false
    fi
done

# Check health endpoint
if [ "$SERVICES_OK" = true ]; then
    print_status "Checking health endpoint..."
    HEALTH_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/manager/v1/health)
    if [ "$HEALTH_CHECK" = "200" ]; then
        print_status "Health check passed"
    else
        print_error "Health check failed (HTTP $HEALTH_CHECK)"
    fi
fi

# Final summary
echo ""
echo "======================================"
echo "Deployment Summary"
echo "======================================"
echo ""

if [ "$SERVICES_OK" = true ]; then
    print_status "CIRIS Manager deployed successfully!"
    echo ""
    echo "Access your installation at:"
    echo "  https://$DOMAIN"
    echo ""
    echo "Next steps:"
    echo "1. Edit configuration: $CONFIG_DIR/config.yml"
    echo "2. Set OAuth credentials: $CONFIG_DIR/environment"
    echo "3. Restart services: systemctl restart ciris-manager ciris-manager-api"
    echo "4. View logs: journalctl -u ciris-manager -u ciris-manager-api -f"
    echo "5. Check status: ciris-status.sh"
else
    print_error "Deployment completed with errors!"
    echo ""
    echo "Check logs for details:"
    echo "  journalctl -u ciris-manager -u ciris-manager-api -n 50"
fi