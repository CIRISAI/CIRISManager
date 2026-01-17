"""
Adapter management routes.

This module provides endpoints for managing adapters on agents:
- List adapters and adapter types
- Load, reload, and unload adapters
- Adapter wizard configuration
- Persisted adapter configs
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .dependencies import get_manager, auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["adapters"])


async def _get_agent_client_info(manager: Any, agent_id: str) -> tuple[str, Dict[str, str], Any]:
    """
    Get the base URL and auth headers for an agent.

    Args:
        manager: CIRISManager instance
        agent_id: The agent ID to look up

    Returns:
        Tuple of (base_url, headers, agent_info)

    Raises:
        HTTPException: If agent not found or auth fails
    """
    from ciris_manager.docker_discovery import DockerAgentDiscovery
    from ciris_manager.agent_auth import get_agent_auth

    # Find the agent
    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()
    agent = next((a for a in agents if a.agent_id == agent_id), None)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get auth headers
    try:
        auth = get_agent_auth()
        headers = auth.get_auth_headers(
            agent.agent_id,
            occurrence_id=agent.occurrence_id,
            server_id=agent.server_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # Get base URL
    try:
        server_config = manager.docker_client.get_server_config(agent.server_id)
        if server_config.is_local:
            base_url = f"http://localhost:{agent.api_port}"
        else:
            base_url = f"http://{server_config.vpc_ip}:{agent.api_port}"
    except Exception:
        base_url = f"http://localhost:{agent.api_port}"

    return base_url, headers, agent


@router.get("/agents/{agent_id}/adapters")
async def list_agent_adapters(
    agent_id: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    List all adapters running on an agent.

    Proxies to agent's GET /v1/system/adapters endpoint.
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{base_url}/v1/system/adapters",
                headers=headers,
            )
            response.raise_for_status()
            result: Dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )


@router.get("/agents/{agent_id}/adapters/types")
async def list_agent_adapter_types(
    agent_id: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    List available adapter types on an agent.

    Proxies to agent's GET /v1/system/adapters/types endpoint.
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{base_url}/v1/system/adapters/types",
                headers=headers,
            )
            response.raise_for_status()
            result: Dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )


@router.get("/agents/{agent_id}/adapters/{adapter_id}")
async def get_agent_adapter(
    agent_id: str,
    adapter_id: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get status of a specific adapter on an agent.

    Proxies to agent's GET /v1/system/adapters/{adapter_id} endpoint.
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{base_url}/v1/system/adapters/{adapter_id}",
                headers=headers,
            )
            response.raise_for_status()
            result: Dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )


@router.post("/agents/{agent_id}/adapters/{adapter_type}")
async def load_agent_adapter(
    agent_id: str,
    adapter_type: str,
    request: Request,
    adapter_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Load/create a new adapter on an agent.

    Proxies to agent's POST /v1/system/adapters/{adapter_type} endpoint.

    Request body should contain:
    {
        "config": {
            "adapter_type": "string",
            "enabled": true,
            "settings": {...},
            "adapter_config": {...}
        },
        "auto_start": true
    }
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    # Get request body
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Build query params
    params = {}
    if adapter_id:
        params["adapter_id"] = adapter_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{base_url}/v1/system/adapters/{adapter_type}",
                headers={**headers, "Content-Type": "application/json"},
                json=body,
                params=params,
            )
            response.raise_for_status()
            result: Dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )


@router.put("/agents/{agent_id}/adapters/{adapter_id}/reload")
async def reload_agent_adapter(
    agent_id: str,
    adapter_id: str,
    request: Request,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Reload an adapter on an agent with new configuration.

    Proxies to agent's PUT /v1/system/adapters/{adapter_id}/reload endpoint.

    Request body should contain:
    {
        "config": {...},
        "auto_start": true
    }
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    # Get request body
    try:
        body = await request.json()
    except Exception:
        body = {"auto_start": True}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.put(
                f"{base_url}/v1/system/adapters/{adapter_id}/reload",
                headers={**headers, "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            result: Dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )


@router.delete("/agents/{agent_id}/adapters/{adapter_id}")
async def unload_agent_adapter(
    agent_id: str,
    adapter_id: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Unload/stop an adapter on an agent.

    Proxies to agent's DELETE /v1/system/adapters/{adapter_id} endpoint.
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.delete(
                f"{base_url}/v1/system/adapters/{adapter_id}",
                headers=headers,
            )
            response.raise_for_status()
            result: Dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )


# =============================================================================
# Pydantic Models for Wizard Endpoints
# =============================================================================


class WizardStartRequest(BaseModel):
    """Request to start a wizard session."""

    resume_from: Optional[str] = None  # Session ID to resume


class WizardStepRequest(BaseModel):
    """Request to execute a wizard step."""

    step_id: str
    action: str = "execute"  # "execute" or "skip"
    data: Dict[str, Any] = {}


class WizardCompleteRequest(BaseModel):
    """Request to complete a wizard."""

    confirm: bool = True


class AdapterConfigUpdate(BaseModel):
    """Request to update adapter config directly."""

    enabled: bool = True
    config: Dict[str, Any] = {}
    env_vars: Dict[str, str] = {}


# =============================================================================
# Wizard & Config Endpoints
# =============================================================================


@router.get("/agents/{agent_id}/adapters/manifests")
async def list_adapter_manifests(
    agent_id: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    List all available adapters with their status.

    Returns summary info for each adapter including:
    - adapter_type, name, description, version
    - status: not_configured, configured, enabled, disabled, error
    - requires_consent, has_wizard, workflow_type
    """
    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    # Get available adapter types from agent
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{base_url}/v1/system/adapters/types",
                headers=headers,
            )
            response.raise_for_status()
            types_data = response.json()
        except Exception as e:
            logger.warning(f"Failed to get adapter types from agent {agent_id}: {e}")
            types_data = {"data": {"types": []}}

        # Get running adapters to determine status
        try:
            running_response = await client.get(
                f"{base_url}/v1/system/adapters",
                headers=headers,
            )
            running_response.raise_for_status()
            running_data = running_response.json()
            running_adapters = {
                a.get("adapter_type", a.get("id")): a
                for a in running_data.get("data", {}).get("adapters", [])
            }
        except Exception:
            running_adapters = {}

        # Get persisted configs from registry
        persisted_configs = manager.agent_registry.get_adapter_configs(
            agent_id,
            occurrence_id=agent_info.occurrence_id,
            server_id=agent_info.server_id,
        )

        # Build adapter list with status
        adapters = []
        adapter_types = types_data.get("data", {}).get("types", [])

        for adapter_type in adapter_types:
            type_name = (
                adapter_type
                if isinstance(adapter_type, str)
                else adapter_type.get("name", "unknown")
            )

            # Determine status
            if type_name in running_adapters:
                status = "enabled"
            elif type_name in persisted_configs:
                config = persisted_configs[type_name]
                status = "configured" if config.get("enabled", True) else "disabled"
            else:
                status = "not_configured"

            # Try to get manifest info
            manifest_info = {}
            try:
                manifest_response = await client.get(
                    f"{base_url}/v1/system/adapters/{type_name}/manifest",
                    headers=headers,
                )
                if manifest_response.status_code == 200:
                    manifest = manifest_response.json().get("data", {})
                    module = manifest.get("module", {})
                    interactive = manifest.get("interactive_config", {})
                    manifest_info = {
                        "name": module.get("name", type_name),
                        "description": module.get("description", ""),
                        "version": module.get("version", ""),
                        "requires_consent": module.get("requires_consent", False),
                        "has_wizard": bool(interactive.get("steps")),
                        "workflow_type": interactive.get("workflow_type", "wizard"),
                    }
            except Exception:
                manifest_info = {
                    "name": type_name,
                    "description": "",
                    "version": "",
                    "requires_consent": False,
                    "has_wizard": False,
                    "workflow_type": "wizard",
                }

            adapters.append(
                {
                    "adapter_type": type_name,
                    "status": status,
                    **manifest_info,
                }
            )

    return {"adapters": adapters}


