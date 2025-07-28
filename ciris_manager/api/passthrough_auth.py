"""
Passthrough authentication for development environments.

When auth is disabled, this service always returns a dev user,
making all endpoints accessible without authentication.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class PassthroughAuthService:
    """
    Authentication service that always passes.

    Used in development when auth.enabled = false.
    Follows the same pattern as NoOpNginxManager.
    """

    def __init__(self) -> None:
        """Initialize passthrough auth."""
        logger.info("Authentication disabled - using passthrough auth service")

    def get_current_user(self, authorization: Optional[str] = None) -> Dict[str, Any]:
        """
        Always return a dev user.

        Args:
            authorization: Ignored in passthrough mode

        Returns:
            Dev user dict
        """
        logger.debug("Passthrough auth returning dev user")
        return {"id": "dev-user-123", "email": "dev@ciris.ai", "name": "Dev User"}

    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        """Not needed in passthrough mode."""
        return f"{redirect_uri}?code=dev&state={state}"

    async def handle_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Not needed in passthrough mode."""
        return {"access_token": "dev-token", "token_type": "Bearer"}

    def create_jwt_token(self, user_data: Dict[str, Any]) -> str:
        """Return a fake token."""
        return "dev-token-no-validation-needed"

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Always return dev user."""
        return self.get_current_user()
