#!/bin/bash
# Quick start script for development setup
# This script sets up a development environment and runs basic tests

set -e

echo "🚀 CIRISManager Quick Start"
echo "=========================="
echo ""

# Check Python version
echo "📍 Checking Python version..."
if ! python3 -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)"; then
    echo "❌ Python 3.11+ is required"
    exit 1
fi
echo "✅ Python $(python3 --version)"

# Check Docker
echo ""
echo "📍 Checking Docker..."
if ! command -v docker &> /dev/null; then
    echo "⚠️  Docker not found (optional, but needed for full functionality)"
else
    echo "✅ Docker $(docker --version)"
fi

# Create virtual environment
echo ""
echo "📍 Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Activate and install
echo ""
echo "📍 Installing dependencies..."
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]"
echo "✅ Dependencies installed"

# Run basic tests
echo ""
echo "📍 Running basic tests..."
pytest tests/ciris_manager/test_config_settings.py -v -q
echo "✅ Basic tests passed"

# Set up local development config
echo ""
echo "📍 Setting up local development environment..."
if [ ! -f "config.yml" ]; then
    cp config.example.yml config.yml
    # Update config for local development
    mkdir -p local-data/agents
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' 's|/opt/ciris-agents|./local-data/agents|g' config.yml
    else
        sed -i 's|/opt/ciris-agents|./local-data/agents|g' config.yml
    fi
    echo "✅ Local config created"
else
    echo "✅ Config file already exists"
fi

# Show available commands
echo ""
echo "🎉 Setup complete! Here are some useful commands:"
echo ""
echo "  make test      - Run all tests"
echo "  make test-cov  - Run tests with coverage"
echo "  make lint      - Check code style"
echo "  make format    - Format code"
echo "  make run-api   - Start the API server"
echo ""
echo "📚 Next steps:"
echo "  1. Your config.yml is ready for local development"
echo "  2. Run 'export CIRIS_MANAGER_CONFIG=$(pwd)/config.yml'"
echo "  3. For dev mode: 'export CIRIS_AUTH_MODE=development'"
echo "  4. Try 'make run-api' to start the server"
echo ""
echo "💡 Tips:"
echo "  - Development mode skips OAuth authentication"
echo "  - Check docs/API.md for endpoint documentation"
echo "  - Run 'make test-cov' to see test coverage (target: 80%+)"
echo ""
echo "Happy coding! 🎈"
