"""
Infrastructure routes - ports and deployment tokens.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..auth import get_current_user_dependency as get_current_user
from .dependencies import get_manager, get_token_manager
from .models import AllocatedPortsResponse, PortRange

logger = logging.getLogger(__name__)

router = APIRouter(tags=["infrastructure"])


@router.get("/ports/allocated", response_model=AllocatedPortsResponse)
async def get_allocated_ports(
    manager: Any = Depends(get_manager),
) -> AllocatedPortsResponse:
    """Get allocated ports."""
    return AllocatedPortsResponse(
        allocated=list(manager.port_manager.allocated_ports.values()),
        reserved=list(manager.port_manager.reserved_ports),
        range=PortRange(
            start=manager.port_manager.start_port,
            end=manager.port_manager.end_port,
        ),
    )


@router.get("/deployment/tokens")
async def get_deployment_tokens(
    token_manager: Any = Depends(get_token_manager),
    _user: Dict[str, str] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get deployment tokens for GitHub secrets configuration.
    Only accessible to @ciris.ai users.
    """
    deploy_tokens = token_manager.get_all_tokens()
    return {
        "status": "success",
        "tokens": {
            "CIRISAI/CIRISAgent": {
                "secret_name": "DEPLOY_TOKEN",
                "secret_value": deploy_tokens.get("agent", ""),
            },
            "CIRISAI/CIRISGUI": {
                "secret_name": "DEPLOY_TOKEN",
                "secret_value": deploy_tokens.get("gui", ""),
            },
        },
        "instructions": "Add these as repository secrets in GitHub Settings > Secrets and variables > Actions",
    }
