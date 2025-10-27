"""
Simple data models for CIRISManager.

Keep it simple. Keep it typed. Keep it working.
"""

from typing import Optional, List, Dict
from pydantic import BaseModel, Field, model_validator


class AgentInfo(BaseModel):
    """Everything we need to know about an agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    agent_name: str = Field(..., description="Human-friendly agent name")
    container_name: str = Field(..., description="Docker container name")
    api_port: Optional[int] = Field(None, description="API port if running")
    status: str = Field("stopped", description="Container status: running, stopped, etc")
    image: Optional[str] = Field(None, description="Docker image")
    oauth_status: Optional[str] = Field(
        None, description="OAuth configuration status: pending, configured, verified"
    )
    service_token: Optional[str] = Field(
        None, description="Service account token for manager-to-agent authentication"
    )
    # Version information from agent status API
    version: Optional[str] = Field(None, description="Agent semantic version (e.g., 1.0.4-beta)")
    codename: Optional[str] = Field(
        None, description="Agent release codename (e.g., Graceful Guardian)"
    )
    code_hash: Optional[str] = Field(
        None, description="Agent code hash for exact version identification"
    )
    cognitive_state: Optional[str] = Field(
        None, description="Agent cognitive state (WAKEUP, WORK, SHUTDOWN, etc.)"
    )
    # Runtime configuration from environment
    mock_llm: Optional[bool] = Field(None, description="Whether agent is using mock LLM")
    discord_enabled: Optional[bool] = Field(None, description="Whether Discord adapter is enabled")

    # Metadata fields
    template: str = Field("unknown", description="Template used to create agent")
    deployment: str = Field(
        "CIRIS_DISCORD_PILOT", description="Deployment identifier (e.g., CIRIS_DISCORD_PILOT)"
    )
    server_id: Optional[str] = Field("main", description="Server ID where agent is deployed")
    occurrence_id: Optional[str] = Field(
        None, description="Occurrence ID for multi-instance agents (e.g., '002')"
    )
    deployment_type: Optional[str] = Field(
        None,
        description="Deployment type: API_ONLY for remote servers, FULL for main server with GUI",
    )
    created_at: Optional[str] = Field(None, description="When agent was created")
    health: Optional[str] = Field(None, description="Agent health status")
    api_endpoint: Optional[str] = Field(None, description="Full API endpoint URL")
    update_available: bool = Field(False, description="Whether an update is available")

    # Computed properties for common access patterns
    @property
    def is_running(self) -> bool:
        """Is the agent currently running?"""
        return self.status == "running"

    @property
    def has_port(self) -> bool:
        """Does the agent have a valid port assigned?"""
        return self.api_port is not None and self.api_port > 0

    @property
    def has_oauth(self) -> bool:
        """Is OAuth configured for this agent?"""
        return self.oauth_status in ["configured", "verified"]


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
    wa_signature: Optional[str] = Field(None, description="WA signature for non-approved templates")
    use_mock_llm: Optional[bool] = Field(None, description="Use mock LLM instead of real API")
    enable_discord: Optional[bool] = Field(None, description="Enable Discord adapter for agent")
    wa_review_completed: Optional[bool] = Field(
        None, description="WA review completed for Tier 4/5 agents"
    )
    billing_enabled: Optional[bool] = Field(
        False, description="Enable paid billing with Stripe (default: false, uses free credits)"
    )
    billing_api_key: Optional[str] = Field(
        None, description="Billing API key (required when billing_enabled=true)"
    )
    server_id: Optional[str] = Field(
        None, description="Target server ID (defaults to 'main' if not specified)"
    )
    database_url: Optional[str] = Field(
        None,
        description="PostgreSQL database URL (e.g., postgresql://user:pass@host:port/db?sslmode=require)",
    )
    database_ssl_cert_path: Optional[str] = Field(
        None,
        description="Path to SSL certificate for database connection (e.g., /root/ca-certificate.crt)",
    )
    agent_occurrence_id: Optional[str] = Field(
        None,
        description="Unique occurrence ID for this agent instance (enables multiple agents on same database)",
    )


class UpdateNotification(BaseModel):
    """CD update notification from GitHub Actions."""

    agent_image: Optional[str] = Field(
        None, description="New agent image (e.g., ghcr.io/cirisai/ciris-agent:latest)"
    )
    gui_image: Optional[str] = Field(None, description="New GUI image if updated")
    nginx_image: Optional[str] = Field(None, description="New nginx image if updated")
    message: str = Field("Update available", description="Human-readable update message")
    strategy: str = Field("canary", description="Deployment strategy: canary, immediate, manual")
    metadata: dict = Field(default_factory=dict, description="Additional deployment metadata")
    # Enhanced fields for informed consent
    source: Optional[str] = Field("github-actions", description="Source of update notification")
    commit_sha: Optional[str] = Field(None, description="Git commit SHA for this update")
    version: Optional[str] = Field(None, description="Semantic version if available")
    changelog: Optional[str] = Field(None, description="Full commit messages from release")
    risk_level: Optional[str] = Field("unknown", description="Risk assessment: low, medium, high")

    @model_validator(mode="after")
    def validate_at_least_one_image(self) -> "UpdateNotification":
        """Ensure at least one image is provided."""
        if not any([self.agent_image, self.gui_image, self.nginx_image]):
            raise ValueError(
                "At least one of agent_image, gui_image, or nginx_image must be provided"
            )
        return self


class DeploymentStatus(BaseModel):
    """Current deployment status."""

    deployment_id: str = Field(..., description="Unique deployment identifier")
    notification: Optional[UpdateNotification] = Field(
        None, description="Original update notification"
    )
    agents_total: int = Field(..., description="Total number of agents")
    agents_updated: int = Field(0, description="Number of agents updated")
    agents_deferred: int = Field(0, description="Number of agents that deferred update")
    agents_failed: int = Field(0, description="Number of agents that failed to update")
    canary_phase: Optional[str] = Field(
        None, description="Current canary phase: explorers, early_adopters, general"
    )
    started_at: Optional[str] = Field(None, description="Deployment start timestamp")
    staged_at: Optional[str] = Field(None, description="When deployment was staged for review")
    completed_at: Optional[str] = Field(None, description="Deployment completion timestamp")
    status: str = Field(
        "in_progress",
        description="Deployment status: pending, in_progress, paused, completed, failed, cancelled, rejected, rolling_back, rolled_back",
    )
    message: str = Field(..., description="Current status message")
    events: List[dict] = Field(default_factory=list, description="Timeline of deployment events")
    strategy: Optional[str] = Field(
        default="canary", description="Deployment strategy: canary, immediate, manual"
    )
    updated_at: Optional[str] = Field(default=None, description="Last update timestamp")
    agents_pending_restart: List[str] = Field(
        default_factory=list, description="Agent IDs that have shutdown and are pending restart"
    )
    agents_in_progress: Dict[str, str] = Field(
        default_factory=dict,
        description="Agents currently being processed: agent_id -> state (shutting_down, restarting, etc)",
    )
    canary_assignments: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Canary group assignments for this deployment: explorers, early_adopters, general",
    )


class AgentUpdateResponse(BaseModel):
    """Agent's response to update request."""

    agent_id: str = Field(..., description="Agent identifier")
    decision: str = Field(
        ...,
        description="Update decision: accept, defer, reject, skipped (maintenance mode), notified (delayed shutdown)",
    )
    reason: Optional[str] = Field(None, description="Reason for decision")
    ready_at: Optional[str] = Field(None, description="When agent will be ready (if deferred)")
