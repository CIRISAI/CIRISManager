"""
Manager GUI routes.

This module provides endpoints for serving the Manager UI:
- / - Manager dashboard (index.html)
- /manager.js - Manager JavaScript
- /callback - OAuth callback handler
"""

import os
from pathlib import Path
from typing import Optional, Union

from fastapi import APIRouter, HTTPException, Header, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

router = APIRouter(tags=["gui"])

# Auth mode checked at module load for route behavior
auth_mode = os.getenv("CIRIS_AUTH_MODE", "production")


def _get_authenticated_user(request: Request, authorization: Optional[str]) -> Optional[dict]:
    """
    Check authentication and return user if valid.

    Args:
        request: FastAPI request object
        authorization: Authorization header value

    Returns:
        User dict if authenticated, None otherwise
    """
    try:
        from ciris_manager.api.auth_routes import get_auth_service

        auth_service = get_auth_service()
        if not auth_service:
            return None

        # Try authorization header first
        user = auth_service.get_current_user(authorization)
        # If no auth header, try cookie
        if not user:
            token = request.cookies.get("manager_token")
            if token:
                user = auth_service.get_current_user(f"Bearer {token}")

        return user
    except Exception:
        return None


@router.get("/", response_model=None)
async def manager_home(
    request: Request, authorization: Optional[str] = Header(None)
) -> Union[FileResponse, RedirectResponse]:
    """Serve manager dashboard for @ciris.ai users."""
    user = _get_authenticated_user(request, authorization)

    if not user:
        return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

    # In production mode, check for @ciris.ai email
    if auth_mode == "production" and not user.get("email", "").endswith("@ciris.ai"):
        raise HTTPException(status_code=403, detail="Access restricted to @ciris.ai users")

    # Serve the manager UI
    static_path = Path(__file__).parent.parent.parent.parent / "static" / "manager" / "index.html"
    if not static_path.exists():
        raise HTTPException(status_code=404, detail="Manager UI not found")

    return FileResponse(
        static_path,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/manager.js", response_model=None)
async def manager_js(
    request: Request, authorization: Optional[str] = Header(None)
) -> Union[FileResponse, RedirectResponse]:
    """Serve manager JavaScript."""
    user = _get_authenticated_user(request, authorization)

    if not user:
        return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

    if auth_mode == "production" and not user.get("email", "").endswith("@ciris.ai"):
        raise HTTPException(status_code=403, detail="Access restricted to @ciris.ai users")

    static_path = Path(__file__).parent.parent.parent.parent / "static" / "manager" / "manager.js"
    if not static_path.exists():
        raise HTTPException(status_code=404, detail="Manager JS not found")

    return FileResponse(
        static_path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/callback")
async def manager_callback(token: Optional[str] = None) -> Response:
    """Handle OAuth callback redirect to Manager UI with token."""
    # Serve a minimal HTML page that extracts the token and redirects
    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Redirecting...</title>
    <style>
        body {
            background-color: #1a1a1a;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .loading {
            text-align: center;
        }
        .spinner {
            border: 3px solid #333;
            border-top: 3px solid #3b82f6;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="loading">
        <div class="spinner"></div>
        <p>Completing authentication...</p>
    </div>
    <script>
        // Extract token from URL
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token');

        if (token) {
            // Store token in localStorage
            localStorage.setItem('managerToken', token);

            // Redirect to manager dashboard
            window.location.href = '/manager/';
        } else {
            // No token, redirect to login
            window.location.href = '/manager/';
        }
    </script>
</body>
</html>
"""

    return HTMLResponse(content=html_content)
