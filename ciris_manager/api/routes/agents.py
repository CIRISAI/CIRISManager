"""
Agent routes - discovery, lifecycle management, logs, maintenance.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles  # type: ignore
import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ciris_manager.models import CreateAgentRequest
from ciris_manager.utils.log_sanitizer import sanitize_agent_id

from ..rate_limit import create_limit
from .dependencies import get_manager, get_auth_dependency, resolve_agent
from .models import AgentListResponse, AgentResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])

# Get auth dependency based on mode
auth_dependency = get_auth_dependency()


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    manager: Any = Depends(get_manager),
) -> AgentListResponse:
    """List all managed agents by discovering Docker containers."""
    from ciris_manager.docker_discovery import DockerAgentDiscovery

    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()

    return AgentListResponse(agents=agents)


@router.get("/agents/versions")
async def get_agent_versions(
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get version information for all agents including version history.

    Returns version, codename, code hash, and version history for rollback.
    Uses DeploymentOrchestrator as single source of truth for version data.
    """
    from ciris_manager.deployment import get_deployment_orchestrator
    from ciris_manager.docker_discovery import DockerAgentDiscovery

    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()

    # Get version history from deployment orchestrator (single source of truth)
    deployment_orchestrator = get_deployment_orchestrator()

    # Build deployment options from all available deployments
    deployment_options: List[Dict[str, Any]] = []

    # Add current active deployment if exists
    current_deployment_data: Optional[Dict[str, Any]] = None
    if deployment_orchestrator.current_deployment:
        current = deployment_orchestrator.deployments.get(
            deployment_orchestrator.current_deployment
        )
        if current and current.notification and current.notification.agent_image:
            current_deployment_data = {
                "image": current.notification.agent_image,
                "tag": current.notification.version,
                "digest": current.notification.commit_sha,
                "deployed_at": current.started_at,
                "deployment_id": current.deployment_id,
                "status": "current",
            }
            deployment_options.append(current_deployment_data)

    # Add pending/staged deployments
    staged_deployment_data: Optional[Dict[str, Any]] = None
    for deployment_id, deployment in deployment_orchestrator.pending_deployments.items():
        if deployment.notification and deployment.notification.agent_image:
            staged_deployment_data = {
                "image": deployment.notification.agent_image,
                "tag": deployment.notification.version,
                "digest": deployment.notification.commit_sha,
                "staged_at": deployment.staged_at,
                "deployment_id": deployment_id,
                "status": "staged",
            }
            deployment_options.append(staged_deployment_data)
            break  # Use first pending deployment

    # Add deployments as rollback options
    completed_deployments: List[Dict[str, Any]] = []
    for deployment_id, deployment in deployment_orchestrator.deployments.items():
        if (
            deployment.status in ["completed", "failed", "cancelled", "rejected"]
            and deployment.notification
            and deployment.notification.agent_image
            and deployment.notification.version
            and deployment_id != deployment_orchestrator.current_deployment
        ):
            completed_deployments.append(
                {
                    "image": deployment.notification.agent_image,
                    "tag": deployment.notification.version,
                    "digest": deployment.notification.commit_sha,
                    "deployed_at": deployment.completed_at or deployment.started_at,
                    "deployment_id": deployment_id,
                    "status": "available"
                    if deployment.status == "completed"
                    else deployment.status,
                    "agents_updated": deployment.agents_updated,
                    "agents_total": deployment.agents_total,
                }
            )

    # Sort by completion time and take last 5
    completed_deployments.sort(key=lambda x: x["deployed_at"] or "", reverse=True)
    deployment_options.extend(completed_deployments[:5])

    # If no current deployment, use staged deployment as current for UI compatibility
    if not current_deployment_data and staged_deployment_data:
        current_deployment_data = staged_deployment_data.copy()
        current_deployment_data["status"] = "current"

    # Build version response
    agent_versions = []
    version_summary: Dict[str, int] = {}

    for agent in agents:
        agent_version = {
            "agent_id": agent.agent_id,
            "agent_name": agent.agent_name,
            "version": agent.version or "unknown",
            "codename": agent.codename or "unknown",
            "code_hash": agent.code_hash or "unknown",
            "status": agent.status,
        }
        agent_versions.append(agent_version)

        # Count versions for summary
        version_key = agent.version or "unknown"
        version_summary[version_key] = version_summary.get(version_key, 0) + 1

    return {
        "agents": agent_versions,
        "version_summary": version_summary,
        "total_agents": len(agents),
        "deployment_options": deployment_options,
        "agent": {
            "current": current_deployment_data,
            "staged": staged_deployment_data,
            "n_minus_1": completed_deployments[0] if len(completed_deployments) > 0 else None,
            "n_minus_2": completed_deployments[1] if len(completed_deployments) > 1 else None,
        },
        "gui": {
            "current": None,
            "staged": None,
            "n_minus_1": None,
            "n_minus_2": None,
        },
    }


