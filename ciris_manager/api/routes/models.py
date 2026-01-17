"""
Shared response models for route modules.

These models are used across multiple route modules for consistent API responses.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ciris_manager.models import AgentInfo


class AgentResponse(BaseModel):
    """Response model for agent information."""

    agent_id: str
    name: str
    container: str
    port: int
    api_endpoint: str
    template: str
    status: str


class AgentListResponse(BaseModel):
    """Response model for agent list."""

    agents: List[AgentInfo]


class StatusResponse(BaseModel):
    """Response model for manager status."""

    status: str
    version: str = "2.2.0"
    components: Dict[str, str]
    auth_mode: Optional[str] = None
    uptime_seconds: Optional[int] = None
    start_time: Optional[str] = None
    system_metrics: Optional[Dict[str, Any]] = None


class TemplateListResponse(BaseModel):
    """Response model for template list."""

    templates: Dict[str, str]  # Template name -> description
    pre_approved: List[str]


class PortRange(BaseModel):
    """Port range information."""

    start: int
    end: int


class AllocatedPortsResponse(BaseModel):
    """Response model for allocated ports."""

    allocated: List[int]
    reserved: List[int]
    range: PortRange


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    healthy: bool = True


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    success: bool = True


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str
    detail: Optional[str] = None
