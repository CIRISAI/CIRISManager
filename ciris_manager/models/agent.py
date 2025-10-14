"""
Pydantic models for agent-related data structures.

These models provide type-safe interfaces for agent configuration,
status, and management operations.
"""

from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, ConfigDict


class AgentConfig(BaseModel):
    """
    Complete agent configuration for export/import operations.

    This model contains all configuration data needed to recreate
    an agent, including compose file settings and environment variables.
    """

    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Human-friendly agent name")
    template: str = Field(..., description="Template used to create agent")
    port: int = Field(..., description="Allocated port number")
    compose_file: str = Field(..., description="Path to docker-compose.yml")
    environment: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables from compose file and .env"
    )

    # Registry metadata
    created_at: Optional[str] = Field(None, description="Agent creation timestamp (ISO 8601)")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata (deployment, canary_group, etc.)"
    )

    # Authentication
    oauth_status: Optional[Literal["pending", "configured", "verified"]] = Field(
        None, description="OAuth configuration status"
    )
    service_token: Optional[str] = Field(
        None, description="Encrypted service token for authentication"
    )
    admin_password: Optional[str] = Field(None, description="Encrypted admin password")

    # Version tracking
    current_version: Optional[str] = Field(None, description="Current agent version")
    last_work_state_at: Optional[str] = Field(
        None, description="Last timestamp agent reached WORK state (ISO 8601)"
    )
    version_transitions: List[Dict[str, Any]] = Field(
        default_factory=list, description="History of version transitions"
    )

    # Management settings
    do_not_autostart: bool = Field(
        default=False, description="Prevent automatic restart (maintenance mode)"
    )
    server_id: str = Field(default="main", description="Server hosting the agent")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "datum",
                "name": "Datum",
                "template": "echo",
                "port": 8001,
                "compose_file": "/opt/ciris/agents/datum/docker-compose.yml",
                "environment": {
                    "CIRIS_AGENT_NAME": "datum",
                    "CIRIS_API_PORT": "8001",
                    "OPENAI_API_KEY": "sk-...",
                },
                "created_at": "2025-01-15T10:30:00Z",
                "server_id": "main",
            }
        }
    )


class AgentCreate(BaseModel):
    """
    Request payload for creating a new agent.

    Sent to POST /manager/v1/agents to create a new agent instance.
    """

    template: str = Field(..., description="Template name (e.g., 'echo', 'teacher')")
    name: str = Field(..., description="Agent name (human-friendly identifier)")
    environment: Dict[str, Any] = Field(
        default_factory=dict, description="Environment variables for agent configuration"
    )

    # Optional configuration
    wa_signature: Optional[str] = Field(None, description="WA signature for non-approved templates")
    use_mock_llm: Optional[bool] = Field(
        None, description="Use mock LLM instead of real API (testing/dev mode)"
    )
    enable_discord: Optional[bool] = Field(None, description="Enable Discord adapter for agent")
    wa_review_completed: Optional[bool] = Field(
        None, description="WA review completed for Tier 4/5 agents"
    )
    billing_enabled: Optional[bool] = Field(
        default=False,
        description="Enable paid billing with Stripe (default: false, uses free credits)",
    )
    billing_api_key: Optional[str] = Field(
        None, description="Billing API key (required when billing_enabled=true)"
    )
    server_id: Optional[str] = Field(
        None, description="Target server ID (defaults to 'main' if not specified)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template": "echo",
                "name": "Datum",
                "environment": {
                    "OPENAI_API_KEY": "sk-...",
                    "CIRIS_SYSTEM_PROMPT": "You are a helpful assistant.",
                },
                "use_mock_llm": False,
                "enable_discord": True,
            }
        }
    )


class AgentUpdate(BaseModel):
    """
    Request payload for updating agent configuration.

    Sent to PATCH /manager/v1/agents/{agent_id}/config to modify
    environment variables and settings.
    """

    environment: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="Environment variables to update (None/empty string to delete)",
    )
    restart: bool = Field(default=True, description="Whether to restart container after update")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "environment": {
                    "CIRIS_ENABLE_DISCORD": "true",
                    "OPENAI_API_KEY": "sk-new-key...",
                    "OLD_VAR": None,  # Delete this variable
                },
                "restart": True,
            }
        }
    )


class AgentStatus(BaseModel):
    """
    Runtime status information for an agent.

    Represents current state from Docker and agent health checks.
    """

    status: Literal["running", "stopped", "restarting", "paused", "exited", "dead"] = Field(
        ..., description="Container status from Docker"
    )
    health: Optional[Literal["healthy", "unhealthy", "starting", "none"]] = Field(
        None, description="Health check status if available"
    )

    # Runtime state
    cognitive_state: Optional[Literal["WAKEUP", "WORK", "SHUTDOWN", "UNKNOWN"]] = Field(
        None, description="Agent cognitive state from status API"
    )
    version: Optional[str] = Field(None, description="Semantic version (e.g., 1.0.4-beta)")
    codename: Optional[str] = Field(None, description="Release codename (e.g., Graceful Guardian)")
    code_hash: Optional[str] = Field(None, description="Code hash for exact version identification")

    # Runtime configuration
    mock_llm: Optional[bool] = Field(None, description="Using mock LLM")
    discord_enabled: Optional[bool] = Field(None, description="Discord adapter enabled")

    # Computed flags
    update_available: bool = Field(
        default=False, description="Whether an update is available for this agent"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "running",
                "health": "healthy",
                "cognitive_state": "WORK",
                "version": "1.0.4-beta",
                "codename": "Graceful Guardian",
                "code_hash": "a1b2c3d4",
                "mock_llm": False,
                "discord_enabled": True,
                "update_available": False,
            }
        }
    )


