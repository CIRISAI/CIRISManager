"""
FastAPI routes for jailbreaker endpoints.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .service import JailbreakerService
from .models import ResetResult, ResetStatus

logger = logging.getLogger(__name__)


class OAuthInitResponse(BaseModel):
    """Response for OAuth initialization."""

    auth_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    """Request for OAuth callback."""

    code: str
    state: str


class OAuthCallbackResponse(BaseModel):
    """Response for OAuth callback."""

    access_token: str
    message: str


class ResetRequest(BaseModel):
    """Request for agent reset."""

    access_token: str


class RateLimitStatusResponse(BaseModel):
    """Rate limit status response."""

    global_limit_seconds: int
    user_limit_seconds: int
    tracked_users: int
    last_global_reset: Optional[int]
    seconds_until_next_global: Optional[int]
    user_next_reset: Optional[int] = None


def create_jailbreaker_routes(jailbreaker_service: JailbreakerService) -> APIRouter:
    """
    Create jailbreaker API routes.

    Args:
        jailbreaker_service: Initialized jailbreaker service

    Returns:
        FastAPI router with jailbreaker endpoints
    """
    router = APIRouter(prefix="/jailbreaker", tags=["jailbreaker"])

    @router.get("/oauth/init", response_model=OAuthInitResponse)
    async def init_oauth(state: Optional[str] = Query(None)):
        """
        Initialize Discord OAuth flow.

        Args:
            state: Optional state parameter for OAuth security

        Returns:
            Discord OAuth URL and state
        """
        try:
            auth_url, oauth_state = jailbreaker_service.generate_oauth_url(state)
            logger.info(f"Generated OAuth URL with state: {oauth_state[:8]}...")

            return OAuthInitResponse(auth_url=auth_url, state=oauth_state)

        except Exception as e:
            logger.error(f"Failed to initialize OAuth: {e}")
            raise HTTPException(status_code=500, detail="Failed to initialize OAuth")

    @router.post("/oauth/callback", response_model=OAuthCallbackResponse)
    async def oauth_callback(request: OAuthCallbackRequest):
        """
        Handle Discord OAuth callback.

        Args:
            request: OAuth callback with code and state

        Returns:
            Access token for subsequent API calls
        """
        try:
            # Exchange code for token
            access_token = await jailbreaker_service.exchange_code_for_token(request.code)

            # Verify the token works and user has permissions
            has_permission, user_id = await jailbreaker_service.verify_access_token(access_token)

            if not has_permission:
                logger.warning(f"OAuth callback for user without jailbreak permissions: {user_id}")
                raise HTTPException(
                    status_code=403, detail="User does not have jailbreak permissions"
                )

            logger.info(f"OAuth callback successful for user {user_id}")

            return OAuthCallbackResponse(
                access_token=access_token, message="Authentication successful"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"OAuth callback failed: {e}")
            raise HTTPException(status_code=400, detail="OAuth callback failed")

    @router.post("/reset", response_model=ResetResult)
    async def reset_agent(request: ResetRequest):
        """
        Reset the target agent.

        Args:
            request: Reset request with access token

        Returns:
            Reset operation result
        """
        try:
            logger.info("Agent reset requested via jailbreaker API")
            result = await jailbreaker_service.reset_agent(request.access_token)

            # Map result status to HTTP status codes
            if result.status == ResetStatus.SUCCESS:
                logger.info(f"Agent reset successful for user {result.user_id}")
                return result
            elif result.status == ResetStatus.UNAUTHORIZED:
                raise HTTPException(status_code=403, detail=result.message)
            elif result.status == ResetStatus.RATE_LIMITED:
                raise HTTPException(
                    status_code=429,
                    detail=result.message,
                    headers={
                        "Retry-After": str(
                            (result.next_allowed_reset or 0) - int(__import__("time").time())
                        )
                    },
                )
            elif result.status == ResetStatus.AGENT_NOT_FOUND:
                raise HTTPException(status_code=404, detail=result.message)
            else:  # ERROR
                raise HTTPException(status_code=500, detail=result.message)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in reset endpoint: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get("/status", response_model=RateLimitStatusResponse)
    async def get_status(user_id: Optional[str] = Query(None)):
        """
        Get jailbreaker service status and rate limits.

        Args:
            user_id: Optional user ID to get user-specific status

        Returns:
            Service status and rate limit information
        """
        try:
            status = jailbreaker_service.get_rate_limit_status(user_id)

            return RateLimitStatusResponse(
                global_limit_seconds=status["global_limit_seconds"],
                user_limit_seconds=status["user_limit_seconds"],
                tracked_users=status["tracked_users"],
                last_global_reset=status["last_global_reset"],
                seconds_until_next_global=status["seconds_until_next_global"],
                user_next_reset=status.get("user_next_reset"),
            )

        except Exception as e:
            logger.error(f"Failed to get jailbreaker status: {e}")
            raise HTTPException(status_code=500, detail="Failed to get service status")

    @router.post("/cleanup")
    async def cleanup_rate_limits():
        """
        Clean up old rate limit entries (admin endpoint).

        Returns:
            Success message
        """
        try:
            await jailbreaker_service.cleanup_rate_limiter()
            logger.info("Rate limiter cleanup completed")

            return {"message": "Rate limiter cleanup completed"}

        except Exception as e:
            logger.error(f"Failed to cleanup rate limits: {e}")
            raise HTTPException(status_code=500, detail="Failed to cleanup rate limits")

    return router
