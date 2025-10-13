#!/usr/bin/env python3
"""Deploy fix_agent_permissions.sh to scout server."""

import sys

sys.path.insert(0, "/opt/ciris-manager")

from pathlib import Path
from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.multi_server_docker import MultiServerDockerClient

# Load config
config = CIRISManagerConfig.from_file("/etc/ciris-manager/config.yml")
docker_client_manager = MultiServerDockerClient(config.servers)

# Get Docker client for scout server
docker_client = docker_client_manager.get_client("scout")

# Read the permission script
script_src = Path("/opt/ciris-manager/ciris_manager/templates/fix_agent_permissions.sh")
with open(script_src, "r") as f:
    script_content = f.read()

print("Deploying fix_agent_permissions.sh to scout server...")

# Create /home/ciris/shared directory
shared_dir_cmd = "mkdir -p /home/ciris/shared && chown 1000:1000 /home/ciris/shared"
try:
    nginx_container = docker_client.containers.get("ciris-nginx")
    exec_result = nginx_container.exec_run(f"sh -c '{shared_dir_cmd}'", user="root")
    if exec_result.exit_code != 0:
        print(f"Warning: Failed to create shared directory via nginx: {exec_result.output}")
        raise Exception("Try Alpine fallback")
except Exception:
    print("Using Alpine container for directory creation...")
    docker_client.containers.run(
        "alpine:latest",
        command=f"sh -c '{shared_dir_cmd}'",
        volumes={"/home/ciris": {"bind": "/home/ciris", "mode": "rw"}},
        remove=True,
        detach=False,
    )

# Write the script
script_path = "/home/ciris/shared/fix_agent_permissions.sh"
write_cmd = f"cat > {script_path} << 'EOFSCRIPT'\n{script_content}\nEOFSCRIPT\n"
write_cmd += f"chmod 755 {script_path}\n"
write_cmd += f"chown 1000:1000 {script_path}"

try:
    nginx_container = docker_client.containers.get("ciris-nginx")
    exec_result = nginx_container.exec_run(f"sh -c '{write_cmd}'", user="root")
    if exec_result.exit_code != 0:
        print(f"Warning: Failed to write script via nginx: {exec_result.output}")
        raise Exception("Try Alpine fallback")
except Exception:
    print("Using Alpine container for script deployment...")
    docker_client.containers.run(
        "alpine:latest",
        command=f"sh -c '{write_cmd}'",
        volumes={"/home/ciris": {"bind": "/home/ciris", "mode": "rw"}},
        remove=True,
        detach=False,
    )

print("✅ Script deployed successfully!")
