"""
Admin actions routes.

This module provides endpoints for executing infrastructure-level actions on agents:
- identity-update: Update agent identity from template (modifies compose, restarts)
- restart: Restart agent container
- pull-image: Pull latest agent image

Note: Agent-side actions (pause/resume/flush-cache) must go through the H3ERE pipeline.
The manager cannot force agent behavior - only infrastructure operations are allowed.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .dependencies import get_manager, auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


class AdminActionType(str, Enum):
    """Available admin actions.

    These are manager-side infrastructure actions only.
    Agent-side actions (pause/resume/etc) must go through the H3ERE pipeline.
    """

    IDENTITY_UPDATE = "identity-update"
    RESTART = "restart"
    PULL_IMAGE = "pull-image"


class AdminActionRequest(BaseModel):
    """Request body for admin actions."""

    action: AdminActionType
    params: Optional[Dict[str, Any]] = None
    force: bool = False


class AdminActionResponse(BaseModel):
    """Response from admin action."""

    success: bool
    action: str
    agent_id: str
    message: str
    details: Optional[Dict[str, Any]] = None


async def _get_agent_client_info(manager: Any, agent_id: str) -> tuple[str, Dict[str, str], Any]:
    """Get the base URL and auth headers for an agent."""
    from ciris_manager.docker_discovery import DockerAgentDiscovery
    from ciris_manager.agent_auth import get_agent_auth

    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()
    agent = next((a for a in agents if a.agent_id == agent_id), None)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    try:
        auth = get_agent_auth()
        headers = auth.get_auth_headers(
            agent.agent_id,
            occurrence_id=agent.occurrence_id,
            server_id=agent.server_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    try:
        server_config = manager.docker_client.get_server_config(agent.server_id)
        if server_config.is_local:
            base_url = f"http://localhost:{agent.api_port}"
        else:
            base_url = f"http://{server_config.vpc_ip}:{agent.api_port}"
    except Exception:
        base_url = f"http://localhost:{agent.api_port}"

    return base_url, headers, agent


@router.get("/agents/{agent_id}/admin/actions")
async def list_available_actions(
    agent_id: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """List available admin actions for an agent."""
    # Verify agent exists
    _, _, agent = await _get_agent_client_info(manager, agent_id)

    actions = [
        {
            "action": "identity-update",
            "description": "Update agent identity from template (requires restart)",
            "params": {"template": "optional template name override"},
            "requires_restart": True,
        },
        {
            "action": "restart",
            "description": "Restart agent container",
            "params": {"pull_image": "whether to pull latest image first"},
            "requires_restart": True,
        },
        {
            "action": "pull-image",
            "description": "Pull latest agent image without restart",
            "params": {},
            "requires_restart": False,
        },
    ]

    return {"agent_id": agent_id, "actions": actions}


@router.post("/agents/{agent_id}/admin/actions")
async def execute_admin_action(
    agent_id: str,
    request: AdminActionRequest,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> AdminActionResponse:
    """
    Execute an administrative action on an agent.

    Manager-side actions (identity-update, restart, pull-image) are handled
    by the manager and may require container operations.

    Agent-side actions (pause, resume, etc.) are proxied to the agent's API.
    """
    base_url, headers, agent = await _get_agent_client_info(manager, agent_id)
    params = request.params or {}

    try:
        if request.action == AdminActionType.IDENTITY_UPDATE:
            return await _handle_identity_update(manager, agent, params, request.force)

        elif request.action == AdminActionType.RESTART:
            return await _handle_restart(manager, agent, params)

        elif request.action == AdminActionType.PULL_IMAGE:
            return await _handle_pull_image(manager, agent)

        else:
            raise HTTPException(
                status_code=400, detail=f"Unknown action: {request.action}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to execute action {request.action} on {agent_id}")
        raise HTTPException(
            status_code=500, detail=f"Action failed: {str(e)}"
        )


async def _handle_identity_update(
    manager: Any, agent: Any, params: Dict[str, Any], force: bool
) -> AdminActionResponse:
    """Handle identity-update action by modifying compose and restarting."""
    import yaml

    agent_id = agent.agent_id
    server_id = agent.server_id
    occurrence_id = getattr(agent, "occurrence_id", None)
    template = params.get("template")

    # Get agent directory - use occurrence_id and server_id for multi-occurrence agents
    agent_info = manager.agent_registry.get_agent(
        agent_id, occurrence_id=occurrence_id, server_id=server_id
    )
    if not agent_info:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not in registry")

    # Determine compose file path
    if server_id == "main":
        compose_dir = Path(manager.config.manager.agents_directory) / agent_id
    else:
        # Remote server - need to handle via docker client
        compose_dir = Path(f"/opt/ciris/agents/{agent_id}")

    compose_path = compose_dir / "docker-compose.yml"

    # Get docker client for the server
    docker_client = manager.docker_client.get_client(server_id)
    server_config = manager.docker_client.get_server_config(server_id)

    # Read current compose file
    if server_config.is_local:
        if not compose_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Compose file not found: {compose_path}"
            )
        with open(compose_path) as f:
            compose_config = yaml.safe_load(f)
    else:
        # Remote: read compose file using a temporary container with host filesystem access
        try:
            compose_file_path = f"/opt/ciris/agents/{agent_id}/docker-compose.yml"
            # Run a temporary alpine container with the agents directory mounted
            result = docker_client.containers.run(
                "alpine:latest",
                f"cat {compose_file_path}",
                volumes={"/opt/ciris/agents": {"bind": "/opt/ciris/agents", "mode": "ro"}},
                remove=True,
                detach=False,
            )
            compose_content = result.decode() if result else ""
            compose_config = yaml.safe_load(compose_content)
            if not compose_config:
                raise HTTPException(
                    status_code=404,
                    detail=f"Compose file not found or empty at {compose_file_path}",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to read remote compose file: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to read compose file: {e}"
            )

    # Find the service and update command
    services = compose_config.get("services", {}) if compose_config else {}
    service_name = list(services.keys())[0] if services else agent_id
    service = services.get(service_name, {})

    command = service.get("command", [])
    if isinstance(command, str):
        command = command.split()

    # Add --identity-update if not present
    if "--identity-update" not in command:
        # Find position after main.py
        insert_pos = 1
        for i, arg in enumerate(command):
            if "main.py" in arg:
                insert_pos = i + 1
                break
        command.insert(insert_pos, "--identity-update")

        # Optionally override template
        if template:
            # Update --template argument
            for i, arg in enumerate(command):
                if arg == "--template" and i + 1 < len(command):
                    command[i + 1] = template
                    break

        service["command"] = command
        compose_config["services"][service_name] = service

        # Write updated compose file
        if server_config.is_local:
            with open(compose_path, "w") as f:
                yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)
        else:
            # Remote: write via temporary container with host filesystem access
            import base64
            compose_yaml = yaml.dump(compose_config, default_flow_style=False, sort_keys=False)
            encoded = base64.b64encode(compose_yaml.encode()).decode()
            compose_file_path = f"/opt/ciris/agents/{agent_id}/docker-compose.yml"
            docker_client.containers.run(
                "alpine:latest",
                f"sh -c 'echo {encoded} | base64 -d > {compose_file_path}'",
                volumes={"/opt/ciris/agents": {"bind": "/opt/ciris/agents", "mode": "rw"}},
                remove=True,
                detach=False,
            )

    # Pull latest image
    try:
        image_name = service.get("image", "ghcr.io/cirisai/ciris-agent:latest")
        docker_client.images.pull(image_name)
        logger.info(f"Pulled latest image: {image_name}")
    except Exception as e:
        logger.warning(f"Failed to pull image: {e}")

    # Restart container with force recreate
    container_name = f"ciris-{agent_id}"
    try:
        container = docker_client.containers.get(container_name)
        container.stop(timeout=30)
        container.remove()
    except Exception as e:
        logger.warning(f"Failed to stop/remove container: {e}")

    # Start new container via compose
    try:
        if server_config.is_local:
            import subprocess
            subprocess.run(
                ["docker", "compose", "up", "-d", "--force-recreate"],
                cwd=str(compose_dir),
                check=True,
                capture_output=True,
            )
        else:
            # Remote: use docker:cli container with socket and agents directory mounted
            compose_file_path = f"/opt/ciris/agents/{agent_id}/docker-compose.yml"
            docker_client.containers.run(
                "docker:cli",
                f"docker compose -f {compose_file_path} up -d --force-recreate",
                volumes={
                    "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                    "/opt/ciris/agents": {"bind": "/opt/ciris/agents", "mode": "rw"},
                },
                remove=True,
                detach=False,
            )
    except Exception as e:
        logger.error(f"Failed to start container: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restart: {e}")

    return AdminActionResponse(
        success=True,
        action="identity-update",
        agent_id=agent_id,
        message="Identity update triggered. Agent is restarting with --identity-update flag.",
        details={
            "compose_updated": True,
            "container_restarted": True,
            "template": template or "default",
        },
    )


async def _handle_restart(
    manager: Any, agent: Any, params: Dict[str, Any]
) -> AdminActionResponse:
    """Handle restart action."""
    agent_id = agent.agent_id
    server_id = agent.server_id
    pull_image = params.get("pull_image", True)

    docker_client = manager.docker_client.get_client(server_id)
    server_config = manager.docker_client.get_server_config(server_id)
    container_name = f"ciris-{agent_id}"

    # Optionally pull latest image
    if pull_image:
        try:
            container = docker_client.containers.get(container_name)
            image_name = container.image.tags[0] if container.image.tags else "ghcr.io/cirisai/ciris-agent:latest"
            docker_client.images.pull(image_name)
        except Exception as e:
            logger.warning(f"Failed to pull image: {e}")

    # Restart via compose
    try:
        if server_config.is_local:
            compose_dir = Path(manager.config.manager.agents_directory) / agent_id
            import subprocess
            subprocess.run(
                ["docker", "compose", "up", "-d", "--force-recreate"],
                cwd=str(compose_dir),
                check=True,
                capture_output=True,
            )
        else:
            # Remote: use docker:cli container with socket and agents directory mounted
            compose_file_path = f"/opt/ciris/agents/{agent_id}/docker-compose.yml"
            docker_client.containers.run(
                "docker:cli",
                f"docker compose -f {compose_file_path} up -d --force-recreate",
                volumes={
                    "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                    "/opt/ciris/agents": {"bind": "/opt/ciris/agents", "mode": "rw"},
                },
                remove=True,
                detach=False,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restart failed: {e}")

    return AdminActionResponse(
        success=True,
        action="restart",
        agent_id=agent_id,
        message="Agent restart initiated",
        details={"pulled_image": pull_image},
    )


async def _handle_pull_image(manager: Any, agent: Any) -> AdminActionResponse:
    """Handle pull-image action without restart."""
    agent_id = agent.agent_id
    server_id = agent.server_id

    docker_client = manager.docker_client.get_client(server_id)
    container_name = f"ciris-{agent_id}"

    try:
        container = docker_client.containers.get(container_name)
        image_name = container.image.tags[0] if container.image.tags else "ghcr.io/cirisai/ciris-agent:latest"
        docker_client.images.pull(image_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pull failed: {e}")

    return AdminActionResponse(
        success=True,
        action="pull-image",
        agent_id=agent_id,
        message=f"Pulled latest image",
        details={"image": image_name},
    )


