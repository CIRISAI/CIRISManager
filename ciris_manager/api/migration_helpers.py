"""
Migration helpers for API consolidation.

Provides backward compatibility during the transition period.
"""

import warnings
from typing import Any, Dict
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta


# Deprecation timeline
DEPRECATION_START = datetime(2025, 8, 18)  # Today
DEPRECATION_WARNING_END = DEPRECATION_START + timedelta(days=90)  # 3 months
DEPRECATION_REMOVAL = DEPRECATION_START + timedelta(days=180)  # 6 months


def add_deprecation_headers(response: JSONResponse, old_path: str, new_path: str) -> JSONResponse:
    """Add deprecation headers to response."""
    response.headers["X-Deprecated"] = "true"
    response.headers["X-Deprecation-Date"] = DEPRECATION_WARNING_END.isoformat()
    response.headers["X-Sunset-Date"] = DEPRECATION_REMOVAL.isoformat()
    response.headers["X-Alternative-Location"] = new_path
    response.headers["Warning"] = f'299 - "Deprecated API: Use {new_path} instead"'
    return response


def check_deprecation_timeline(old_path: str) -> bool:
    """Check if we should still serve the deprecated endpoint."""
    now = datetime.now()

    if now > DEPRECATION_REMOVAL:
        # Past removal date - return 410 Gone
        raise HTTPException(
            status_code=410,
            detail={
                "error": "Endpoint removed",
                "message": f"This endpoint was deprecated and has been removed. Use {get_new_path(old_path)} instead.",
                "migration_guide": "https://docs.ciris.ai/api/migration",
            },
        )

    if now > DEPRECATION_WARNING_END:
        # Past warning period - log heavily
        warnings.warn(
            f"CRITICAL: Deprecated endpoint {old_path} still in use after warning period",
            DeprecationWarning,
            stacklevel=2,
        )

    return True


def get_new_path(old_path: str) -> str:
    """Map old paths to new paths."""
    path_mapping = {
        "/agents/versions": "/versions/agents",
        "/versions/adoption": "/versions/adoption",  # No change
        "/updates/rollback-options": "/versions/rollback-options",
        "/updates/current-images": "/versions/current",
        "/updates/history": "/versions/history",
        "/updates/latest/changelog": "/versions/changelog/latest",
        "/updates/deploy-single": "/deployments/agent/{agent_id}/deploy",
        "/updates/notify": "/deployments/notify",
        "/updates/launch": "/deployments/{deployment_id}/launch",
        "/updates/cancel": "/deployments/{deployment_id}/cancel",
        "/updates/pause": "/deployments/{deployment_id}/pause",
        "/updates/rollback": "/deployments/{deployment_id}/rollback",
        "/updates/pending": "/deployments/pending",
        "/updates/pending/all": "/deployments/pending/details",
        "/updates/status": "/deployments/{deployment_id}/status",
        "/updates/events/{deployment_id}": "/deployments/{deployment_id}/events",
    }

    return path_mapping.get(old_path, old_path)


def log_deprecated_usage(request: Request, old_path: str, new_path: str) -> None:
    """Log usage of deprecated endpoints for monitoring."""
    # In production, this would log to your monitoring system
    client_info = {
        "ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("User-Agent", "unknown"),
        "timestamp": datetime.now().isoformat(),
        "old_path": old_path,
        "new_path": new_path,
    }

    # Log for monitoring
    warnings.warn(f"Deprecated API usage: {client_info}", DeprecationWarning, stacklevel=2)


def create_legacy_wrapper(old_endpoint, new_endpoint, old_path: str, new_path: str):
    """
    Create a wrapper function that calls the new endpoint with deprecation warnings.

    This allows us to maintain the old endpoint while routing to new logic.
    """

    async def legacy_wrapper(request: Request, *args, **kwargs):
        # Check if we should still serve this
        check_deprecation_timeline(old_path)

        # Log usage
        log_deprecated_usage(request, old_path, new_path)

        # Call new endpoint
        result = await new_endpoint(*args, **kwargs)

        # Add deprecation headers
        if isinstance(result, dict):
            response = JSONResponse(content=result)
            return add_deprecation_headers(response, old_path, new_path)

        return result

    # Preserve function metadata
    legacy_wrapper.__name__ = f"legacy_{old_endpoint.__name__}"
    legacy_wrapper.__doc__ = f"DEPRECATED: {old_endpoint.__doc__}\n\nUse {new_path} instead."

    return legacy_wrapper


class DeprecationMiddleware:
    """
    Middleware to handle deprecated endpoints globally.

    Can be added to FastAPI app to automatically handle deprecations.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]

            # Check if this is a deprecated path
            new_path = get_new_path(path)
            if new_path != path:
                # Add deprecation warning to response headers
                async def send_wrapper(message):
                    if message["type"] == "http.response.start":
                        headers = dict(message.get("headers", []))
                        headers[b"x-deprecated"] = b"true"
                        headers[b"x-alternative-location"] = new_path.encode()
                        message["headers"] = list(headers.items())
                    await send(message)

                await self.app(scope, receive, send_wrapper)
                return

        await self.app(scope, receive, send)


def migrate_request_body(old_format: Dict[str, Any], endpoint: str) -> Dict[str, Any]:
    """
    Migrate request body from old format to new format.

    Handles differences in request structure between old and new endpoints.
    """
    if endpoint == "/updates/deploy-single":
        # Old format: {agent_id, version, message, strategy}
        # New format: {version, message, strategy} (agent_id in path)
        return {
            "version": old_format.get("version"),
            "message": old_format.get("message"),
            "strategy": old_format.get("strategy", "immediate"),
        }

    # Default: no transformation needed
    return old_format


def migrate_response_body(new_format: Dict[str, Any], endpoint: str) -> Dict[str, Any]:
    """
    Migrate response body from new format to old format.

    Ensures backward compatibility for clients expecting old response structure.
    """
    if endpoint == "/agents/versions":
        # New endpoint returns more structured data
        # Flatten for old clients if needed
        if "agents" in new_format:
            return new_format  # Already compatible

    if endpoint == "/updates/rollback-options":
        # Ensure both "agent" and "agents" are present for compatibility
        if "agent" in new_format and "agents" not in new_format:
            new_format["agents"] = new_format["agent"]  # Add legacy field

    return new_format


# Usage tracking for metrics
class DeprecationMetrics:
    """Track usage of deprecated endpoints."""

    def __init__(self):
        self.usage_counts: Dict[str, int] = {}
        self.last_usage: Dict[str, datetime] = {}
        self.unique_clients: Dict[str, set] = {}

    def record_usage(self, endpoint: str, client_id: str):
        """Record usage of a deprecated endpoint."""
        if endpoint not in self.usage_counts:
            self.usage_counts[endpoint] = 0
            self.unique_clients[endpoint] = set()

        self.usage_counts[endpoint] += 1
        self.last_usage[endpoint] = datetime.now()
        self.unique_clients[endpoint].add(client_id)

    def get_metrics(self) -> Dict[str, Any]:
        """Get deprecation metrics for monitoring."""
        metrics = {}
        for endpoint in self.usage_counts:
            metrics[endpoint] = {
                "total_calls": self.usage_counts[endpoint],
                "unique_clients": len(self.unique_clients[endpoint]),
                "last_usage": self.last_usage[endpoint].isoformat()
                if endpoint in self.last_usage
                else None,
                "days_since_deprecation": (datetime.now() - DEPRECATION_START).days,
            }
        return metrics


# Global metrics instance
deprecation_metrics = DeprecationMetrics()
