"""
OAuth Device Flow routes for CLI authentication.

Implements RFC 8628 OAuth 2.0 Device Authorization Grant.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import secrets
from datetime import datetime, timezone, timedelta
import logging

from .auth_routes import get_auth_service
from .auth_service import AuthService
from ciris_manager.utils.log_sanitizer import sanitize_for_log, sanitize_email

logger = logging.getLogger(__name__)


class DeviceCodeRequest(BaseModel):
    """Request for device code."""

    client_id: str = "ciris-cli"
    scope: str = "manager:full"


class DeviceCodeResponse(BaseModel):
    """Response with device code."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int = 600  # 10 minutes
    interval: int = 5  # Poll every 5 seconds


class DeviceTokenRequest(BaseModel):
    """Request for token using device code."""

    device_code: str
    client_id: str = "ciris-cli"


class DeviceTokenResponse(BaseModel):
    """Token response."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600  # 60 minutes as requested


# In-memory storage for device codes (in production, use Redis or database)
_device_codes: Dict[str, Dict[str, Any]] = {}
_user_codes: Dict[str, str] = {}  # user_code -> device_code mapping


def generate_user_code() -> str:
    """Generate a user-friendly code (e.g., ABCD-1234)."""
    # Use only easily distinguishable characters
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part1 = "".join(secrets.choice(chars) for _ in range(4))
    part2 = "".join(secrets.choice(chars) for _ in range(4))
    return f"{part1}-{part2}"


def create_device_auth_routes() -> APIRouter:
    """Create device authentication routes."""
    router = APIRouter()

    @router.post("/device/code", response_model=DeviceCodeResponse)
    async def request_device_code(
        request: Request,
        device_request: DeviceCodeRequest,
    ) -> DeviceCodeResponse:
        """Request a device code for CLI authentication."""
        # Generate codes
        device_code = secrets.token_urlsafe(32)
        user_code = generate_user_code()

        logger.info(
            f"Device code requested - user_code: {sanitize_for_log(user_code)}, "
            f"device_code: {device_code[:10]}..., client_id: {sanitize_for_log(device_request.client_id)}"
        )

        # Store device code info
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=600)
        _device_codes[device_code] = {
            "user_code": user_code,
            "client_id": device_request.client_id,
            "scope": device_request.scope,
            "expires_at": expires_at,
            "status": "pending",  # pending, authorized, denied, expired
            "user": None,
        }
        _user_codes[user_code] = device_code

        # Determine base URL
        if request.url.hostname in ["localhost", "127.0.0.1"]:
            base_url = f"http://{request.url.netloc}"
        else:
            base_url = "https://agents.ciris.ai"

        verification_uri = f"{base_url}/manager/device"

        return DeviceCodeResponse(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=f"{verification_uri}?code={user_code}",
            expires_in=600,
            interval=5,
        )

    @router.post("/device/token")
    async def request_device_token(
        token_request: DeviceTokenRequest,
        auth_service: AuthService = Depends(get_auth_service),
    ) -> JSONResponse:
        """Poll for token using device code."""
        if not auth_service:
            raise HTTPException(status_code=500, detail="Auth service not configured")

        logger.debug(
            f"Token request for device_code: {token_request.device_code[:10]}..., "
            f"client_id: {token_request.client_id}"
        )

        device_info = _device_codes.get(token_request.device_code)
        if not device_info:
            # Log without user input to prevent log injection
            logger.warning("Invalid device code submitted")
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_grant", "error_description": "Invalid device code"},
            )

        # Check expiration
        if datetime.now(timezone.utc) > device_info["expires_at"]:
            device_info["status"] = "expired"
            return JSONResponse(
                status_code=400,
                content={"error": "expired_token", "error_description": "Device code expired"},
            )

        # Check status
        logger.debug(
            f"Device code status: {device_info['status']}, "
            f"user: {device_info['user']['email'] if device_info['user'] else 'None'}"
        )

        if device_info["status"] == "pending":
            return JSONResponse(
                status_code=400,
                content={
                    "error": "authorization_pending",
                    "error_description": "Authorization pending",
                },
            )
        elif device_info["status"] == "denied":
            logger.info(f"Device code denied: {token_request.device_code[:10]}...")
            return JSONResponse(
                status_code=400,
                content={"error": "access_denied", "error_description": "Authorization denied"},
            )
        elif device_info["status"] == "authorized" and device_info["user"]:
            # Generate token with 60 minute expiry
            auth_service.jwt_expiration_hours = 1  # Override to 1 hour
            token = auth_service.create_jwt_token(
                {
                    "sub": device_info["user"]["email"],
                    "email": device_info["user"]["email"],
                    "name": device_info["user"].get("name", ""),
                    "picture": device_info["user"].get("picture", ""),
                    "hd": device_info["user"].get("hd", ""),
                }
            )

            logger.info(
                f"Token issued for device_code: {token_request.device_code[:10]}..., "
                f"user: {device_info['user']['email']}"
            )

            # Clean up used codes
            del _device_codes[token_request.device_code]
            if device_info["user_code"] in _user_codes:
                del _user_codes[device_info["user_code"]]

            return JSONResponse(
                status_code=200,
                content={
                    "access_token": token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_grant",
                    "error_description": "Invalid device code state",
                },
            )

    @router.get("/device")
    async def device_verification_page(
        code: Optional[str] = None,
        auth_service: AuthService = Depends(get_auth_service),
    ) -> HTMLResponse:
        """Device verification page."""
        if not auth_service:
            return HTMLResponse("OAuth not configured", status_code=500)

        # Simple HTML page for device verification
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>CIRIS Manager - Device Authorization</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 2rem;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    max-width: 400px;
                    width: 100%;
                }}
                h1 {{
                    margin: 0 0 1rem 0;
                    font-size: 1.5rem;
                }}
                .code-input {{
                    width: 100%;
                    padding: 0.75rem;
                    font-size: 1.25rem;
                    border: 2px solid #ddd;
                    border-radius: 4px;
                    text-align: center;
                    text-transform: uppercase;
                    letter-spacing: 0.1em;
                }}
                .code-input:focus {{
                    outline: none;
                    border-color: #4CAF50;
                }}
                .submit-btn {{
                    width: 100%;
                    padding: 0.75rem;
                    margin-top: 1rem;
                    background: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 1rem;
                    cursor: pointer;
                }}
                .submit-btn:hover {{
                    background: #45a049;
                }}
                .submit-btn:disabled {{
                    background: #ccc;
                    cursor: not-allowed;
                }}
                .error {{
                    color: #f44336;
                    margin-top: 0.5rem;
                    font-size: 0.875rem;
                }}
                .info {{
                    color: #666;
                    margin-bottom: 1rem;
                    font-size: 0.875rem;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Device Authorization</h1>
                <p class="info">Enter the code displayed on your device to authorize access.</p>
                <form id="deviceForm">
                    <input 
                        type="text" 
                        id="userCode" 
                        class="code-input" 
                        placeholder="XXXX-XXXX" 
                        maxlength="9"
                        pattern="[A-Z0-9]{{4}}-[A-Z0-9]{{4}}"
                        value="{code or ""}"
                        required
                    >
                    <button type="submit" class="submit-btn" id="submitBtn">
                        Verify Code
                    </button>
                    <div id="error" class="error"></div>
                </form>
            </div>
            
            <script>
                const form = document.getElementById('deviceForm');
                const codeInput = document.getElementById('userCode');
                const submitBtn = document.getElementById('submitBtn');
                const errorDiv = document.getElementById('error');
                
                // Auto-format code input
                codeInput.addEventListener('input', (e) => {{
                    let value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
                    if (value.length > 4) {{
                        value = value.slice(0, 4) + '-' + value.slice(4, 8);
                    }}
                    e.target.value = value;
                }});
                
                form.addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    errorDiv.textContent = '';
                    submitBtn.disabled = true;
                    submitBtn.textContent = 'Verifying...';
                    
                    const userCode = codeInput.value;
                    
                    try {{
                        // Check if we have a token in the URL (just returned from OAuth)
                        const urlParams = new URLSearchParams(window.location.search);
                        const tokenFromUrl = urlParams.get('token');
                        
                        let authHeaders = {{}};
                        if (tokenFromUrl) {{
                            // Use token from URL if available
                            authHeaders['Authorization'] = `Bearer ${{tokenFromUrl}}`;
                        }}
                        
                        // First, check if user is authenticated
                        const authCheck = await fetch('/manager/v1/oauth/user', {{
                            credentials: 'include',
                            headers: authHeaders
                        }});
                        
                        if (!authCheck.ok) {{
                            // Redirect to login with return URL, preserving only the code
                            const currentUrl = new URL(window.location.href);
                            const cleanUrl = `${{currentUrl.origin}}${{currentUrl.pathname}}?code=${{userCode}}`;
                            window.location.href = `/manager/v1/oauth/login?redirect_uri=${{encodeURIComponent(cleanUrl)}}`;
                            return;
                        }}
                        
                        // User is authenticated, verify the device code
                        const verifyHeaders = {{
                            'Content-Type': 'application/json',
                        }};
                        if (tokenFromUrl) {{
                            verifyHeaders['Authorization'] = `Bearer ${{tokenFromUrl}}`;
                        }}
                        
                        const response = await fetch('/manager/v1/device/verify', {{
                            method: 'POST',
                            headers: verifyHeaders,
                            credentials: 'include',
                            body: JSON.stringify({{ user_code: userCode }})
                        }});
                        
                        const result = await response.json();
                        
                        if (response.ok) {{
                            submitBtn.textContent = '✓ Authorized';
                            submitBtn.style.background = '#4CAF50';
                            setTimeout(() => {{
                                window.location.href = '/manager/';
                            }}, 1500);
                        }} else {{
                            errorDiv.textContent = result.detail || 'Invalid code';
                            submitBtn.disabled = false;
                            submitBtn.textContent = 'Verify Code';
                        }}
                    }} catch (error) {{
                        errorDiv.textContent = 'Network error. Please try again.';
                        submitBtn.disabled = false;
                        submitBtn.textContent = 'Verify Code';
                    }}
                }});
                
                // Focus on input
                codeInput.focus();
                
                // Auto-submit if we have a code and just returned from OAuth
                const urlParams = new URLSearchParams(window.location.search);
                if (urlParams.has('token') && codeInput.value) {{
                    // User just authenticated via OAuth, auto-submit the form
                    console.log('Auto-submitting after OAuth authentication');
                    // Use requestSubmit for better compatibility
                    if (form.requestSubmit) {{
                        form.requestSubmit();
                    }} else {{
                        // Fallback for older browsers
                        submitBtn.click();
                    }}
                }}
            </script>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    @router.post("/device/verify")
    async def verify_device_code(
        request: Request,
        body: Dict[str, str],
        auth_service: AuthService = Depends(get_auth_service),
    ) -> Dict[str, Any]:
        """Verify device code and authorize."""
        user_code = body.get("user_code", "")
        logger.info(f"Device verification attempt for user_code: {sanitize_for_log(user_code)}")

        if not auth_service:
            logger.error("Auth service not configured")
            raise HTTPException(status_code=500, detail="Auth service not configured")

        # Get current user from session
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            # Check cookie
            token = request.cookies.get("manager_token")
            if token:
                auth_header = f"Bearer {token}"
                logger.debug("Using token from cookie")

        user = auth_service.get_current_user(auth_header)
        if not user:
            # Log without user input to prevent log injection
            logger.warning("Unauthenticated verification attempt")
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Sanitize email for logging to prevent log injection
        email = user.get("email", "unknown")
        safe_email = sanitize_email(email)
        logger.info(f"User {safe_email} attempting to verify device code")

        # Verify user is from @ciris.ai domain in production
        if auth_service.oauth_provider.__class__.__name__ != "MockOAuthProvider":
            if not user.get("email", "").endswith("@ciris.ai"):
                raise HTTPException(status_code=403, detail="Access restricted to @ciris.ai users")

        # Find device code by user code
        device_code = _user_codes.get(user_code.upper())
        if not device_code:
            # Log without user input to prevent log injection
            logger.warning("Invalid user_code submitted")
            logger.debug(f"Available user codes count: {len(_user_codes)}")
            raise HTTPException(status_code=400, detail="Invalid code")

        device_info = _device_codes.get(device_code)
        if not device_info:
            logger.error(f"Device code found but no device info: {device_code[:10]}...")
            raise HTTPException(status_code=400, detail="Invalid code")

        # Check expiration
        if datetime.now(timezone.utc) > device_info["expires_at"]:
            device_info["status"] = "expired"
            raise HTTPException(status_code=400, detail="Code expired")

        # Authorize the device
        device_info["status"] = "authorized"
        device_info["user"] = user

        logger.info(
            f"Device authorized successfully - user_code: {sanitize_for_log(user_code)}, "
            f"device_code: {device_code[:10]}..., user: {sanitize_email(user.get('email', 'unknown'))}"
        )

        return {"status": "authorized", "message": "Device authorized successfully"}

    return router
