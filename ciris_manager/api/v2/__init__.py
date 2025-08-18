"""
Clean v2 API - No legacy cruft.
"""

from .agents import router as agents_router
from .versions import router as versions_router
from .deployments import router as deployments_router
from .templates import router as templates_router
from .system import router as system_router

__all__ = [
    "agents_router",
    "versions_router",
    "deployments_router",
    "templates_router",
    "system_router",
]
