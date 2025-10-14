"""
Deployment-related data models for CIRISManager.

These models define the structure for deployment notifications, status tracking,
events, history, rollback options, and canary group information used throughout
the deployment orchestration system.
"""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, model_validator


class DeploymentNotification(BaseModel):
    """
    CD update notification from GitHub Actions.

    This is the payload sent by CI/CD pipelines to trigger deployments.
    At least one image field must be provided.
    """

    agent_image: Optional[str] = Field(
        None, description="New agent image (e.g., ghcr.io/cirisai/ciris-agent:latest)"
    )
    gui_image: Optional[str] = Field(None, description="New GUI image if updated")
    nginx_image: Optional[str] = Field(None, description="New nginx image if updated")
    message: str = Field(default="Update available", description="Human-readable update message")
    strategy: Literal["canary", "immediate", "manual"] = Field(
        default="canary",
        description="Deployment strategy: canary (staged rollout), immediate (all at once), manual (agent-controlled)",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional deployment metadata"
    )

    # Enhanced fields for informed consent
    source: Optional[str] = Field(
        default="github-actions", description="Source of update notification"
    )
    commit_sha: Optional[str] = Field(None, description="Git commit SHA for this update")
    version: Optional[str] = Field(None, description="Semantic version if available")
    changelog: Optional[str] = Field(None, description="Full commit messages from release")
    risk_level: Optional[Literal["low", "medium", "high", "unknown"]] = Field(
        default="unknown", description="Risk assessment level for this deployment"
    )

    @model_validator(mode="after")
    def validate_at_least_one_image(self) -> "DeploymentNotification":
        """Ensure at least one image is provided."""
        if not any([self.agent_image, self.gui_image, self.nginx_image]):
            raise ValueError(
                "At least one of agent_image, gui_image, or nginx_image must be provided"
            )
        return self


class DeploymentEvent(BaseModel):
    """
    A single event in a deployment's timeline.

    Events track the progression and significant actions during a deployment,
    providing an audit trail and debugging information.
    """

    timestamp: str = Field(..., description="ISO 8601 timestamp when event occurred")
    event_type: str = Field(
        ...,
        description="Type of event (e.g., 'staged', 'launched', 'phase_started', 'agent_updated', 'completed', 'failed')",
    )
    message: str = Field(..., description="Human-readable event description")
    details: Optional[Dict[str, Any]] = Field(
        None, description="Additional structured data about the event"
    )


class CanaryGroup(BaseModel):
    """
    Information about a canary deployment group.

    Canary deployments are staged in phases:
    - explorers: 10% of agents, first to receive updates
    - early_adopters: 20% of agents, receive updates after explorers succeed
    - general: 70% of agents, receive updates after early adopters succeed
    """

    name: Literal["explorer", "early_adopter", "general"] = Field(
        ..., description="Canary group name"
    )
    agent_ids: List[str] = Field(
        default_factory=list, description="Agent IDs assigned to this group"
    )
    agents_total: int = Field(default=0, description="Total number of agents in this group")
    agents_updated: int = Field(default=0, description="Number of agents successfully updated")
    agents_failed: int = Field(default=0, description="Number of agents that failed to update")
    agents_deferred: int = Field(default=0, description="Number of agents that deferred the update")
    phase_started_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when this phase started"
    )
    phase_completed_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when this phase completed"
    )
    success_rate: Optional[float] = Field(
        None, description="Success rate (0.0-1.0) for this group, calculated after completion"
    )
    avg_time_to_work: Optional[float] = Field(
        None, description="Average time in minutes for agents to reach WORK state"
    )