@router.get("/agents/{agent_id}/adapters/{adapter_type}/manifest")
async def get_adapter_manifest(
    agent_id: str,
    adapter_type: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get full manifest for a specific adapter.

    Fetches from agent's /v1/system/adapters/types and filters to the requested adapter.
    Also fetches wizard info from /v1/system/adapters/configurable if available.
    """
    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get all adapter types - this contains the manifest info
        try:
            response = await client.get(
                f"{base_url}/v1/system/adapters/types",
                headers=headers,
            )
            response.raise_for_status()
            types_data = response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )

        # Find the specific adapter in core_modules or adapters
        manifest: Optional[Dict[str, Any]] = None
        for module in types_data.get("core_modules", []):
            if module.get("module_id") == adapter_type:
                manifest = {"module": module}
                break

        if not manifest:
            for adapter in types_data.get("adapters", []):
                if adapter.get("module_id") == adapter_type:
                    manifest = {"module": adapter}
                    break

        if not manifest:
            raise HTTPException(
                status_code=404,
                detail=f"Adapter type '{adapter_type}' not found on agent",
            )

        # Try to get wizard/interactive config from configurable endpoint
        try:
            config_response = await client.get(
                f"{base_url}/v1/system/adapters/configurable",
                headers=headers,
            )
            if config_response.status_code == 200:
                config_data = config_response.json().get("data", {})
                for adapter in config_data.get("adapters", []):
                    if adapter.get("adapter_type") == adapter_type:
                        manifest["interactive_config"] = {
                            "workflow_type": adapter.get("workflow_type", "wizard"),
                            "steps": adapter.get("steps", []),
                            "requires_oauth": adapter.get("requires_oauth", False),
                        }
                        break
        except Exception as e:
            logger.debug(f"Could not get configurable info for {adapter_type}: {e}")

    # Add manager overlay with current config
    persisted_configs = manager.agent_registry.get_adapter_configs(
        agent_id,
        occurrence_id=agent_info.occurrence_id,
        server_id=agent_info.server_id,
    )

    current_config = persisted_configs.get(adapter_type)
    manifest["_manager"] = {
        "current_config": current_config,
        "status": "configured" if current_config else "not_configured",
    }

    return manifest


@router.post("/agents/{agent_id}/adapters/{adapter_type}/wizard/start")
async def start_adapter_wizard(
    agent_id: str,
    adapter_type: str,
    body: WizardStartRequest,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Start a new wizard session for configuring an adapter.

    Proxies to agent's /v1/system/adapters/{adapter_type}/configure/start endpoint.
    The agent manages the wizard session state.
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Proxy to agent's configure/start endpoint
            response = await client.post(
                f"{base_url}/v1/system/adapters/{adapter_type}/configure/start",
                headers={**headers, "Content-Type": "application/json"},
                json={},
            )
            response.raise_for_status()
            result = response.json().get("data", {})

            # Transform agent response to match expected format
            return {
                "session_id": result.get("session_id"),
                "adapter_type": result.get("adapter_type", adapter_type),
                "current_step": result.get("current_step", {}).get("step_id"),
                "current_step_details": result.get("current_step"),
                "steps_remaining": [
                    f"step_{i}" for i in range(
                        result.get("current_step_index", 0) + 1,
                        result.get("total_steps", 1)
                    )
                ],
                "total_steps": result.get("total_steps", 0),
                "status": result.get("status", "active"),
                "created_at": result.get("created_at"),
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Adapter type '{adapter_type}' not found or not configurable",
                )
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to start wizard on agent: {str(e)}",
            )


@router.post("/agents/{agent_id}/adapters/{adapter_type}/wizard/{session_id}/step")
async def execute_wizard_step(
    agent_id: str,
    adapter_type: str,
    session_id: str,
    body: WizardStepRequest,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Execute a wizard step.

    Proxies to agent's /v1/system/adapters/configure/{session_id}/step endpoint.
    The agent handles validation, OAuth, discovery, etc.
    """
    base_url, headers, _ = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Proxy to agent's step endpoint
            response = await client.post(
                f"{base_url}/v1/system/adapters/configure/{session_id}/step",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "step_id": body.step_id,
                    "action": body.action,
                    "data": body.data,
                },
            )
            response.raise_for_status()
            result = response.json().get("data", {})

            # Transform agent response
            return {
                "session_id": session_id,
                "step_id": body.step_id,
                "status": result.get("status", "completed"),
                "next_step": result.get("next_step", {}).get("step_id") if result.get("next_step") else None,
                "next_step_details": result.get("next_step"),
                "validation": result.get("validation"),
                "result": result.get("result"),
                "collected_data": result.get("collected_data", {}),
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 410:
                raise HTTPException(
                    status_code=410,
                    detail="Wizard session expired or not found",
                )
            if e.response.status_code == 400:
                # Try to extract error message from response
                try:
                    error_data = e.response.json()
                    detail = error_data.get("detail", str(e))
                except Exception:
                    detail = e.response.text
                raise HTTPException(status_code=400, detail=detail)
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to execute wizard step: {str(e)}",
            )


