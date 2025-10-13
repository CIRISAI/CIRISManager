#!/bin/bash
# Wrapper to run direct creation script with proper environment
set -e

# Source environment file
set -a
source /etc/ciris-manager/environment
set +a

# Run the Python script passed as argument (default to scout creation)
cd /opt/ciris-manager
python3 "${1:-/tmp/create_scout_agent_direct.py}"