@router.post("/agents/{agent_id}/deployment")
async def set_agent_deployment(
    agent_id: str,
    request: Dict[str, Any],
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Set the deployment identifier for an agent."""
    deployment = request.get("deployment")
    if not deployment:
        raise HTTPException(status_code=400, detail="Deployment field is required")

    # Resolve agent to ensure it exists
    _ = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

    # Update deployment using composite key
    if not manager.agent_registry.set_deployment(
        agent_id, deployment, occurrence_id=occurrence_id, server_id=server_id
    ):
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    return {"status": "success", "agent_id": agent_id, "deployment": deployment}


@router.get("/agents/by-deployment/{deployment}")
async def get_agents_by_deployment(
    deployment: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Get all agents with a specific deployment identifier."""
    agents = manager.agent_registry.get_agents_by_deployment(deployment)

    agent_list = []
    for agent in agents:
        agent_list.append(
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "template": agent.template,
                "port": agent.port,
                "deployment": deployment,
                "metadata": agent.metadata if hasattr(agent, "metadata") else {},
            }
        )

    return {"deployment": deployment, "agents": agent_list, "count": len(agent_list)}


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
) -> AgentResponse:
    """Get specific agent by ID with composite key support."""
    agent = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

    return AgentResponse(
        agent_id=agent.agent_id,
        name=agent.name,
        container=f"ciris-agent-{agent.agent_id}",
        port=agent.port,
        api_endpoint=f"http://localhost:{agent.port}",
        template=agent.template,
        status="running",
    )


