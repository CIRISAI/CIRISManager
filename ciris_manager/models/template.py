"""
Pydantic models for template-related data structures.

These models define the schema for agent templates, including
basic template information, detailed configuration, and environment
variable structures.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any


class TemplateInfo(BaseModel):
    """
    Basic template information for list views.

    Used in template listing endpoints to provide a summary
    of available agent templates.
    """

    name: str = Field(description="Template identifier name")
    description: str = Field(description="Human-readable description of the template")
    stewardship_tier: int = Field(default=1, description="Stewardship tier level (1-5)", ge=1, le=5)
    pre_approved: bool = Field(default=False, description="Whether the template is pre-approved")
    checksum: Optional[str] = Field(
        default=None, description="SHA256 checksum of the template file"
    )


class TemplateDetails(BaseModel):
    """
    Detailed template information including full configuration.

    Used when retrieving complete template details, including
    role description, permitted actions, guardrails, and the
    full template YAML structure.
    """

    name: str = Field(description="Template identifier name")
    description: str = Field(description="Human-readable description of the template")
    stewardship_tier: int = Field(default=1, description="Stewardship tier level (1-5)", ge=1, le=5)
    pre_approved: bool = Field(default=False, description="Whether the template is pre-approved")
    role_description: Optional[str] = Field(
        default=None, description="Detailed role description for the agent"
    )
    permitted_actions: List[str] = Field(
        default_factory=list,
        description="List of actions the agent is permitted to perform",
    )
    guardrails: Dict[str, Any] = Field(
        default_factory=dict, description="Guardrails configuration for the agent"
    )
    full_template: Dict[str, Any] = Field(
        default_factory=dict, description="Complete template YAML data structure"
    )
    requires_wa_review: bool = Field(
        default=False,
        description="Whether the template requires Wisdom Authority review (tier >= 4)",
    )


class TemplateEnvironment(BaseModel):
    """
    Template environment variable configuration.

    Provides default environment variables for agent creation,
    with sensitive values masked or cleared.
    """

    content: str = Field(
        description="Environment variable content in KEY=VALUE format, one per line"
    )


class TemplateValidation(BaseModel):
    """
    Template validation result.

    Used when validating template structure and configuration
    for correctness and completeness.
    """

    name: str = Field(description="Template identifier name")
    valid: bool = Field(description="Whether the template is valid")
    pre_approved: bool = Field(default=False, description="Whether the template is pre-approved")
    stewardship_tier: int = Field(default=1, description="Stewardship tier level (1-5)", ge=1, le=5)
    errors: List[str] = Field(default_factory=list, description="Validation errors found")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")


class TemplateListResponse(BaseModel):
    """
    Response model for template list endpoint.

    Contains a mapping of template names to descriptions and
    a list of pre-approved template names.
    """

    templates: Dict[str, str] = Field(
        default_factory=dict, description="Template name to description mapping"
    )
    pre_approved: List[str] = Field(
        default_factory=list, description="List of pre-approved template names"
    )
