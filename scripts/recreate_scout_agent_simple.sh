#!/bin/bash
# Simple script to recreate scout agent by directly managing Docker containers
set -e

echo "============================================================"
echo " Recreate Scout Agent (Direct Docker Method)"
echo "============================================================"

SCOUT_HOST="root@207.148.14.113"
AGENT_ID="scout-u7e9s3"
CONTAINER_NAME="ciris-$AGENT_ID"

# Step 1: Stop and remove container on scout server
echo ""
echo "[1/3] Removing existing container on scout server..."
ssh -i /root/.ssh/ciris_deploy $SCOUT_HOST "docker stop $CONTAINER_NAME 2>/dev/null || true"
ssh -i /root/.ssh/ciris_deploy $SCOUT_HOST "docker rm $CONTAINER_NAME 2>/dev/null || true"
echo "✓ Container removed"

# Step 2: Delete agent from registry on main server
echo ""
echo "[2/3] Deleting agent from registry..."
# Manually edit metadata.json to remove the agent entry
# This is safer than trying to use the API
ssh -i /root/.ssh/ciris_deploy root@108.61.119.117 "cd /opt/ciris/agents && python3 -c \"
import json
with open('metadata.json', 'r') as f:
    data = json.load(f)

# Remove the scout agent
if '$AGENT_ID' in data.get('agents', {}):
    del data['agents']['$AGENT_ID']
    print('Removed $AGENT_ID from registry')
else:
    print('Agent $AGENT_ID not found in registry')

# Save back
with open('metadata.json', 'w') as f:
    json.dump(data, f, indent=2)
\""
echo "✓ Agent removed from registry"

# Step 3: Create new agent via API (using curl with no auth - relies on dev mode)
echo ""
echo "[3/3] Creating new scout agent..."
ssh -i /root/.ssh/ciris_deploy root@108.61.119.117 'curl -X POST http://localhost:8888/manager/v1/agents \
  -H "Content-Type: application/json" \
  -d "{
    \"template\": \"scout\",
    \"name\": \"scout-test\",
    \"server_id\": \"scout\",
    \"use_mock_llm\": true,
    \"environment\": {
      \"OAUTH_CALLBACK_BASE_URL\": \"https://scoutapi.ciris.ai\"
    }
  }" | jq .'

echo ""
echo "============================================================"
echo " ✅ Done! Check the output above for new agent ID"
echo "============================================================"
