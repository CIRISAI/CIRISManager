"""
Shared dependencies for route modules.

This module provides common dependencies used across multiple route modules:
- Manager instance access
- Authentication dependencies
- Helper functions for agent resolution
- Deployment authentication
"""

import os
import logging
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request

from ..auth import get_current_user_dependency as get_current_user

logger = logging.getLogger(__name__)


def get_manager(request: Request) -> Any:
    """
    Get manager instance from app state.

    Args:
        request: FastAPI request object

    Returns:
        CIRISManager instance

    Raises:
        HTTPException: If manager not available
    """
    if not hasattr(request.app.state, "manager"):
        raise HTTPException(status_code=500, detail="Manager not initialized")
    return request.app.state.manager


def get_deployment_orchestrator(request: Request) -> Any:
    """
    Get deployment orchestrator from app state.

    Args:
        request: FastAPI request object

    Returns:
        DeploymentOrchestrator instance

    Raises:
        HTTPException: If orchestrator not available
    """
    if not hasattr(request.app.state, "deployment_orchestrator"):
        raise HTTPException(status_code=500, detail="Deployment orchestrator not initialized")
    return request.app.state.deployment_orchestrator


def get_token_manager(request: Request) -> Any:
    """
    Get deployment token manager from app state.

    Args:
        request: FastAPI request object

    Returns:
        DeploymentTokenManager instance

    Raises:
        HTTPException: If token manager not available
    """
    if not hasattr(request.app.state, "token_manager"):
        raise HTTPException(status_code=500, detail="Token manager not initialized")
    return request.app.state.token_manager


async def get_mock_user() -> Dict[str, str]:
    """Mock user for development mode."""
    return {"id": "dev-user", "email": "dev@ciris.local", "name": "Development User"}


def _get_auth_dependency_runtime(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, str]:
    """
    Runtime auth dependency that checks CIRIS_AUTH_MODE at call time.

    This allows test fixtures to set the mode after import.
    """
    auth_mode = os.getenv("CIRIS_AUTH_MODE", "production")
    if auth_mode == "development":
        # Return mock user synchronously for dev mode
        return {"id": "dev-user", "email": "dev@ciris.local", "name": "Development User"}

    # For production, delegate to the real auth
    from ..auth_routes import get_auth_service

    auth_service = get_auth_service()
    return auth_service.get_current_user(request, authorization)  # type: ignore[no-any-return]


def get_auth_dependency():
    """
    Get the auth dependency that evaluates mode at runtime.

    Returns:
        Depends() wrapper for runtime auth check
    """
    return Depends(_get_auth_dependency_runtime)


# Create a reusable auth dependency
auth_dependency = get_auth_dependency()


def resolve_agent(
    manager: Any,
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
) -> Any:
    """
    Resolve an agent lookup with composite key support.

    Handles cases where multiple instances have the same agent_id but different occurrence_ids.

    Args:
        manager: CIRISManager instance
        agent_id: The agent ID to look up
        occurrence_id: Optional occurrence ID for disambiguation
        server_id: Optional server ID for disambiguation

    Returns:
        RegisteredAgent if found uniquely

    Raises:
        HTTPException: If agent not found or multiple instances exist without disambiguation
    """
    if occurrence_id or server_id:
        # Precise lookup with composite key
        agent = manager.agent_registry.get_agent(
            agent_id, occurrence_id=occurrence_id, server_id=server_id
        )
        if not agent:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agent_id}' with occurrence_id='{occurrence_id}' and server_id='{server_id}' not found",
            )
        return agent
    else:
        # No disambiguation provided - check if there are multiple instances
        all_instances = manager.agent_registry.get_agents_by_agent_id(agent_id)

        if len(all_instances) == 0:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        elif len(all_instances) == 1:
            # Only one instance - unambiguous
            return all_instances[0]
        else:
            # Multiple instances exist - need disambiguation
            instance_details = [
                f"  - occurrence_id={a.occurrence_id or 'none'}, server_id={a.server_id}"
                for a in all_instances
            ]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Multiple instances of agent '{agent_id}' exist. "
                    f"Please specify occurrence_id and/or server_id query parameters:\n"
                    + "\n".join(instance_details)
                ),
            )


async def deployment_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, str]:
    """
    Verify deployment token for CD operations and identify the source.

    Args:
        request: FastAPI request object
        authorization: Bearer token from Authorization header

    Returns:
        Dict with user info and source_repo

    Raises:
        HTTPException: If token missing or invalid
    """
    token_manager = get_token_manager(request)
    deploy_tokens = token_manager.get_all_tokens()

    if not any(deploy_tokens.values()):
        raise HTTPException(status_code=500, detail="Deployment tokens not configured")

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    # Extract token from "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = parts[1]

    # Identify which repo this token belongs to
    source_repo = None
    for repo_type, repo_token in deploy_tokens.items():
        if repo_token and token == repo_token:
            source_repo = repo_type
            break

    if not source_repo:
        raise HTTPException(status_code=401, detail="Invalid deployment token")

    return {
        "id": "github-actions",
        "email": "cd@ciris.ai",
        "name": "GitHub Actions CD",
        "source_repo": source_repo,
    }
