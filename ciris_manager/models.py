"""
Simple data models for CIRISManager.

Keep it simple. Keep it typed. Keep it working.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class AgentInfo(BaseModel):
    """Everything we need to know about an agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    agent_name: str = Field(..., description="Human-friendly agent name")
    container_name: str = Field(..., description="Docker container name")
    api_port: Optional[int] = Field(None, description="API port if running")
    status: str = Field("stopped", description="Container status: running, stopped, etc")
    image: Optional[str] = Field(None, description="Docker image")

    # Computed properties for common access patterns
    @property
    def is_running(self) -> bool:
        """Is the agent currently running?"""
        return self.status == "running"

    @property
    def has_port(self) -> bool:
        """Does the agent have a valid port assigned?"""
        return self.api_port is not None and self.api_port > 0


class PortAllocation(BaseModel):
    """Port allocation tracking."""

    allocated: List[int] = Field(default_factory=list, description="Currently allocated ports")
    reserved: List[int] = Field(default_factory=list, description="Reserved ports (never allocate)")


class OAuthToken(BaseModel):
    """OAuth token data."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None


class OAuthUser(BaseModel):
    """OAuth user information."""

    id: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None

    @property
    def is_ciris_user(self) -> bool:
        """Check if user has @ciris.ai email."""
        return self.email.endswith("@ciris.ai")


class OAuthSession(BaseModel):
    """OAuth session data."""

    redirect_uri: str = Field(..., description="Where to redirect after OAuth")
    callback_url: str = Field(..., description="OAuth callback URL")
    created_at: str = Field(..., description="Session creation timestamp")


class JWTPayload(BaseModel):
    """JWT token payload."""

    user_id: int = Field(..., description="Internal user ID")
    email: str = Field(..., description="User email")
    name: Optional[str] = Field(None, description="User name")
    exp: Optional[int] = Field(None, description="Expiration timestamp")


class CreateAgentRequest(BaseModel):
    """Request to create a new agent."""

    template: str = Field(..., description="Template name (e.g., 'echo', 'teacher')")
    name: str = Field(..., description="Agent name")
    environment: dict = Field(default_factory=dict, description="Environment variables")
