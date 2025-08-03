#!/bin/bash
# Test if database is truly read-only

echo "=== Testing database write permissions ==="

# Test 1: Check systemd service protection settings
echo "1. Checking systemd ProtectHome setting:"
ssh root@108.61.119.117 "systemctl show ciris-manager | grep -E 'ProtectHome|ProtectSystem|ReadWritePaths'"

# Test 2: Check actual running process and its effective user
echo -e "\n2. Checking running process:"
ssh root@108.61.119.117 "ps aux | grep 'ciris-manager' | grep -v grep | grep -v journalctl"

# Test 3: Try to write to the database directly
echo -e "\n3. Testing direct database write:"
ssh root@108.61.119.117 "cd /var/lib/ciris-manager/.config/ciris-manager && sqlite3 auth.db 'SELECT COUNT(*) FROM users;' 2>&1"

# Test 4: Check if systemd is using DynamicUser
echo -e "\n4. Checking DynamicUser setting:"
ssh root@108.61.119.117 "systemctl show ciris-manager | grep -E 'DynamicUser|User|Group'"

# Test 5: Check actual file system mount options
echo -e "\n5. Checking filesystem mount:"
ssh root@108.61.119.117 "findmnt -T /var/lib/ciris-manager | grep -v TARGET"