@router.post("/agents/{agent_id}/adapters/{adapter_type}/wizard/{session_id}/complete")
async def complete_adapter_wizard(
    agent_id: str,
    adapter_type: str,
    session_id: str,
    body: WizardCompleteRequest,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Complete the wizard and apply configuration.

    Proxies to agent's /v1/system/adapters/configure/{session_id}/complete endpoint.
    Also stores config in manager registry for persistence across restarts.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Proxy to agent's complete endpoint
            response = await client.post(
                f"{base_url}/v1/system/adapters/configure/{session_id}/complete",
                headers={**headers, "Content-Type": "application/json"},
                json={"confirm": True},
            )
            response.raise_for_status()
            result = response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 410:
                raise HTTPException(
                    status_code=410,
                    detail="Wizard session expired or not found",
                )
            if e.response.status_code == 400:
                try:
                    error_data = e.response.json()
                    detail = error_data.get("detail", str(e))
                except Exception:
                    detail = e.response.text
                raise HTTPException(status_code=400, detail=detail)
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to complete wizard: {str(e)}",
            )

        # Extract collected data and env vars from agent response
        collected_data = result.get("collected_data", {})
        env_vars = result.get("env_vars", {})

        # Build config to store in registry
        adapter_config = {
            "enabled": True,
            "configured_at": datetime.now(timezone.utc).isoformat(),
            "config": collected_data,
            "env_vars": env_vars,
        }

        if collected_data.get("consent_given"):
            adapter_config["consent_given"] = True
            adapter_config["consent_timestamp"] = collected_data.get(
                "consent_timestamp", datetime.now(timezone.utc).isoformat()
            )

        # Store in registry for persistence
        try:
            manager.agent_registry.set_adapter_config(
                agent_id,
                adapter_type,
                adapter_config,
                occurrence_id=agent_info.occurrence_id,
                server_id=agent_info.server_id,
            )
            logger.info(f"Stored adapter config for {adapter_type} on agent {agent_id}")
        except Exception as e:
            logger.warning(f"Failed to store adapter config in registry: {e}")

        # Regenerate compose file with new adapter env vars
        compose_regenerated = False
        try:
            await manager.regenerate_agent_compose(
                agent_id=agent_id,
                occurrence_id=agent_info.occurrence_id,
                server_id=agent_info.server_id,
            )
            compose_regenerated = True
            logger.info(f"Regenerated compose file for agent {agent_id} with {adapter_type} config")
        except Exception as e:
            logger.warning(f"Failed to regenerate compose file for {agent_id}: {e}")

    return {
        "session_id": session_id,
        "status": "completed",
        "adapter_type": adapter_type,
        "config_applied": result.get("config_applied", True),
        "compose_regenerated": compose_regenerated,
        "adapter_loaded": result.get("adapter_loaded", False),
        "restart_required": not result.get("adapter_loaded", False),
        "message": result.get("message", f"{adapter_type} adapter configured successfully"),
    }


