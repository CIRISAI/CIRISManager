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
from .wizard_sessions import get_wizard_session_manager

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

    Includes interactive_config with wizard steps.
    """
    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{base_url}/v1/system/adapters/{adapter_type}/manifest",
                headers=headers,
            )
            response.raise_for_status()
            manifest: Dict[str, Any] = response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Adapter type '{adapter_type}' not found on agent",
                )
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent returned error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with agent: {str(e)}",
            )

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

    Optionally resume from a previous session.
    """
    # Resume existing session if requested
    if body.resume_from:
        session_mgr = get_wizard_session_manager()
        session = session_mgr.get_session(body.resume_from)
        if session and session.agent_id == agent_id and session.adapter_type == adapter_type:
            return session.to_dict()
        # If session not found or doesn't match, create new one

    # Get manifest to extract steps
    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{base_url}/v1/system/adapters/{adapter_type}/manifest",
                headers=headers,
            )
            response.raise_for_status()
            manifest = response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Adapter type '{adapter_type}' not found",
                )
            raise HTTPException(
                status_code=e.response.status_code,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to get adapter manifest: {str(e)}",
            )

    # Extract step IDs from manifest
    interactive_config = manifest.get("interactive_config", {})
    steps = interactive_config.get("steps", [])

    if not steps:
        raise HTTPException(
            status_code=400,
            detail=f"Adapter '{adapter_type}' does not have a configuration wizard",
        )

    step_ids = [s.get("step_id") for s in steps if s.get("step_id")]

    # Create session
    session_mgr = get_wizard_session_manager()
    session = session_mgr.create_session(
        agent_id=agent_id,
        adapter_type=adapter_type,
        steps=step_ids,
    )

    return session.to_dict()


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

    Validates input and stores collected data.
    For OAuth steps, returns authorization URL.
    For discovery steps, returns discovered items.
    """
    session_mgr = get_wizard_session_manager()
    session = session_mgr.get_session(session_id)

    if not session:
        raise HTTPException(status_code=410, detail="Wizard session expired or not found")

    if session.agent_id != agent_id or session.adapter_type != adapter_type:
        raise HTTPException(status_code=400, detail="Session does not match agent/adapter")

    # Get manifest for step definition
    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/v1/system/adapters/{adapter_type}/manifest",
            headers=headers,
        )
        response.raise_for_status()
        manifest = response.json().get("data", {})

    # Find step definition
    steps = manifest.get("interactive_config", {}).get("steps", [])
    step_def = next((s for s in steps if s.get("step_id") == body.step_id), None)

    if not step_def:
        raise HTTPException(status_code=400, detail=f"Step '{body.step_id}' not found")

    # Handle skip for optional steps
    if body.action == "skip":
        if not step_def.get("optional", False):
            raise HTTPException(status_code=400, detail=f"Step '{body.step_id}' is not optional")
        session.advance_step()
        return {
            "session_id": session_id,
            "step_id": body.step_id,
            "status": "skipped",
            "next_step": session.current_step if session.steps_remaining else None,
            "collected_data": session._mask_sensitive_data(session.collected_data),
        }

    # Process step based on type
    step_type = step_def.get("step_type", "input")
    result: Dict[str, Any] = {}

    if step_type == "input":
        # Validate and collect input fields
        fields = step_def.get("fields", [])
        errors = []

        for field in fields:
            field_id = field.get("field_id") or field.get("name")
            required = field.get("required", False)
            value = body.data.get(field_id)

            if required and not value:
                errors.append(f"{field.get('label', field_id)} is required")
            elif value:
                # Store in collected data
                session.collected_data[field_id] = value

        if errors:
            return {
                "session_id": session_id,
                "step_id": body.step_id,
                "status": "validation_failed",
                "validation": {"valid": False, "errors": errors},
            }

        result = {"status": "completed", "validation": {"valid": True, "errors": []}}

    elif step_type == "confirm":
        # Confirmation step - just mark complete
        result = {"status": "completed"}

    elif step_type == "select":
        # Selection step
        selections = body.data.get("selections", body.data.get("selected", []))
        if selections:
            session.collected_data[f"{body.step_id}_selections"] = selections
        result = {"status": "completed"}

    elif step_type == "discovery":
        # Discovery would need agent-side implementation
        # For now, accept manual URL entry
        if "url" in body.data:
            session.collected_data["discovered_url"] = body.data["url"]
        result = {"status": "completed", "result": {"discovered": body.data.get("discovered", [])}}

    elif step_type == "oauth":
        # OAuth requires redirect flow
        oauth_config = step_def.get("oauth_config", {})
        # Generate state for CSRF protection
        import secrets

        state = secrets.token_urlsafe(32)
        session.oauth_state = state

        # Build authorization URL (simplified - real impl would vary by provider)
        base_oauth_url = session.collected_data.get("discovered_url", "")
        if not base_oauth_url:
            raise HTTPException(status_code=400, detail="OAuth requires discovered URL first")

        auth_path = oauth_config.get("authorization_path", "/auth/authorize")
        callback_url = f"https://agents.ciris.ai/manager/v1/agents/{agent_id}/adapters/{adapter_type}/wizard/{session_id}/oauth-callback"

        # Store for later
        session.collected_data["oauth_callback_url"] = callback_url

        return {
            "session_id": session_id,
            "step_id": body.step_id,
            "status": "pending_redirect",
            "result": {
                "authorization_url": f"{base_oauth_url}{auth_path}?state={state}&redirect_uri={callback_url}",
                "state": state,
                "callback_url": callback_url,
            },
        }

    # Advance to next step
    session.advance_step()

    return {
        "session_id": session_id,
        "step_id": body.step_id,
        "next_step": session.current_step if session.steps_remaining else None,
        "collected_data": session._mask_sensitive_data(session.collected_data),
        **result,
    }


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

    Stores config in registry and optionally loads adapter on agent.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    session_mgr = get_wizard_session_manager()
    session = session_mgr.get_session(session_id)

    if not session:
        raise HTTPException(status_code=410, detail="Wizard session expired or not found")

    if session.agent_id != agent_id or session.adapter_type != adapter_type:
        raise HTTPException(status_code=400, detail="Session does not match agent/adapter")

    # Get manifest for env var mappings
    base_url, headers, agent_info = await _get_agent_client_info(manager, agent_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/v1/system/adapters/{adapter_type}/manifest",
            headers=headers,
        )
        response.raise_for_status()
        manifest = response.json().get("data", {})

        # Map collected data to env vars
        configuration = manifest.get("configuration", {})
        env_vars = {}

        for param_name, param_def in configuration.items():
            env_key = param_def.get("env")
            if env_key and param_name in session.collected_data:
                env_vars[env_key] = str(session.collected_data[param_name])

        # Check for consent
        consent_given = session.collected_data.get("consent_given", False)
        consent_timestamp = None
        if manifest.get("module", {}).get("requires_consent"):
            if not consent_given:
                raise HTTPException(
                    status_code=400,
                    detail="This adapter requires explicit consent",
                )
            consent_timestamp = datetime.now(timezone.utc).isoformat()

        # Build config to store in registry
        adapter_config = {
            "enabled": True,
            "configured_at": datetime.now(timezone.utc).isoformat(),
            "config": session.collected_data,
            "env_vars": env_vars,
        }

        if consent_given:
            adapter_config["consent_given"] = True
            adapter_config["consent_timestamp"] = consent_timestamp

        # Store in registry
        success = manager.agent_registry.set_adapter_config(
            agent_id,
            adapter_type,
            adapter_config,
            occurrence_id=agent_info.occurrence_id,
            server_id=agent_info.server_id,
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to save adapter configuration")

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

        # Try to load adapter on agent
        adapter_loaded = False
        try:
            load_response = await client.post(
                f"{base_url}/v1/system/adapters/{adapter_type}",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "config": session.collected_data,
                    "auto_start": True,
                },
            )
            adapter_loaded = load_response.status_code == 200
        except Exception as e:
            logger.warning(f"Failed to load adapter {adapter_type} on agent: {e}")

    # Clean up session
    session_mgr.delete_session(session_id)

    return {
        "session_id": session_id,
        "status": "completed",
        "adapter_type": adapter_type,
        "config_applied": True,
        "compose_regenerated": compose_regenerated,
        "adapter_loaded": adapter_loaded,
        "restart_required": not adapter_loaded,
        "message": f"{adapter_type} adapter configured successfully"
        + (" and started" if adapter_loaded else " (restart required to apply)"),
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
