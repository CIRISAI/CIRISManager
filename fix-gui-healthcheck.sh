#!/bin/bash
# Fix ciris-gui health check by recreating container with wget-based health check
# This script fixes the zombie process accumulation issue

set -e

echo "🔧 Fixing ciris-gui health check..."

# Get current container details
CURRENT_IMAGE=$(docker inspect ciris-gui --format='{{.Config.Image}}')
CURRENT_PORTS=$(docker inspect ciris-gui --format='{{range $p, $conf := .NetworkSettings.Ports}}{{$p}} {{end}}')
CURRENT_VOLUMES=$(docker inspect ciris-gui --format='{{range .Mounts}}--volume={{.Source}}:{{.Destination}}{{if .Mode}}:{{.Mode}}{{end}} {{end}}')
CURRENT_ENV=$(docker inspect ciris-gui --format='{{range .Config.Env}}--env={{.}} {{end}}')

echo "📋 Current container details:"
echo "  Image: $CURRENT_IMAGE"
echo "  Network: host"

# Stop and remove current container
echo "🛑 Stopping current ciris-gui container..."
docker stop ciris-gui

echo "🗑️ Removing current ciris-gui container..."
docker rm ciris-gui

# Create new container with fixed health check
echo "🚀 Creating new ciris-gui container with fixed health check..."
docker run -d \
  --name ciris-gui \
  --network=host \
  --restart=unless-stopped \
  --health-cmd="wget --no-verbose --tries=1 --spider http://localhost:3000 || exit 1" \
  --health-interval=30s \
  --health-timeout=3s \
  --health-retries=3 \
  --health-start-period=5s \
  $CURRENT_IMAGE

# Wait for container to start
echo "⏳ Waiting for container to start..."
sleep 10

# Check health status
echo "🩺 Checking health status..."
HEALTH_STATUS=$(docker inspect ciris-gui --format='{{.State.Health.Status}}')
echo "  Health status: $HEALTH_STATUS"

if [ "$HEALTH_STATUS" = "starting" ] || [ "$HEALTH_STATUS" = "healthy" ]; then
    echo "✅ GUI container recreated successfully with fixed health check!"
    echo "🔄 The new health check uses wget instead of Node.js to prevent zombie process accumulation."

    # Show new health check configuration
    echo ""
    echo "📊 New health check configuration:"
    docker inspect ciris-gui | jq -r '.[0].Config.Healthcheck'
else
    echo "⚠️ Health check may still be initializing. Check status in a few minutes with:"
    echo "   docker inspect ciris-gui | jq -r '.[0].State.Health'"
fi

echo ""
echo "🎉 Fix complete! The GUI should now have a stable health check without zombie processes."
