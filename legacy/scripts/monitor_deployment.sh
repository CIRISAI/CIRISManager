#!/bin/bash
# Quick deployment monitoring script

echo "=== Checking GitHub Actions deployment status ==="
gh run list --workflow=deploy-production.yml --limit=1 --json status,conclusion,displayTitle,startedAt

echo -e "\n=== Checking if systemd service was updated on production ==="
ssh root@108.61.119.117 "grep -n 'ReadWritePaths' /etc/systemd/system/ciris-manager.service | grep -c '/var/lib/ciris-manager' || echo '0 - Not deployed yet'"

echo -e "\n=== Current service status ==="
ssh root@108.61.119.117 "systemctl status ciris-manager --no-pager | head -10"

echo -e "\n=== Testing OAuth (last 5 minutes) ==="
ssh root@108.61.119.117 "journalctl -u ciris-manager --since '5 minutes ago' | grep -i oauth | tail -5"

echo -e "\n=== Quick OAuth test ==="
curl -s -o /dev/null -w "OAuth login endpoint: %{http_code}\n" https://agents.ciris.ai/manager/v1/oauth/login
