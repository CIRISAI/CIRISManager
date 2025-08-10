"""
Rate limiting for CIRISManager API endpoints.

Provides configurable rate limiting to prevent abuse and ensure fair usage.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

# Create limiter instance using client IP address as key
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour"],  # Global default limit
    storage_uri="memory://",  # In-memory storage (can be changed to Redis for distributed systems)
)

# Rate limit configurations for different endpoint types
RATE_LIMITS = {
    # Authentication endpoints - stricter limits to prevent brute force
    "auth": "5 per minute",
    "login": "10 per minute",
    "oauth": "20 per minute",
    # Agent management - moderate limits
    "create_agent": "5 per minute",
    "delete_agent": "10 per minute",
    "update_agent": "30 per minute",
    # Read operations - more permissive
    "list_agents": "60 per minute",
    "get_agent": "120 per minute",
    "get_status": "120 per minute",
    # Deployment operations - strict limits
    "deploy": "2 per minute",
    "rollback": "2 per minute",
    # Device auth - moderate limits
    "device_auth": "10 per minute",
    # Default for unspecified endpoints
    "default": "60 per minute",
}


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Args:
        request: The request that exceeded the rate limit
        exc: The RateLimitExceeded exception

    Returns:
        JSON response with 429 status code
    """
    response = JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded: {exc.detail}",
            "error": "rate_limit_exceeded",
            "retry_after": exc.retry_after if hasattr(exc, "retry_after") else None,
        },
    )

    # Add Retry-After header if available
    if hasattr(exc, "retry_after"):
        response.headers["Retry-After"] = str(exc.retry_after)

    # Log rate limit violation for monitoring
    client_ip = get_remote_address(request)
    logger.warning(f"Rate limit exceeded for {client_ip} on {request.url.path}: {exc.detail}")

    return response


def get_rate_limit(endpoint_type: str) -> str:
    """
    Get the rate limit for a specific endpoint type.

    Args:
        endpoint_type: Type of endpoint (e.g., 'auth', 'create_agent')

    Returns:
        Rate limit string (e.g., "5 per minute")
    """
    return RATE_LIMITS.get(endpoint_type, RATE_LIMITS["default"])


# Decorator shortcuts for common rate limits
auth_limit = limiter.limit(RATE_LIMITS["auth"])
login_limit = limiter.limit(RATE_LIMITS["login"])
create_limit = limiter.limit(RATE_LIMITS["create_agent"])
read_limit = limiter.limit(RATE_LIMITS["get_agent"])
deploy_limit = limiter.limit(RATE_LIMITS["deploy"])
