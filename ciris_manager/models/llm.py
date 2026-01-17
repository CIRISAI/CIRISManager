"""
Pydantic models for LLM configuration management.

These models provide type-safe interfaces for configuring LLM providers
on agents, supporting primary and backup providers with API key validation.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


# Provider type literals
LLMProvider = Literal["openai", "together", "groq", "openrouter", "custom"]

# Default API base URLs for known providers
PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class LLMProviderConfig(BaseModel):
    """
    Configuration for a single LLM provider.

    All providers must be OpenAI-compatible (use the same API format).
    """

    provider: LLMProvider = Field(
        ...,
        description="Provider name: openai, together, groq, openrouter, or custom",
    )
    api_key: str = Field(
        ...,
        description="API key for the provider (stored encrypted at rest)",
        min_length=1,
    )
    model: str = Field(
        ...,
        description="Model identifier (e.g., gpt-4o, llama-3.1-70b-versatile)",
        min_length=1,
    )
    api_base: Optional[str] = Field(
        None,
        description="Custom API base URL. If not provided, uses provider default.",
    )

    @property
    def effective_api_base(self) -> str:
        """Get the API base URL to use (custom or provider default)."""
        if self.api_base:
            return self.api_base
        return PROVIDER_DEFAULTS.get(self.provider, "https://api.openai.com/v1")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider": "openai",
                "api_key": "sk-...",
                "model": "gpt-4o",
                "api_base": None,
            }
        }
    )


class LLMConfig(BaseModel):
    """
    Complete LLM configuration for an agent.

    Supports primary and optional backup providers. The agent handles
    failover logic - the manager only stores and provides configuration.
    """

    primary: LLMProviderConfig = Field(
        ...,
        description="Primary LLM provider configuration",
    )
    backup: Optional[LLMProviderConfig] = Field(
        None,
        description="Backup LLM provider configuration (optional)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "primary": {
                    "provider": "openai",
                    "api_key": "sk-...",
                    "model": "gpt-4o",
                },
                "backup": {
                    "provider": "groq",
                    "api_key": "gsk_...",
                    "model": "llama-3.1-70b-versatile",
                },
            }
        }
    )


class LLMConfigResponse(BaseModel):
    """
    Response model for LLM configuration with API keys redacted.

    Used when returning LLM config to clients - never exposes full API keys.
    """

    primary: "LLMProviderConfigRedacted" = Field(
        ...,
        description="Primary LLM provider configuration (key redacted)",
    )
    backup: Optional["LLMProviderConfigRedacted"] = Field(
        None,
        description="Backup LLM provider configuration (key redacted)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "primary": {
                    "provider": "openai",
                    "api_key_hint": "sk-a...xyz",
                    "model": "gpt-4o",
                    "api_base": "https://api.openai.com/v1",
                },
                "backup": {
                    "provider": "groq",
                    "api_key_hint": "gsk_a...xyz",
                    "model": "llama-3.1-70b-versatile",
                    "api_base": "https://api.groq.com/openai/v1",
                },
            }
        }
    )


class LLMProviderConfigRedacted(BaseModel):
    """
    LLM provider config with API key redacted for safe display.
    """

    provider: LLMProvider = Field(
        ...,
        description="Provider name",
    )
    api_key_hint: str = Field(
        ...,
        description="Redacted API key showing only first/last chars (e.g., sk-a...xyz)",
    )
    model: str = Field(
        ...,
        description="Model identifier",
    )
    api_base: str = Field(
        ...,
        description="Effective API base URL",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider": "openai",
                "api_key_hint": "sk-a...xyz",
                "model": "gpt-4o",
                "api_base": "https://api.openai.com/v1",
            }
        }
    )


class LLMConfigUpdate(BaseModel):
    """
    Request model for updating LLM configuration.

    Used with PUT /agents/{id}/llm endpoint.
    """

    primary_provider: LLMProvider = Field(
        ...,
        description="Primary provider name",
    )
    primary_api_key: str = Field(
        ...,
        description="Primary API key",
        min_length=1,
    )
    primary_model: str = Field(
        ...,
        description="Primary model identifier",
        min_length=1,
    )
    primary_api_base: Optional[str] = Field(
        None,
        description="Primary custom API base URL",
    )
    backup_provider: Optional[LLMProvider] = Field(
        None,
        description="Backup provider name",
    )
    backup_api_key: Optional[str] = Field(
        None,
        description="Backup API key",
    )
    backup_model: Optional[str] = Field(
        None,
        description="Backup model identifier",
    )
    backup_api_base: Optional[str] = Field(
        None,
        description="Backup custom API base URL",
    )

    def to_llm_config(self) -> LLMConfig:
        """Convert to LLMConfig model."""
        primary = LLMProviderConfig(
            provider=self.primary_provider,
            api_key=self.primary_api_key,
            model=self.primary_model,
            api_base=self.primary_api_base,
        )
        backup = None
        if self.backup_provider and self.backup_api_key and self.backup_model:
            backup = LLMProviderConfig(
                provider=self.backup_provider,
                api_key=self.backup_api_key,
                model=self.backup_model,
                api_base=self.backup_api_base,
            )
        return LLMConfig(primary=primary, backup=backup)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "primary_provider": "openai",
                "primary_api_key": "sk-...",
                "primary_model": "gpt-4o",
                "backup_provider": "groq",
                "backup_api_key": "gsk_...",
                "backup_model": "llama-3.1-70b-versatile",
            }
        }
    )


class LLMValidateRequest(BaseModel):
    """
    Request model for validating LLM configuration without saving.

    Used with POST /agents/{id}/llm/validate endpoint.
    """

    provider: LLMProvider = Field(
        ...,
        description="Provider name",
    )
    api_key: str = Field(
        ...,
        description="API key to validate",
        min_length=1,
    )
    model: str = Field(
        ...,
        description="Model identifier to check access",
        min_length=1,
    )
    api_base: Optional[str] = Field(
        None,
        description="Custom API base URL",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider": "together",
                "api_key": "...",
                "model": "meta-llama/Llama-3.1-70B-Instruct-Turbo",
            }
        }
    )


class LLMValidateResponse(BaseModel):
    """
    Response model for LLM validation.
    """

    valid: bool = Field(
        ...,
        description="Whether the configuration is valid",
    )
    error: Optional[str] = Field(
        None,
        description="Error message if validation failed",
    )
    models_available: Optional[list[str]] = Field(
        None,
        description="List of available models (if API key is valid)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "valid": True,
                "error": None,
                "models_available": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
            }
        }
    )


def redact_api_key(api_key: str) -> str:
    """
    Redact an API key for safe display.

    Shows first 4 and last 3 characters with ... in between.
    Example: sk-abc123xyz789 -> sk-a...789
    """
    if not api_key:
        return "***"
    if len(api_key) <= 8:
        return f"{api_key[0]}...{api_key[-1]}" if len(api_key) > 1 else "***"
    return f"{api_key[:4]}...{api_key[-3:]}"


def redact_provider_config(config: LLMProviderConfig) -> LLMProviderConfigRedacted:
    """Convert an LLMProviderConfig to its redacted version."""
    return LLMProviderConfigRedacted(
        provider=config.provider,
        api_key_hint=redact_api_key(config.api_key),
        model=config.model,
        api_base=config.effective_api_base,
    )


def redact_llm_config(config: LLMConfig) -> LLMConfigResponse:
    """Convert an LLMConfig to its redacted response version."""
    return LLMConfigResponse(
        primary=redact_provider_config(config.primary),
        backup=redact_provider_config(config.backup) if config.backup else None,
    )
