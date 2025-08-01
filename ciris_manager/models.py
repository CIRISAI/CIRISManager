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


class UpdateNotification(BaseModel):
    """CD update notification from GitHub Actions."""

    agent_image: str = Field(
        ..., description="New agent image (e.g., ghcr.io/cirisai/ciris-agent:latest)"
    )
    gui_image: Optional[str] = Field(None, description="New GUI image if updated")
    message: str = Field("Update available", description="Human-readable update message")
    strategy: str = Field("canary", description="Deployment strategy: canary, immediate, manual")
    metadata: dict = Field(default_factory=dict, description="Additional deployment metadata")
    # Enhanced fields for informed consent
    source: Optional[str] = Field("github-actions", description="Source of update notification")
    commit_sha: Optional[str] = Field(None, description="Git commit SHA for this update")
    version: Optional[str] = Field(None, description="Semantic version if available")
    changelog: Optional[str] = Field(None, description="Brief description of changes")
    risk_level: Optional[str] = Field("unknown", description="Risk assessment: low, medium, high")


class DeploymentStatus(BaseModel):
    """Current deployment status."""

    deployment_id: str = Field(..., description="Unique deployment identifier")
    agents_total: int = Field(..., description="Total number of agents")
    agents_updated: int = Field(0, description="Number of agents updated")
    agents_deferred: int = Field(0, description="Number of agents that deferred update")
    agents_failed: int = Field(0, description="Number of agents that failed to update")
    canary_phase: Optional[str] = Field(
        None, description="Current canary phase: explorers, early_adopters, general"
    )
    started_at: str = Field(..., description="Deployment start timestamp")
    completed_at: Optional[str] = Field(None, description="Deployment completion timestamp")
    status: str = Field(
        "in_progress", description="Deployment status: in_progress, completed, failed, cancelled"
    )
    message: str = Field(..., description="Current status message")


class AgentUpdateResponse(BaseModel):
    """Agent's response to update request."""

    agent_id: str = Field(..., description="Agent identifier")
    decision: str = Field(..., description="Update decision: accept, defer, reject")
    reason: Optional[str] = Field(None, description="Reason for decision")
    ready_at: Optional[str] = Field(None, description="When agent will be ready (if deferred)")
