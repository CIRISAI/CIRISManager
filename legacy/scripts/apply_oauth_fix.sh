#!/bin/bash
# Apply the OAuth database write fix directly to production

echo "=== Applying OAuth fix to production ==="

# Add /var/lib/ciris-manager to ReadWritePaths
ssh root@108.61.119.117 "sed -i 's|ReadWritePaths=/opt/ciris/agents /var/log/ciris-manager /etc/ciris-manager /home/ciris/nginx|ReadWritePaths=/opt/ciris/agents /var/log/ciris-manager /etc/ciris-manager /home/ciris/nginx /var/lib/ciris-manager|' /etc/systemd/system/ciris-manager.service"

echo "=== Reloading systemd and restarting service ==="
ssh root@108.61.119.117 "systemctl daemon-reload && systemctl restart ciris-manager"

echo "=== Verifying fix applied ==="
ssh root@108.61.119.117 "grep ReadWritePaths /etc/systemd/system/ciris-manager.service"

echo "=== Service status ==="
ssh root@108.61.119.117 "systemctl status ciris-manager --no-pager | head -10"
