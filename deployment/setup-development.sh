#!/bin/bash
# Setup CIRISManager for local development
# This script sets up the development environment without systemd

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"; }

log "Setting up CIRISManager for development..."

# Check if we're in the right directory
if [ ! -f "setup.py" ] || [ ! -d "ciris_manager" ]; then
    error "This script must be run from the CIRISManager repository root"
    exit 1
fi

# Step 1: Create virtual environment
log "Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Step 2: Install dependencies
log "Installing Python dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e ".[dev]"

# Step 3: Create local config directory
log "Creating local configuration..."
mkdir -p config

if [ ! -f "config/dev.yml" ]; then
    # Generate development config
    python -m ciris_manager.cli --generate-config --config config/dev.yml

    # Adjust for local development
    sed -i 's|port: 9999|port: 8888|' config/dev.yml
    sed -i 's|/home/ciris/CIRISAgent/deployment/docker-compose.yml|./docker-compose.yml|' config/dev.yml

    log "Development configuration created at config/dev.yml"
else
    log "Development configuration already exists"
fi

# Step 4: Create development scripts
log "Creating development scripts..."

# Create run script for full manager
cat > run-manager.sh << 'EOF'
#!/bin/bash
source venv/bin/activate
export PYTHONPATH="$PWD:$PYTHONPATH"
exec python -m ciris_manager.cli --config config/dev.yml
EOF
chmod +x run-manager.sh


# Create test runner
cat > run-tests.sh << 'EOF'
#!/bin/bash
source venv/bin/activate
export PYTHONPATH="$PWD:$PYTHONPATH"

echo "Running linting..."
ruff check ciris_manager/
ruff format --check ciris_manager/

echo "Running type checking..."
mypy ciris_manager/

echo "Running tests..."
pytest tests/ -v
EOF
chmod +x run-tests.sh

# Step 5: Setup pre-commit hooks (optional)
if command -v pre-commit >/dev/null 2>&1; then
    log "Setting up pre-commit hooks..."
    cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.7.1
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
EOF
    pre-commit install
else
    log "Skipping pre-commit setup (pre-commit not installed)"
fi

# Step 6: Verify installation
log "Verifying installation..."
if python -c "import ciris_manager; print('✓ CIRISManager module imported successfully')"; then
    log "Installation verified!"
else
    error "Failed to import ciris_manager module"
    exit 1
fi

log "Development setup complete!"
echo ""
echo "Available commands:"
echo "  ./run-manager.sh    # Run full manager (watchdog + API)"
echo "  ./run-api.sh        # Run API server only"
echo "  ./run-tests.sh      # Run tests and linting"
echo ""
echo "Configuration file: config/dev.yml"
echo ""
echo "To start developing:"
echo "  1. Edit config/dev.yml to point to your docker-compose file"
echo "  2. Run ./run-api.sh to start the API server"
echo "  3. Access API at http://localhost:8888/manager/v1/system/health"
echo ""
