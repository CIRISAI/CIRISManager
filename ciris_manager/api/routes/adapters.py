"""
Adapter management routes.

This module provides endpoints for managing adapters on agents:
- List adapters and adapter types
- Load, reload, and unload adapters
- Adapter configuration (future)
"""

from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .dependencies import get_manager, auth_dependency

router = APIRouter(tags=["adapters"])


async def _get_agent_client_info(
    manager: Any, agent_id: str
) -> tuple[str, Dict[str, str], Any]:
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
