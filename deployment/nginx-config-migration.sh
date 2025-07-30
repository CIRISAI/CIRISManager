#!/bin/bash
# Nginx config migration script - Run on production server

echo "=== Nginx Config Migration ==="
echo "Moving nginx config from /home/ciris/nginx to /opt/ciris-manager/nginx"

# Create new directory
sudo mkdir -p /opt/ciris-manager/nginx
sudo chown ciris-manager:ciris-manager /opt/ciris-manager/nginx

# Copy existing config if it exists
if [ -f /home/ciris/nginx/nginx.conf ]; then
    echo "Copying existing nginx.conf..."
    sudo cp /home/ciris/nginx/nginx.conf /opt/ciris-manager/nginx/
    sudo chown ciris-manager:ciris-manager /opt/ciris-manager/nginx/nginx.conf
fi

# Update docker-compose for nginx container to mount from new location
echo ""
echo "IMPORTANT: Update your nginx container volume mount:"
echo "  FROM: /home/ciris/nginx/nginx.conf:/etc/nginx/nginx.conf:ro"
echo "  TO:   /opt/ciris-manager/nginx/nginx.conf:/etc/nginx/nginx.conf:ro"
echo ""
echo "Then restart nginx container to apply changes."

echo "Migration preparation complete!"