class DeploymentStatus(BaseModel):
    """
    Current status of a deployment.

    Tracks the progress, state, and results of an active or completed deployment.
    Used for both active deployments and staged deployments awaiting approval.
    """

    deployment_id: str = Field(..., description="Unique deployment identifier")
    notification: Optional[DeploymentNotification] = Field(
        None, description="Original update notification that triggered this deployment"
    )
    agents_total: int = Field(..., description="Total number of agents affected by this deployment")
    agents_updated: int = Field(default=0, description="Number of agents successfully updated")
    agents_deferred: int = Field(default=0, description="Number of agents that deferred the update")
    agents_failed: int = Field(default=0, description="Number of agents that failed to update")
    canary_phase: Optional[Literal["explorers", "early_adopters", "general"]] = Field(
        None, description="Current canary phase if using canary strategy"
    )
    started_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when deployment execution started"
    )
    staged_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when deployment was staged for review"
    )
    completed_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when deployment completed or failed"
    )
    status: Literal[
        "pending",
        "in_progress",
        "paused",
        "completed",
        "failed",
        "cancelled",
        "rejected",
        "rolling_back",
        "rolled_back",
        "rollback_proposed",
    ] = Field(default="in_progress", description="Current deployment status")
    message: str = Field(..., description="Current status message providing context")
    events: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Timeline of deployment events (untyped for backwards compatibility)",
    )
    strategy: Optional[Literal["canary", "immediate", "manual"]] = Field(
        default="canary", description="Deployment strategy being used"
    )
    updated_at: Optional[str] = Field(None, description="ISO 8601 timestamp of last status update")
    agents_pending_restart: List[str] = Field(
        default_factory=list,
        description="Agent IDs that have shutdown and are pending container restart",
    )
    agents_in_progress: Dict[str, str] = Field(
        default_factory=dict,
        description="Agents currently being processed: agent_id -> state (shutting_down, restarting, etc)",
    )
    canary_assignments: Optional[Dict[str, List[str]]] = Field(
        None,
        description="Canary group assignments for this deployment: explorers, early_adopters, general",
    )


class DeploymentHistory(BaseModel):
    """
    Historical record of a completed deployment.

    Simplified view of deployment information for history/audit purposes.
    Contains essential information about past deployments.
    """

    deployment_id: str = Field(..., description="Unique deployment identifier")
    started_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when deployment started"
    )
    completed_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when deployment completed"
    )
    status: str = Field(..., description="Final deployment status")
    strategy: Optional[str] = Field(None, description="Deployment strategy used")
    agents_total: int = Field(default=0, description="Total number of agents in deployment")
    agents_updated: int = Field(default=0, description="Number of agents successfully updated")
    agents_failed: int = Field(default=0, description="Number of agents that failed")
    agents_deferred: int = Field(default=0, description="Number of agents that deferred")
    agent_image: Optional[str] = Field(None, description="Agent image deployed (if applicable)")
    gui_image: Optional[str] = Field(None, description="GUI image deployed (if applicable)")
    nginx_image: Optional[str] = Field(None, description="Nginx image deployed (if applicable)")
    message: Optional[str] = Field(None, description="Deployment message")
    version: Optional[str] = Field(None, description="Version identifier if available")
    commit_sha: Optional[str] = Field(None, description="Git commit SHA")


class RollbackOption(BaseModel):
    """
    Information about available rollback versions for a component.

    Provides version history for rolling back deployments if issues occur.
    Supports n-1, n-2 versioning as well as specific version targeting.
    """

    component: Literal["agent", "gui", "nginx"] = Field(..., description="Component type")
    current: Optional[str] = Field(None, description="Currently deployed version/image")
    n_minus_1: Optional[str] = Field(
        None, description="Previous version (n-1), most recent rollback target"
    )
    n_minus_2: Optional[str] = Field(
        None, description="Two versions back (n-2), secondary rollback target"
    )
    deployment_id: Optional[str] = Field(
        None, description="Deployment ID associated with current version"
    )
    deployed_at: Optional[str] = Field(
        None, description="ISO 8601 timestamp when current version was deployed"
    )
    available_versions: Optional[List[str]] = Field(
        None, description="List of all available versions for rollback"
    )
