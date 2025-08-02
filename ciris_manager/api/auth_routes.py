"""
OAuth authentication routes for CIRISManager.

Uses dependency injection for better testability.
"""

from fastapi import APIRouter, HTTPException, Request, Response, Depends, Header
from fastapi.responses import RedirectResponse
from typing import Optional, Dict, Any
import logging
import os
from pathlib import Path

from .auth_service import (
    AuthService,
    InMemorySessionStore,
    SQLiteUserStore,
    MockOAuthProvider,
    OAuthProvider,
    TokenResponse,
)
from .google_oauth import GoogleOAuthProvider

logger = logging.getLogger(__name__)

# Global instances (configured on startup)
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get auth service dependency."""
    if _auth_service is None:
        raise RuntimeError("Auth service not initialized")
    return _auth_service


def init_auth_service(
    google_client_id: Optional[str] = None,
    google_client_secret: Optional[str] = None,
    jwt_secret: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[AuthService]:
    """Initialize auth service with configuration."""
    global _auth_service

    # Use environment variables if not provided
    client_id = google_client_id or os.getenv("GOOGLE_CLIENT_ID")
    client_secret = google_client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
    jwt_secret_value = jwt_secret or os.getenv("MANAGER_JWT_SECRET") or "dev-secret-key"
    db_path = db_path or Path.home() / ".config" / "ciris-manager" / "auth.db"

    # Check for dev mode
    # Declare with Protocol type
    oauth_provider: OAuthProvider

    if client_id == "mock-local-testing" or os.getenv("CIRIS_DEV_MODE") == "true":
        logger.info("Using mock OAuth provider for development")
        oauth_provider = MockOAuthProvider()
    elif not client_id or not client_secret:
        logger.warning("Google OAuth not configured")
        return None
    else:
        # Create Google OAuth provider
        oauth_provider = GoogleOAuthProvider(
            client_id=client_id, client_secret=client_secret, hd_domain="ciris.ai"
        )

    session_store = InMemorySessionStore()
    user_store = SQLiteUserStore(db_path)

    _auth_service = AuthService(
        oauth_provider=oauth_provider,
        session_store=session_store,
        user_store=user_store,
        jwt_secret=jwt_secret_value,
    )

    return _auth_service


def _get_callback_url(request: Request) -> str:
    """Determine OAuth callback URL based on environment."""
    if request.url.hostname in ["localhost", "127.0.0.1"]:
        return "http://localhost:8888/manager/v1/oauth/callback"
    return "https://agents.ciris.ai/manager/oauth/callback"


def _get_redirect_uri(request: Request, redirect_uri: Optional[str]) -> str:
    """Determine redirect URI after OAuth."""
    if redirect_uri:
        return redirect_uri
    return f"{request.url.scheme}://{request.url.netloc}/manager/"


def create_auth_routes() -> APIRouter:
    """Create authentication routes."""
    router = APIRouter()
    oauth_error_msg = "OAuth not configured"

    @router.get("/oauth/login")
    async def google_login(
        request: Request,
        redirect_uri: Optional[str] = None,
        auth_service: AuthService = Depends(get_auth_service),
    ) -> RedirectResponse:
        """Initiate Google OAuth login flow."""
        if not auth_service:
            raise HTTPException(status_code=500, detail=oauth_error_msg)

        final_redirect_uri = _get_redirect_uri(request, redirect_uri)
        callback_url = _get_callback_url(request)

        try:
            state, auth_url = await auth_service.initiate_oauth_flow(
                redirect_uri=final_redirect_uri, callback_url=callback_url
            )
            return RedirectResponse(url=auth_url)
        except Exception as e:
            logger.error(f"OAuth initiation failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to initiate OAuth")

    @router.get("/oauth/callback")
    async def google_callback(
        request: Request,
        code: str,
        state: str,
        auth_service: AuthService = Depends(get_auth_service),
    ) -> RedirectResponse:
        """Handle Google OAuth callback."""
        if not auth_service:
            raise HTTPException(status_code=500, detail=oauth_error_msg)

        try:
            result = await auth_service.handle_oauth_callback(code, state)

            # Redirect with token in URL (like original implementation)
            # This matches how the frontend expects to receive the token
            redirect_url = f"{result['redirect_uri']}?token={result['access_token']}"

            # Also set JWT cookie for future API calls
            response = RedirectResponse(url=redirect_url)
            response.set_cookie(
                key="manager_token",
                value=result["access_token"],
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                max_age=86400,  # 24 hours
            )

            return response

        except ValueError as e:
            logger.error(f"OAuth callback error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"OAuth callback failed: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception args: {e.args}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail="Authentication failed")

    @router.post("/oauth/logout")
    async def logout(response: Response) -> Dict[str, str]:
        """Logout by clearing the JWT cookie."""
        response.delete_cookie("manager_token")
        return {"message": "Logged out successfully"}

    @router.get("/oauth/user")
    async def get_current_user(
        authorization: Optional[str] = Header(None),
        auth_service: AuthService = Depends(get_auth_service),
    ) -> Dict[str, Any]:
        """Get current authenticated user."""
        if not auth_service:
            raise HTTPException(status_code=500, detail=oauth_error_msg)

        user = auth_service.get_current_user(authorization)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        return {"user": user}

    # Add dev token endpoint for easy testing
    if os.getenv("CIRIS_DEV_MODE") == "true":

        @router.post("/dev/token")
        async def get_dev_token(
            auth_service: AuthService = Depends(get_auth_service),
        ) -> TokenResponse:
            """Get a development token (only available in dev mode)."""
            if not auth_service:
                raise HTTPException(status_code=500, detail=oauth_error_msg)

            # Create a dev user session
            dev_user = {
                "id": "dev-user-123",
                "email": "dev@ciris.ai",
                "name": "Dev User",
            }

            from ciris_manager.models import OAuthUser

            user = OAuthUser(id="dev-user", email="dev@ciris.ai", name="Dev User")
            token = auth_service.create_jwt_token(dev_user)
            return TokenResponse(access_token=token, user=user)

    return router


def get_current_user_dependency(
    request: Request,
    authorization: Optional[str] = Header(None),
    auth_service: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """FastAPI dependency to get current authenticated user."""
    if not auth_service:
        raise HTTPException(
            status_code=500, detail="OAuth not configured"
        )  # Keep for external dependency

    # Try authorization header first
    user = auth_service.get_current_user(authorization)

    # If no auth header, try cookie
    if not user:
        token = request.cookies.get("manager_token")
        if token:
            user = auth_service.get_current_user(f"Bearer {token}")

    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user