class AgentInfo(BaseModel):
    """
    Complete agent information for API responses.

    Combines registry data, Docker status, and runtime information.
    This is the primary model returned by GET /manager/v1/agents.
    """

    # Identity
    agent_id: str = Field(..., description="Unique agent identifier")
    agent_name: str = Field(..., description="Human-friendly agent name")
    container_name: str = Field(..., description="Docker container name")

    # Network
    api_port: Optional[int] = Field(None, description="API port if running")
    api_endpoint: Optional[str] = Field(None, description="Full API endpoint URL")

    # Status
    status: str = Field(
        default="stopped", description="Container status: running, stopped, restarting, etc."
    )
    health: Optional[str] = Field(None, description="Agent health status")

    # Docker info
    image: Optional[str] = Field(None, description="Docker image")

    # Authentication
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
    template: str = Field(default="unknown", description="Template used to create agent")
    deployment: str = Field(
        default="CIRIS_DISCORD_PILOT",
        description="Deployment identifier (e.g., CIRIS_DISCORD_PILOT)",
    )
    server_id: Optional[str] = Field(
        default="main", description="Server ID where agent is deployed"
    )
    deployment_type: Optional[str] = Field(
        None,
        description="Deployment type: API_ONLY for remote servers, FULL for main server with GUI",
    )
    created_at: Optional[str] = Field(None, description="When agent was created (ISO 8601)")
    update_available: bool = Field(default=False, description="Whether an update is available")

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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "datum",
                "agent_name": "Datum",
                "container_name": "ciris-agent-datum",
                "api_port": 8001,
                "api_endpoint": "https://agents.ciris.ai/api/datum/v1",
                "status": "running",
                "health": "healthy",
                "image": "ghcr.io/cirisai/ciris-agent:1.0.4-beta",
                "oauth_status": "verified",
                "version": "1.0.4-beta",
                "codename": "Graceful Guardian",
                "code_hash": "a1b2c3d4",
                "cognitive_state": "WORK",
                "mock_llm": False,
                "discord_enabled": True,
                "template": "echo",
                "deployment": "CIRIS_DISCORD_PILOT",
                "server_id": "main",
                "created_at": "2025-01-15T10:30:00Z",
                "update_available": False,
            }
        }
    )


class AgentListItem(BaseModel):
    """
    Lightweight agent information for list views.

    Subset of AgentInfo with only essential fields for displaying
    agent lists in the UI.
    """

    agent_id: str = Field(..., description="Unique agent identifier")
    agent_name: str = Field(..., description="Human-friendly agent name")
    status: str = Field(..., description="Container status")
    api_port: Optional[int] = Field(None, description="API port if running")
    template: str = Field(default="unknown", description="Template used")
    version: Optional[str] = Field(None, description="Current version")
    health: Optional[str] = Field(None, description="Health status")
    update_available: bool = Field(default=False, description="Update available")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "datum",
                "agent_name": "Datum",
                "status": "running",
                "api_port": 8001,
                "template": "echo",
                "version": "1.0.4-beta",
                "health": "healthy",
                "update_available": False,
            }
        }
    )


class AgentMaintenanceMode(BaseModel):
    """
    Maintenance mode status for an agent.

    Response from GET /manager/v1/agents/{agent_id}/maintenance
    and request for POST /manager/v1/agents/{agent_id}/maintenance.
    """

    agent_id: str = Field(..., description="Agent identifier")
    do_not_autostart: bool = Field(..., description="Whether automatic restart is prevented")
    maintenance_mode: Literal["enabled", "disabled"] = Field(
        ..., description="Human-readable maintenance mode status"
    )
    message: Optional[str] = Field(None, description="Status message (for POST responses)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "datum",
                "do_not_autostart": True,
                "maintenance_mode": "enabled",
                "message": "Maintenance mode enabled for agent datum",
            }
        }
    )


class AgentOAuthStatus(BaseModel):
    """
    OAuth configuration status for an agent.

    Response from GET /manager/v1/agents/{agent_id}/oauth/verify
    showing OAuth setup status and callback URLs.
    """

    agent_id: str = Field(..., description="Agent identifier")
    configured: bool = Field(..., description="Whether OAuth has been configured")
    working: bool = Field(..., description="Whether OAuth is verified and working")
    status: Literal["pending", "configured", "verified"] = Field(
        ..., description="Current OAuth status"
    )
    callback_urls: Dict[str, str] = Field(..., description="OAuth callback URLs for each provider")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "datum",
                "configured": True,
                "working": True,
                "status": "verified",
                "callback_urls": {
                    "google": "https://agents.ciris.ai/v1/auth/oauth/datum/google/callback",
                    "github": "https://agents.ciris.ai/v1/auth/oauth/datum/github/callback",
                    "discord": "https://agents.ciris.ai/v1/auth/oauth/datum/discord/callback",
                },
            }
        }
    )