@router.get("/agents/{agent_id}/access")
async def get_agent_access(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get access details for an agent including service token and database info.

    Returns connection details needed to interact with the agent directly.
    """
    from ciris_manager.crypto import get_token_encryption
    from ciris_manager.docker_discovery import DockerAgentDiscovery

    # Discover the agent
    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()

    # Filter by agent_id
    matching = [a for a in agents if a.agent_id == agent_id]
    if server_id:
        matching = [a for a in matching if a.server_id == server_id]
    if occurrence_id:
        matching = [a for a in matching if a.occurrence_id == occurrence_id]

    if not matching:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    agent = matching[0]

    # Build registry key to find service token
    # Key format: {agent_id}-{occurrence}-{server_id} or {agent_id}-{server_id}
    registry_keys_to_try = []
    if agent.occurrence_id:
        registry_keys_to_try.append(f"{agent_id}-{agent.occurrence_id}-{agent.server_id}")
    registry_keys_to_try.append(f"{agent_id}-{agent.server_id}")
    registry_keys_to_try.append(agent_id)

    # Find registry entry
    registry_entry = None
    registry_key_used = None
    for key in registry_keys_to_try:
        entry = manager.agent_registry.get_agent(key)
        if entry:
            registry_entry = entry
            registry_key_used = key
            break

    # Decrypt service token if available
    service_token = None
    if registry_entry and registry_entry.service_token:
        try:
            encryption = get_token_encryption()
            service_token = encryption.decrypt_token(registry_entry.service_token)
        except Exception as e:
            logger.warning(f"Failed to decrypt service token for {agent_id}: {e}")
            service_token = "[decryption failed]"

    # Get database info from container
    database_info = {}
    try:
        docker_client = manager.docker_client.get_client(agent.server_id or "main")
        container_name = agent.container_name or f"ciris-{agent_id}"
        container = docker_client.containers.get(container_name)

        # Get environment variables for database config
        env_vars = container.attrs.get("Config", {}).get("Env", [])
        env_dict = {}
        for env in env_vars:
            if "=" in env:
                k, v = env.split("=", 1)
                env_dict[k] = v

        # Check for PostgreSQL config - try multiple common env var names
        import re

        postgres_env_vars = [
            "CIRIS_DB_URL",
            "CIRIS_DATABASE_URL",
            "DATABASE_URL",
            "POSTGRES_URL",
            "PG_URL",
            "DB_URL",
        ]
        db_url = None
        db_env_var = None
        for env_var in postgres_env_vars:
            if env_dict.get(env_var):
                db_url = env_dict[env_var]
                db_env_var = env_var
                break

        if db_url and ("postgresql" in db_url or "postgres" in db_url):
            # Redact password in URL for display
            redacted_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", db_url)
            database_info = {
                "type": "postgresql",
                "url": redacted_url,
                "raw_url": db_url,  # Include full URL for actual access
                "env_var": db_env_var,
            }
        elif db_url:
            # Some other database URL
            redacted_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", db_url)
            database_info = {
                "type": "database",
                "url": redacted_url,
                "raw_url": db_url,
                "env_var": db_env_var,
            }
        else:
            # Default to SQLite
            # Get mount points to find data directory
            mounts = container.attrs.get("Mounts", [])
            data_mount = None
            for mount in mounts:
                if mount.get("Destination") == "/app/data":
                    data_mount = mount.get("Source")
                    break

            database_info = {
                "type": "sqlite",
                "path": f"{data_mount}/ciris_engine.db"
                if data_mount
                else "/app/data/ciris_engine.db",
                "container_path": "/app/data/ciris_engine.db",
            }
    except Exception as e:
        logger.warning(f"Failed to get database info for {agent_id}: {e}")
        database_info = {"error": str(e)}

    # Build server connection info
    server_config = None
    try:
        server_config = manager.docker_client.get_server_config(agent.server_id or "main")
    except Exception:
        pass

    # Build API endpoint URL
    if server_config and server_config.hostname:
        api_endpoint = f"https://{server_config.hostname}/api/{agent_id}/v1/"
    else:
        api_endpoint = f"https://agents.ciris.ai/api/{agent_id}/v1/"

    # Build SSH access info from known server IPs
    ssh_info = None
    if server_config:
        # Map server_id to public IP for SSH access
        server_ssh_ips = {
            "main": "45.76.231.182",
            "scout1": "144.202.55.195",
            "scout2": "45.76.18.133",
        }
        ssh_ip = server_ssh_ips.get(agent.server_id)
        if ssh_ip:
            ssh_info = {
                "command": f"ssh -i ~/.ssh/ciris_deploy root@{ssh_ip}",
                "ip": ssh_ip,
                "user": "root",
                "key": "~/.ssh/ciris_deploy",
            }

    return {
        "agent_id": agent_id,
        "registry_key": registry_key_used,
        "server_id": agent.server_id,
        "occurrence_id": agent.occurrence_id,
        "container_name": agent.container_name,
        "port": agent.api_port,
        "api_endpoint": api_endpoint,
        "service_token": service_token,
        "database": database_info,
        "server": {
            "hostname": server_config.hostname if server_config else None,
            "vpc_ip": server_config.vpc_ip if server_config else None,
        }
        if server_config
        else None,
        "ssh": ssh_info,
    }


@router.post("/agents", response_model=AgentResponse)
@create_limit
async def create_agent(
    request: Request,
    agent_request: CreateAgentRequest,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> AgentResponse:
    """Create a new agent."""
    try:
        # Check if template requires WA review (Tier 4/5)
        try:
            if not re.match(r"^[a-zA-Z0-9_-]+$", agent_request.template):
                raise HTTPException(status_code=400, detail="Invalid template name")

            templates_dir = Path(manager.config.manager.templates_directory)
            template_file = templates_dir / f"{agent_request.template}.yaml"

            template_file = template_file.resolve()
            templates_dir_resolved = templates_dir.resolve()
            if not str(template_file).startswith(str(templates_dir_resolved)):
                raise HTTPException(status_code=400, detail="Invalid template path")

            if template_file.exists():
                async with aiofiles.open(template_file, "r") as f:
                    content = await f.read()
                    template_data = yaml.safe_load(content)
                stewardship_tier = template_data.get("stewardship", {}).get("stewardship_tier", 1)

                if stewardship_tier >= 4:
                    if not agent_request.wa_review_completed:
                        raise HTTPException(
                            status_code=400,
                            detail=f"WA review confirmation required for Tier {stewardship_tier} agent",
                        )
                    logger.info(
                        f"WA review confirmed for Tier {stewardship_tier} agent '{agent_request.name}' "
                        f"(template: {agent_request.template}) by {user['email']}"
                    )
        except (TypeError, AttributeError) as e:
            logger.debug(f"Could not check template stewardship tier: {e}")
            pass

        result = await manager.create_agent(
            template=agent_request.template,
            name=agent_request.name,
            environment=agent_request.environment,
            wa_signature=agent_request.wa_signature,
            use_mock_llm=agent_request.use_mock_llm,
            enable_discord=agent_request.enable_discord,
            billing_enabled=agent_request.billing_enabled,
            billing_api_key=agent_request.billing_api_key,
            server_id=agent_request.server_id,
            database_url=agent_request.database_url,
            database_ssl_cert_path=agent_request.database_ssl_cert_path,
            agent_occurrence_id=agent_request.agent_occurrence_id,
        )

        logger.info(f"Agent {result['agent_id']} created by {user['email']}")

        return AgentResponse(
            agent_id=result["agent_id"],
            name=agent_request.name,
            container=result["container"],
            port=result["port"],
            api_endpoint=result["api_endpoint"],
            template=agent_request.template,
            status=result["status"],
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create agent: {e}")
        raise HTTPException(status_code=500, detail="Failed to create agent")


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, str]:
    """Delete an agent and clean up all resources."""
    try:
        _ = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)
    except HTTPException as e:
        if e.status_code == 404:
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery(
                manager.agent_registry, docker_client_manager=manager.docker_client
            )
            discovered_agents = discovery.discover_agents()

            discovered_agent = next((a for a in discovered_agents if a.agent_id == agent_id), None)
            if discovered_agent:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Agent '{agent_id}' was not created by CIRISManager. "
                        "Please stop it manually using docker-compose."
                    ),
                )
            else:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        else:
            raise

    success = await manager.delete_agent(agent_id)

    if success:
        logger.info(f"Agent {agent_id} deleted by {user['email']}")
        return {
            "status": "deleted",
            "agent_id": agent_id,
            "message": f"Agent {agent_id} and all its resources have been removed",
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete agent {agent_id}. Check logs for details.",
        )


@router.get("/agents/{agent_id}/logs")
async def get_agent_logs(
    agent_id: str,
    lines: int = 100,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    source: str = "all",
    manager: Any = Depends(get_manager),
    _user: dict = auth_dependency,
) -> PlainTextResponse:
    """
    Get logs for an agent.

    Args:
        agent_id: Agent identifier
        lines: Number of log lines to retrieve
        occurrence_id: Optional occurrence ID for multi-instance agents
        server_id: Optional server ID for multi-server agents
        source: Log source - "docker" (container stdout/stderr),
                "file" (application log files), or "all" (both, default)
    """
    try:
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        discovered_agent = next(
            (
                a
                for a in agents
                if a.agent_id == agent_id
                and (occurrence_id is None or a.occurrence_id == occurrence_id)
                and (server_id is None or a.server_id == server_id)
            ),
            None,
        )

        if not discovered_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        container_name = discovered_agent.container_name
        client = manager.docker_client.get_client(discovered_agent.server_id)

        all_logs = []

        try:
            container = client.containers.get(container_name)

            # Get docker container logs (stdout/stderr)
            if source in ("docker", "all"):
                try:
                    docker_logs = container.logs(tail=lines, timestamps=True).decode("utf-8")
                    if docker_logs.strip():
                        all_logs.append("=== DOCKER CONTAINER LOGS ===\n" + docker_logs)
                except Exception as e:
                    logger.warning(f"Failed to get docker logs for {container_name}: {e}")
                    if source == "docker":
                        raise

            # Get application log files
            if source in ("file", "all"):
                try:
                    # Find the latest ciris_agent log file
                    exit_code, output = container.exec_run(
                        "sh -c 'ls -t /app/logs/ciris_agent_*.log 2>/dev/null | head -1'",
                        demux=False,
                    )
                    if exit_code == 0 and output:
                        latest_log = output.decode("utf-8").strip()
                        if latest_log:
                            # Read the latest log file
                            exit_code, log_content = container.exec_run(
                                f"tail -n {lines} {latest_log}",
                                demux=False,
                            )
                            if exit_code == 0 and log_content:
                                content = log_content.decode("utf-8")
                                if content.strip():
                                    all_logs.append(
                                        f"=== APPLICATION LOG ({latest_log}) ===\n" + content
                                    )

                    # Also get incidents log if available
                    exit_code, output = container.exec_run(
                        "sh -c 'ls -t /app/logs/incidents_*.log 2>/dev/null | head -1'",
                        demux=False,
                    )
                    if exit_code == 0 and output:
                        incidents_log = output.decode("utf-8").strip()
                        if incidents_log:
                            exit_code, log_content = container.exec_run(
                                f"tail -n {lines} {incidents_log}",
                                demux=False,
                            )
                            if exit_code == 0 and log_content:
                                content = log_content.decode("utf-8")
                                if content.strip():
                                    all_logs.append(
                                        f"=== INCIDENTS LOG ({incidents_log}) ===\n" + content
                                    )

                except Exception as e:
                    logger.warning(f"Failed to get log files for {container_name}: {e}")
                    if source == "file":
                        raise

            if not all_logs:
                return PlainTextResponse(content="No logs available")

            return PlainTextResponse(content="\n\n".join(all_logs))

        except Exception as e:
            logger.warning(f"Failed to get logs for container {container_name}: {e}")
            raise HTTPException(
                status_code=404,
                detail=f"Container {container_name} not found or logs unavailable",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting logs for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/{agent_id}/logs/file/{filename}")
async def get_agent_log_file(
    agent_id: str,
    filename: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    _user: dict = auth_dependency,
) -> PlainTextResponse:
    """Get a specific log file from an agent container."""
    allowed_files = ["latest.log", "incidents_latest.log"]
    if filename not in allowed_files:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename. Allowed: {allowed_files}",
        )

    try:
        agent = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

        if agent.occurrence_id:
            container_name = f"ciris-{agent_id}-{agent.occurrence_id}"
        else:
            container_name = f"ciris-{agent_id}"

        client = manager.docker_client.get_client(agent.server_id)

        try:
            container = client.containers.get(container_name)
            exit_code, output = container.exec_run(
                f"cat /app/logs/{filename}",
                demux=False,
            )
            if exit_code != 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Log file {filename} not found in container {container_name}",
                )
            content = output.decode("utf-8") if isinstance(output, bytes) else output
            return PlainTextResponse(content=content)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Failed to get log file {filename} for container {container_name}: {e}")
            raise HTTPException(
                status_code=404,
                detail=f"Container {container_name} not found or log file unavailable: {e}",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting log file for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/{agent_id}/start")
async def start_agent(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, str]:
    """Start a stopped agent container using Docker."""
    try:
        import docker
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        discovered_agent = next(
            (
                a
                for a in agents
                if a.agent_id == agent_id
                and (occurrence_id is None or a.occurrence_id == occurrence_id)
                and (server_id is None or a.server_id == server_id)
            ),
            None,
        )

        if not discovered_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        container_name = discovered_agent.container_name

        registry_agent = manager.agent_registry.get_agent(
            agent_id, occurrence_id=occurrence_id, server_id=discovered_agent.server_id
        )

        client = manager.docker_client.get_client(discovered_agent.server_id)

        try:
            container = client.containers.get(container_name)

            if container.status == "running":
                return {
                    "status": "already_running",
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} is already running",
                    "container": container_name,
                }

            expected_image = "ghcr.io/cirisai/ciris-agent:latest"
            container_image = ""
            if container.image and container.image.tags:
                container_image = container.image.tags[0]

            if container_image != expected_image or (
                registry_agent and registry_agent.compose_file
            ):
                logger.info(
                    f"Container image changed from {container_image} to {expected_image}, recreating container"
                )

                if registry_agent and registry_agent.compose_file:
                    compose_path = Path(registry_agent.compose_file)
                    if compose_path.exists():
                        result = await asyncio.create_subprocess_exec(
                            "docker-compose",
                            "-f",
                            str(compose_path),
                            "up",
                            "-d",
                            "--pull",
                            "always",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await result.communicate()

                        if result.returncode == 0:
                            logger.info(
                                f"Agent {agent_id} recreated with new image by {user['email']}"
                            )
                            return {
                                "status": "success",
                                "agent_id": agent_id,
                                "message": f"Agent {agent_id} is starting with updated image",
                                "container": container_name,
                            }
                        else:
                            raise HTTPException(
                                status_code=500,
                                detail=f"Failed to recreate agent: {stderr.decode()}",
                            )
                else:
                    container.start()
            else:
                container.start()

            logger.info(f"Agent {agent_id} started by {user['email']}")

            return {
                "status": "success",
                "agent_id": agent_id,
                "message": f"Agent {agent_id} is starting",
                "container": container_name,
            }
        except docker.errors.NotFound:
            try:
                container = client.containers.get(f"ciris-{agent_id}")
                if container.status != "running":
                    container.start()
                return {
                    "status": "success",
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} is starting",
                }
            except docker.errors.NotFound:
                if registry_agent and registry_agent.compose_file:
                    compose_path = Path(registry_agent.compose_file)
                    if compose_path.exists():
                        result = await asyncio.create_subprocess_exec(
                            "docker-compose",
                            "-f",
                            str(compose_path),
                            "up",
                            "-d",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await result.communicate()

                        if result.returncode == 0:
                            return {
                                "status": "success",
                                "agent_id": agent_id,
                                "message": f"Agent {agent_id} is starting via docker-compose",
                            }
                        else:
                            raise HTTPException(
                                status_code=500,
                                detail=f"Failed to start agent: {stderr.decode()}",
                            )

                raise HTTPException(
                    status_code=404, detail=f"Container for agent '{agent_id}' not found"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start agent: {str(e)}")


@router.post("/agents/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, str]:
    """Force stop an agent container immediately using Docker."""
    try:
        import docker
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        discovered_agent = next(
            (
                a
                for a in agents
                if a.agent_id == agent_id
                and (occurrence_id is None or a.occurrence_id == occurrence_id)
                and (server_id is None or a.server_id == server_id)
            ),
            None,
        )

        if not discovered_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        container_name = discovered_agent.container_name
        client = manager.docker_client.get_client(discovered_agent.server_id)

        try:
            container = client.containers.get(container_name)
            container.stop(timeout=10)

            logger.info(f"Agent {agent_id} force stopped by {user['email']}")

            return {
                "status": "success",
                "agent_id": agent_id,
                "message": f"Agent {agent_id} has been stopped",
                "container": container_name,
            }
        except docker.errors.NotFound:
            try:
                container = client.containers.get(f"ciris-agent-{agent_id}")
                container.stop(timeout=10)
                return {
                    "status": "success",
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} has been stopped",
                }
            except docker.errors.NotFound:
                raise HTTPException(
                    status_code=404, detail=f"Container for agent '{agent_id}' not found"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop agent: {str(e)}")


@router.post("/agents/{agent_id}/shutdown")
async def request_shutdown_agent(
    agent_id: str,
    request: Dict[str, str],
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, str]:
    """Request a graceful shutdown of an agent with a reason."""
    try:
        agent = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

        reason = request.get("reason", "Operator requested shutdown")

        from ciris_manager.agent_auth import get_agent_auth

        auth = get_agent_auth()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                headers = auth.get_auth_headers(agent_id)

                server_config = manager.docker_client.get_server_config(agent.server_id)
                if server_config.is_local:
                    agent_url = f"http://localhost:{agent.port}"
                else:
                    agent_url = f"http://{server_config.vpc_ip}:{agent.port}"

                response = await client.post(
                    f"{agent_url}/v1/system/shutdown",
                    headers=headers,
                    json={"reason": reason},
                )

                if response.status_code == 200:
                    logger.info(
                        f"Shutdown requested for agent {agent_id} by {user['email']}: {reason}"
                    )
                    return {
                        "status": "success",
                        "agent_id": agent_id,
                        "message": f"Shutdown request sent to agent {agent_id}",
                        "reason": reason,
                    }
                else:
                    logger.warning(
                        f"Agent {sanitize_agent_id(agent_id)} returned {response.status_code} for shutdown request"
                    )
                    return {
                        "status": "accepted",
                        "agent_id": agent_id,
                        "message": "Agent may not support graceful shutdown, use force stop if needed",
                    }

            except httpx.ConnectError:
                return {
                    "status": "unreachable",
                    "agent_id": agent_id,
                    "message": "Agent is not responding, use force stop if needed",
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to request shutdown for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to request shutdown: {str(e)}")


@router.post("/agents/{agent_id}/restart")
async def restart_agent(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id_param: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, str]:
    """Restart an agent container using Docker."""
    try:
        import docker
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        discovered_agent = next(
            (
                a
                for a in agents
                if a.agent_id == agent_id
                and (occurrence_id is None or a.occurrence_id == occurrence_id)
                and (server_id_param is None or a.server_id == server_id_param)
            ),
            None,
        )

        if not discovered_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        container_name = discovered_agent.container_name
        server_id = discovered_agent.server_id

        client = manager.docker_client.get_client(server_id)

        try:
            container = client.containers.get(container_name)
            container.restart(timeout=30)

            logger.info(f"Agent {agent_id} restarted by {user['email']}")

            return {
                "status": "success",
                "agent_id": agent_id,
                "message": f"Agent {agent_id} is restarting",
                "container": container_name,
            }
        except docker.errors.NotFound:
            try:
                container = client.containers.get(f"ciris-{agent_id}")
                container.restart(timeout=30)

                logger.info(f"Agent {agent_id} restarted by {user['email']}")

                return {
                    "status": "success",
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} is restarting",
                    "container": f"ciris-{agent_id}",
                }
            except docker.errors.NotFound:
                raise HTTPException(
                    status_code=404, detail=f"Container for agent '{agent_id}' not found"
                )
        except docker.errors.APIError as e:
            logger.error(f"Docker API error restarting {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to restart container: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restart agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restart agent: {str(e)}")


@router.post("/agents/{agent_id}/maintenance")
async def set_agent_maintenance(
    agent_id: str,
    request: Dict[str, bool],
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, Any]:
    """Set maintenance mode for an agent to prevent automatic restart."""
    try:
        do_not_autostart = request.get("do_not_autostart", False)

        if not isinstance(do_not_autostart, bool):
            raise HTTPException(status_code=400, detail="do_not_autostart must be a boolean value")

        _ = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

        success = manager.agent_registry.set_do_not_autostart(
            agent_id, do_not_autostart, occurrence_id=occurrence_id, server_id=server_id
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        action = "enabled" if do_not_autostart else "disabled"
        logger.info(f"Maintenance mode {action} for {agent_id} by {user['email']}")

        return {
            "status": "success",
            "agent_id": agent_id,
            "do_not_autostart": do_not_autostart,
            "message": f"Maintenance mode {action} for agent {agent_id}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set maintenance mode for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set maintenance mode: {str(e)}")


@router.get("/agents/{agent_id}/maintenance")
async def get_agent_maintenance(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    _user: dict = auth_dependency,
) -> Dict[str, Any]:
    """Get maintenance mode status for an agent."""
    try:
        agent = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

        do_not_autostart = hasattr(agent, "do_not_autostart") and agent.do_not_autostart

        return {
            "agent_id": agent_id,
            "do_not_autostart": do_not_autostart,
            "maintenance_mode": "enabled" if do_not_autostart else "disabled",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get maintenance mode for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get maintenance mode: {str(e)}")
