"""
OAuth routes - agent OAuth configuration verification.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from .dependencies import get_manager, get_auth_dependency, resolve_agent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])

# Get auth dependency based on mode
auth_dependency = get_auth_dependency()


@router.get("/agents/{agent_id}/oauth/verify")
async def verify_agent_oauth(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, Any]:
    """
    Verify OAuth configuration for an agent.

    Checks if OAuth is properly configured and working.
    Supports composite keys for multi-instance deployments.
    """
    agent = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

    oauth_configured = agent.oauth_status in ["configured", "verified"]
    oauth_working = agent.oauth_status == "verified"

    return {
        "agent_id": agent_id,
        "configured": oauth_configured,
        "working": oauth_working,
        "status": agent.oauth_status or "pending",
        "callback_urls": {
            "google": f"https://agents.ciris.ai/v1/auth/oauth/{agent_id}/google/callback",
            "github": f"https://agents.ciris.ai/v1/auth/oauth/{agent_id}/github/callback",
            "discord": f"https://agents.ciris.ai/v1/auth/oauth/{agent_id}/discord/callback",
        },
    }


@router.post("/agents/{agent_id}/oauth/complete")
async def mark_oauth_complete(
    agent_id: str,
    occurrence_id: Optional[str] = None,
    server_id: Optional[str] = None,
    manager: Any = Depends(get_manager),
    user: dict = auth_dependency,
) -> Dict[str, str]:
    """
    Mark OAuth as configured for an agent.

    Called after admin has registered callback URLs in provider dashboards.
    Supports composite keys for multi-instance deployments.
    """
    agent = resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

    agent.oauth_status = "configured"
    manager.agent_registry.save_metadata()

    logger.info(f"OAuth marked as configured for agent {agent_id} by {user['email']}")

    return {
        "status": "success",
        "agent_id": agent_id,
        "oauth_status": "configured",
        "message": "OAuth configuration marked as complete. Run verification to test.",
    }
