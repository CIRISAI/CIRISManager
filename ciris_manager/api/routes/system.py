"""
System routes - health and status endpoints.
"""

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends

from .dependencies import get_manager
from .models import StatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "ciris-manager"}


@router.get("/status", response_model=StatusResponse)
async def get_status(
    manager: Any = Depends(get_manager),
) -> StatusResponse:
    """Get manager status."""
    auth_mode = os.getenv("CIRIS_AUTH_MODE", "production")
    status = manager.get_status()
    return StatusResponse(
        status="running" if status["running"] else "stopped",
        components=status["components"],
        auth_mode=auth_mode,
        uptime_seconds=status.get("uptime_seconds"),
        start_time=status.get("start_time"),
        system_metrics=status.get("system_metrics"),
    )
