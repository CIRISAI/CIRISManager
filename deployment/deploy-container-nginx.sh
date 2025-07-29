#!/bin/bash
# Minimal deployment script for nginx container
# This runs ALONGSIDE system nginx for testing

set -e

echo "Deploying nginx container (test mode)..."

# Ensure docker-compose file exists
if [ ! -f "docker-compose.yml" ]; then
    echo "ERROR: docker-compose.yml not found"
    echo "Run from CIRISManager root directory"
    exit 1
fi

# Create network if it doesn't exist
docker network create ciris-network 2>/dev/null || true

# Start nginx container
echo "Starting nginx container on ports 8080/8443..."
docker-compose up -d nginx

# Wait for container to be healthy
echo "Waiting for nginx container to be ready..."
sleep 5

# Test container nginx
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health | grep -q "200"; then
    echo "✓ Container nginx is running on port 8080"
else
    echo "✗ Container nginx health check failed"
    exit 1
fi

echo ""
echo "Container nginx deployed successfully!"
echo "Test URLs:"
echo "  http://localhost:8080/manager/v1/health"
echo "  https://localhost:8443/manager/v1/health (self-signed cert warning expected)"
echo ""
echo "Production nginx still running on ports 80/443"