@router.get("/agents/{agent_id}/adapters/configs")
async def get_adapter_configs(
    agent_id: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get all persisted adapter configurations for an agent.

    Returns configs stored in the registry (not runtime state).
    """
    _, _, agent_info = await _get_agent_client_info(manager, agent_id)

    configs = manager.agent_registry.get_adapter_configs(
        agent_id,
        occurrence_id=agent_info.occurrence_id,
        server_id=agent_info.server_id,
    )

    # Mask sensitive values
    def mask_sensitive(d: Dict[str, Any]) -> Dict[str, Any]:
        sensitive_keys = {"password", "secret", "token", "api_key", "client_secret"}
        masked: Dict[str, Any] = {}
        for k, v in d.items():
            if any(s in k.lower() for s in sensitive_keys):
                masked[k] = "***"
            elif isinstance(v, dict):
                masked[k] = mask_sensitive(v)
            else:
                masked[k] = v
        return masked

    return {"configs": {k: mask_sensitive(v) for k, v in configs.items()}}


@router.delete("/agents/{agent_id}/adapters/{adapter_type}/config")
async def remove_adapter_config(
    agent_id: str,
    adapter_type: str,
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Remove adapter configuration from registry.

    Also attempts to unload the adapter from the agent.
    """
    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    # Remove from registry
    removed = manager.agent_registry.remove_adapter_config(
        agent_id,
        adapter_type,
        occurrence_id=agent_info.occurrence_id,
        server_id=agent_info.server_id,
    )

    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"No configuration found for adapter '{adapter_type}'",
        )

    # Try to unload from agent
    adapter_unloaded = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.delete(
                f"{base_url}/v1/system/adapters/{adapter_type}",
                headers=headers,
            )
            adapter_unloaded = response.status_code == 200
        except Exception as e:
            logger.warning(f"Failed to unload adapter {adapter_type}: {e}")

    return {
        "adapter_type": adapter_type,
        "config_removed": True,
        "adapter_unloaded": adapter_unloaded,
        "message": f"{adapter_type} adapter disabled and configuration removed",
    }
