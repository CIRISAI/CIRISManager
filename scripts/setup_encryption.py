#!/usr/bin/env python3
"""
Set up encryption for CIRISManager service tokens.

This script:
1. Generates a new encryption key if needed
2. Migrates existing service tokens to encrypted format
3. Sets up the systemd service with the encryption key
"""

import os
import sys
import json
import base64
import subprocess
from pathlib import Path
from cryptography.fernet import Fernet


def generate_encryption_key():
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key().decode()


def get_service_token_from_container(container_name):
    """Get the service token from a running container."""
    try:
        result = subprocess.run(
            ["docker", "exec", container_name, "printenv", "CIRIS_SERVICE_TOKEN"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def main():
    """Main setup function."""
    print("=== CIRISManager Encryption Setup ===\n")

    # Check if running as root
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root")
        sys.exit(1)

    # Paths
    METADATA_PATH = Path("/opt/ciris/agents/metadata.json")
    SYSTEMD_SERVICE = Path("/etc/systemd/system/ciris-manager.service")

    # Check metadata exists
    if not METADATA_PATH.exists():
        print(f"ERROR: Metadata file not found at {METADATA_PATH}")
        sys.exit(1)

    # Load metadata
    with open(METADATA_PATH) as f:
        metadata = json.load(f)

    # Generate encryption key
    encryption_key = generate_encryption_key()
    print(f"Generated encryption key: {encryption_key[:20]}...")

    # Create cipher for encryption
    cipher = Fernet(encryption_key.encode())

    # Process each agent
    updated_count = 0
    for agent_id, agent_data in metadata.get("agents", {}).items():
        print(f"\nProcessing agent: {agent_id}")

        # Determine container name
        if agent_id == "datum":
            container_name = "ciris-datum"
        elif agent_id.startswith("sage-"):
            container_name = f"ciris-sage-{agent_id.split('-', 1)[1]}"
        else:
            container_name = f"ciris-{agent_id}"

        # Get service token from container
        token = get_service_token_from_container(container_name)

        if token:
            # Encrypt the token
            encrypted = cipher.encrypt(token.encode())
            # Store as base64-encoded string
            encrypted_b64 = base64.urlsafe_b64encode(encrypted).decode()

            # Update metadata
            agent_data["service_token"] = encrypted_b64
            agent_data["encrypted_service_token"] = True

            print(f"  ✓ Encrypted service token for {agent_id}")
            updated_count += 1
        else:
            print(f"  ⚠ Could not get service token for {agent_id} (container may not be running)")

    # Save updated metadata
    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✓ Updated {updated_count} service tokens in metadata.json")

    # Update systemd service with encryption key
    print(f"\nUpdating systemd service at {SYSTEMD_SERVICE}")

    # Read current service file
    with open(SYSTEMD_SERVICE) as f:
        service_content = f.read()

    # Check if Environment section exists
    if "[Service]" not in service_content:
        print("ERROR: Invalid systemd service file")
        sys.exit(1)

    # Add encryption key to environment
    if "CIRIS_ENCRYPTION_KEY=" not in service_content:
        # Find the [Service] section and add after it
        lines = service_content.split("\n")
        new_lines = []
        in_service_section = False
        env_added = False

        for line in lines:
            new_lines.append(line)
            if line.strip() == "[Service]":
                in_service_section = True
            elif (
                in_service_section
                and not env_added
                and (line.startswith("Type=") or line.startswith("ExecStart="))
            ):
                # Add environment variable before Type or ExecStart
                new_lines.insert(-1, f'Environment="CIRIS_ENCRYPTION_KEY={encryption_key}"')
                env_added = True

        service_content = "\n".join(new_lines)

        # Write updated service file
        with open(SYSTEMD_SERVICE, "w") as f:
            f.write(service_content)

        print("  ✓ Added CIRIS_ENCRYPTION_KEY to systemd service")
    else:
        print("  ⚠ CIRIS_ENCRYPTION_KEY already exists in service file")

    # Reload systemd and restart service
    print("\nReloading systemd and restarting CIRISManager...")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "restart", "ciris-manager"], check=True)

    print("\n✅ Encryption setup complete!")
    print("\nEncryption key has been added to the systemd service.")
    print("Service tokens have been encrypted in metadata.json")
    print("CIRISManager service has been restarted.")

    # Test the setup
    print("\n=== Testing Setup ===")
    subprocess.run(["systemctl", "status", "ciris-manager", "--no-pager", "-n", "5"])


if __name__ == "__main__":
    main()
