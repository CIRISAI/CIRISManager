#!/usr/bin/env python3
"""
Script to delete and re-create scout agent on remote server.
Uses environment variables for secrets to avoid exposure in code.
"""

import os
import sys
import httpx
import time

# Configuration
MANAGER_URL = "http://localhost:8888"
AGENT_ID = "scout-u7e9s3"
TEMPLATE = "scout"
SERVER_ID = "scout"

# Get API keys from environment (optional for mock LLM mode)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# Use mock LLM if no API keys provided
USE_MOCK_LLM = not (GROQ_API_KEY and OPENAI_API_KEY)

if USE_MOCK_LLM:
    print("No API keys found - will use mock LLM mode")
else:
    print("API keys found - will use real LLM")


def get_manager_jwt():
    """Get JWT token from manager service file."""
    try:
        with open("/etc/systemd/system/ciris-manager.service", "r") as f:
            for line in f:
                if "MANAGER_JWT_SECRET" in line:
                    # Extract the secret value
                    secret = line.split("=", 1)[1].strip().strip('"')
                    return secret
    except Exception as e:
        print(f"Warning: Could not read JWT secret: {e}")
    return None


def call_api(method: str, endpoint: str, json_data=None, auth_header=None):
    """Make API call to manager."""
    url = f"{MANAGER_URL}/manager/v1/{endpoint}"
    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        if method == "GET":
            response = httpx.get(url, headers=headers, timeout=30.0)
        elif method == "DELETE":
            response = httpx.delete(url, headers=headers, timeout=30.0)
        elif method == "POST":
            response = httpx.post(url, json=json_data, headers=headers, timeout=60.0)
        else:
            raise ValueError(f"Unsupported method: {method}")

        return response
    except Exception as e:
        print(f"API call failed: {e}")
        return None


def main():
    print("=" * 60)
    print("Scout Agent Management Script")
    print("=" * 60)

    # Step 1: Check if agent exists
    print(f"\n[1/4] Checking if agent {AGENT_ID} exists...")
    response = call_api("GET", "agents")
    if response and response.status_code == 200:
        agents = response.json().get("agents", [])
        exists = any(a["agent_id"] == AGENT_ID for a in agents)
        if exists:
            print(f"✓ Agent {AGENT_ID} found")
        else:
            print(f"✗ Agent {AGENT_ID} not found")
    else:
        print("Warning: Could not check agents (auth may be required)")

    # Step 2: Delete existing agent
    print(f"\n[2/4] Deleting agent {AGENT_ID}...")
    # For dev mode, try without auth first
    response = call_api("DELETE", f"agents/{AGENT_ID}")
    if response and response.status_code in (200, 204):
        print(f"✓ Agent {AGENT_ID} deleted successfully")
        time.sleep(2)  # Wait for cleanup
    elif response and response.status_code == 404:
        print(f"✓ Agent {AGENT_ID} not found (already deleted)")
    else:
        status = response.status_code if response else "unknown"
        text = response.text if response else "no response"
        print(f"✗ Failed to delete agent (status: {status})")
        print(f"  Response: {text}")
        # Don't exit - try to create anyway

    # Step 3: Create new agent
    print(f"\n[3/4] Creating new scout agent on {SERVER_ID} server...")
    create_payload = {
        "template": TEMPLATE,
        "name": "scout-test",
        "server_id": SERVER_ID,
        "use_mock_llm": USE_MOCK_LLM,
        "environment": {
            "OAUTH_CALLBACK_BASE_URL": "https://scoutapi.ciris.ai",
        },
    }

    # Add real API keys if provided
    if not USE_MOCK_LLM:
        create_payload["environment"]["GROQ_API_KEY"] = GROQ_API_KEY
        create_payload["environment"]["OPENAI_API_KEY"] = OPENAI_API_KEY

    # Add Discord token if provided
    if DISCORD_TOKEN:
        create_payload["environment"]["DISCORD_BOT_TOKEN"] = DISCORD_TOKEN
        create_payload["enable_discord"] = True

    response = call_api("POST", "agents", json_data=create_payload)
    if response and response.status_code in (200, 201):
        result = response.json()
        new_agent_id = result.get("agent_id")
        print(f"✓ Agent created successfully: {new_agent_id}")
        print(f"  Port: {result.get('port')}")
        print(f"  Status: {result.get('status')}")

        # Step 4: Verify Docker labels
        print("\n[4/4] Verifying Docker labels...")
        time.sleep(5)  # Wait for container to start

        # SSH to scout server and check container labels
        import subprocess

        check_cmd = [
            "ssh",
            "-i",
            "/root/.ssh/ciris_deploy",
            "root@207.148.14.113",
            f"docker inspect ciris-{new_agent_id} --format='{{{{json .Config.Labels}}}}'",
        ]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            import json

            labels = json.loads(result.stdout.strip())
            if "ai.ciris.agents.id" in labels:
                print("✓ Docker labels present on container")
                print(f"  ai.ciris.agents.id: {labels.get('ai.ciris.agents.id')}")
                print(f"  ai.ciris.agents.template: {labels.get('ai.ciris.agents.template')}")
            else:
                print("✗ Docker labels MISSING from container!")
        else:
            print(f"✗ Could not check container labels: {result.stderr}")

    elif response and response.status_code == 401:
        print("✗ Authentication required - cannot create in production mode")
        print("  Manual intervention required: set auth.mode to 'development' temporarily")
        sys.exit(1)
    else:
        status = response.status_code if response else "unknown"
        text = response.text if response else "no response"
        print(f"✗ Failed to create agent (status: {status})")
        print(f"  Response: {text}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ Scout agent management complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
