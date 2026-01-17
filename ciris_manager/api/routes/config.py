"""
Config routes - agent configuration management.
"""

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict

import aiofiles
import yaml
from fastapi import APIRouter, Depends, HTTPException

from .dependencies import get_manager, get_auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])

# Get auth dependency based on mode
auth_dependency = get_auth_dependency()


@router.get("/agents/{agent_id}/config")
async def get_agent_config(
    agent_id: str,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, Any]:
    """Get agent configuration from docker-compose.yml."""
    try:
        # Validate agent_id to prevent directory traversal
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$", agent_id):
            raise HTTPException(status_code=400, detail="Invalid agent ID format")

        # Path to agent's docker-compose file
        base_path = Path("/opt/ciris/agents")
        compose_path = (base_path / agent_id / "docker-compose.yml").resolve()

        # Ensure the resolved path is still within the agents directory
        if not str(compose_path).startswith(str(base_path)):
            raise HTTPException(status_code=400, detail="Invalid agent path")

        if not compose_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Agent '{agent_id}' configuration not found"
            )

        # Read docker-compose.yml
        async with aiofiles.open(compose_path, "r") as f:
            content = await f.read()
            compose_data = yaml.safe_load(content)

        # Extract environment variables
        environment = {}
        if "services" in compose_data:
            for service in compose_data["services"].values():
                # First, load from env_file if specified
                if "env_file" in service:
                    env_files = service["env_file"]
                    if not isinstance(env_files, list):
                        env_files = [env_files]

                    for env_file in env_files:
                        env_file_path = compose_path.parent / env_file
                        if env_file_path.exists():
                            async with aiofiles.open(env_file_path, "r") as ef:
                                content = await ef.read()
                                for line in content.split("\n"):
                                    line = line.strip()
                                    if line and not line.startswith("#") and "=" in line:
                                        key, value = line.split("=", 1)
                                        # Remove quotes if present
                                        value = value.strip()
                                        if (value.startswith('"') and value.endswith('"')) or (
                                            value.startswith("'") and value.endswith("'")
                                        ):
                                            value = value[1:-1]
                                        environment[key.strip()] = value

                # Then, override with explicit environment variables
                if "environment" in service:
                    environment.update(service["environment"])
                break

        return {
            "agent_id": agent_id,
            "environment": environment,
            "compose_file": str(compose_path),
        }

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Configuration not found for agent '{agent_id}'"
        )
    except Exception as e:
        logger.error(f"Failed to get agent config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/agents/{agent_id}/config")
async def update_agent_config(
    agent_id: str,
    config_update: Dict[str, Any],
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, str]:
    """Update agent configuration by modifying docker-compose.yml."""
    try:
        # Validate agent_id to prevent directory traversal
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$", agent_id):
            raise HTTPException(status_code=400, detail="Invalid agent ID format")

        # Path to agent's docker-compose file
        base_path = Path("/opt/ciris/agents")
        compose_path = (base_path / agent_id / "docker-compose.yml").resolve()

        # Ensure the resolved path is still within the agents directory
        if not str(compose_path).startswith(str(base_path)):
            raise HTTPException(status_code=400, detail="Invalid agent path")

        if not compose_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Agent '{agent_id}' configuration not found"
            )

        # Read current docker-compose.yml
        async with aiofiles.open(compose_path, "r") as f:
            content = await f.read()
            compose_data = yaml.safe_load(content)

        # Update environment variables
        if "environment" in config_update:
            if "services" in compose_data:
                for service in compose_data["services"].values():
                    if "environment" in service:
                        # Special handling for CIRIS_ENABLE_DISCORD
                        if "CIRIS_ENABLE_DISCORD" in config_update["environment"]:
                            current_adapter = service["environment"].get("CIRIS_ADAPTER", "api")
                            adapters = [a.strip() for a in current_adapter.split(",")]

                            enable_discord = (
                                config_update["environment"]["CIRIS_ENABLE_DISCORD"] == "true"
                            )
                            if enable_discord:
                                if "discord" not in adapters:
                                    adapters.append("discord")
                            else:
                                if "discord" in adapters:
                                    adapters.remove("discord")

                            service["environment"]["CIRIS_ADAPTER"] = ",".join(adapters)
                            del config_update["environment"]["CIRIS_ENABLE_DISCORD"]

                        # Update other environment variables
                        for key, value in config_update["environment"].items():
                            if value is None or value == "":
                                service["environment"].pop(key, None)
                            else:
                                service["environment"][key] = value

        # Backup current config
        backup_path = compose_path.with_suffix(".yml.bak")

        try:
            async with aiofiles.open(compose_path, "r") as f:
                original_content = await f.read()

            try:
                async with aiofiles.open(backup_path, "w") as f:
                    await f.write(original_content)
            except PermissionError:
                logger.warning(
                    f"Could not create backup file at {backup_path} - continuing without backup"
                )
        except Exception as e:
            logger.warning(f"Could not read original file for backup: {e}")

        # Write updated docker-compose.yml
        content = yaml.dump(compose_data, default_flow_style=False, sort_keys=False)

        try:
            async with aiofiles.open(compose_path, "w") as f:
                await f.write(content)
        except PermissionError:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as tmp:
                tmp.write(content)
                temp_path = tmp.name

            try:
                shutil.move(temp_path, str(compose_path))
            except Exception as move_error:
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass
                raise RuntimeError(f"Failed to update config file: {move_error}")

        # Check if we should restart the container
        should_restart = config_update.get("restart", True)

        if should_restart:
            try:
                agent = manager.agent_registry.get_agent(agent_id)
            except Exception:
                agent = None

            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

            server_id = agent.server_id if hasattr(agent, "server_id") else "main"

            if server_id != "main":
                from ciris_manager.deployment import get_deployment_orchestrator

                orchestrator = get_deployment_orchestrator()
                success = await orchestrator._recreate_agent_container(
                    agent_id, server_id=server_id, new_image=None
                )
                if not success:
                    raise RuntimeError("Failed to recreate remote agent container")
            else:
                agent_dir = Path("/opt/ciris/agents") / agent_id
                proc = await asyncio.create_subprocess_exec(
                    "docker-compose",
                    "up",
                    "-d",
                    cwd=str(agent_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError(f"Failed to recreate container: {stderr.decode()}")

            logger.info(f"Agent {agent_id} config updated and restarted by {user['email']}")
            return {
                "status": "updated",
                "agent_id": agent_id,
                "message": "Configuration updated and container recreated",
            }
        else:
            logger.info(f"Agent {agent_id} config updated (no restart) by {user['email']}")
            return {
                "status": "updated",
                "agent_id": agent_id,
                "message": "Configuration saved. Changes will be applied on next restart.",
            }

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to recreate container: {e}")
        raise HTTPException(status_code=500, detail="Failed to apply configuration")
    except Exception as e:
        logger.error(f"Failed to update agent config: {e}")
        raise HTTPException(status_code=500, detail=str(e))
