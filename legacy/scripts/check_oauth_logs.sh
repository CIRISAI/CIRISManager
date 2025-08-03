#!/bin/bash
# Check production OAuth failure logs

echo "=== Checking CIRISManager API logs for OAuth errors ==="
ssh root@108.61.119.117 "journalctl -u ciris-manager-api -n 100 --no-pager | grep -E 'oauth|OAuth|callback|500|ERROR|error' | tail -20"

echo -e "\n=== Checking nginx access logs for OAuth callbacks ==="
ssh root@108.61.119.117 "docker logs ciris-nginx --tail 50 2>&1 | grep -E 'oauth/callback|manager/callback|500' | tail -10"

echo -e "\n=== Current CIRISManager service status ==="
ssh root@108.61.119.117 "systemctl status ciris-manager-api --no-pager | head -15"

echo -e "\n=== Checking if OAuth environment variables are set ==="
ssh root@108.61.119.117 "grep -E 'GOOGLE_CLIENT|JWT_SECRET' /etc/systemd/system/ciris-manager-api.service || echo 'No OAuth env vars found in service file'"

echo -e "\n=== Recent OAuth-related errors (last hour) ==="
ssh root@108.61.119.117 "journalctl -u ciris-manager-api --since '1 hour ago' --no-pager | grep -iE 'oauth|google|callback|auth.*failed|500.*internal' | tail -20"
