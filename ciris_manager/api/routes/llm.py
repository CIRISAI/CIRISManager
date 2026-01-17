"""
LLM configuration management routes.

This module provides endpoints for managing LLM provider configurations:
- Get current LLM config (with keys redacted)
- Set/update LLM config (with validation)
- Validate config without saving
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ciris_manager.models.llm import (
    LLMConfig,
    LLMConfigUpdate,
    LLMValidateRequest,
    LLMValidateResponse,
    redact_llm_config,
    LLMProviderConfig,
)
from ciris_manager.llm_validator import validate_llm_config
from .dependencies import get_manager, auth_dependency, resolve_agent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["llm"])


@router.get("/agents/{agent_id}/llm")
async def get_llm_configuration(
    agent_id: str,
    occurrence_id: Optional[str] = Query(None, description="Occurrence ID for disambiguation"),
    server_id: Optional[str] = Query(None, description="Server ID for disambiguation"),
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get LLM configuration for an agent.

    Returns the configuration with API keys redacted for security.
    Shows provider, model, and api_base, but only key hints (e.g., "sk-a...xyz").

    Args:
        agent_id: The agent ID
        occurrence_id: Optional occurrence ID for multi-instance disambiguation
        server_id: Optional server ID for multi-server disambiguation

    Returns:
        LLM configuration with redacted keys, or null if not configured
    """
    # Resolve agent (validates it exists)
    agent = resolve_agent(manager, agent_id, occurrence_id, server_id)

    # Get LLM config (decrypted)
    config = manager.agent_registry.get_llm_config(
        agent.agent_id,
        occurrence_id=agent.occurrence_id,
        server_id=agent.server_id,
    )

    if not config:
        return {
            "agent_id": agent.agent_id,
            "llm_config": None,
            "message": "No LLM configuration set. Using environment variables or defaults.",
        }

    # Convert to pydantic model for redaction
    try:
        llm_config = LLMConfig(
            primary=LLMProviderConfig(**config["primary"]),
            backup=LLMProviderConfig(**config["backup"]) if config.get("backup") else None,
        )
        redacted = redact_llm_config(llm_config)
        return {
            "agent_id": agent.agent_id,
            "llm_config": redacted.model_dump(),
        }
    except Exception as e:
        logger.error(f"Error processing LLM config for {agent_id}: {e}")
        return {
            "agent_id": agent.agent_id,
            "llm_config": None,
            "error": "Configuration exists but could not be processed",
        }


@router.put("/agents/{agent_id}/llm")
async def set_llm_configuration(
    agent_id: str,
    config: LLMConfigUpdate,
    validate: bool = Query(True, description="Validate API keys before saving"),
    restart: bool = Query(True, description="Restart agent container after update"),
    occurrence_id: Optional[str] = Query(None, description="Occurrence ID for disambiguation"),
    server_id: Optional[str] = Query(None, description="Server ID for disambiguation"),
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Set or update LLM configuration for an agent.

    By default, validates API keys before saving by calling the provider's
    /v1/models endpoint. Use validate=false to skip validation.

    By default, restarts the agent container after updating configuration.
    Use restart=false to update config without restarting.

    Args:
        agent_id: The agent ID
        config: LLM configuration update payload
        validate: Whether to validate API keys before saving (default: true)
        restart: Whether to restart container after update (default: true)
        occurrence_id: Optional occurrence ID for multi-instance disambiguation
        server_id: Optional server ID for multi-server disambiguation

    Returns:
        Success message with validation results
    """
    # Resolve agent
    agent = resolve_agent(manager, agent_id, occurrence_id, server_id)

    validation_results = {}

    # Validate primary if requested
    if validate:
        logger.info(f"Validating primary LLM config for {agent_id}")
        is_valid, error, models = await validate_llm_config(
            provider=config.primary_provider,
            api_key=config.primary_api_key,
            model=config.primary_model,
            api_base=config.primary_api_base,
        )
        validation_results["primary"] = {
            "valid": is_valid,
            "error": error,
            "models_available": models[:10] if models else None,  # Limit to 10 models
        }

        if not is_valid and error and "valid" not in error.lower():
            raise HTTPException(
                status_code=400,
                detail=f"Primary LLM validation failed: {error}",
            )

        # Validate backup if provided
        if config.backup_provider and config.backup_api_key and config.backup_model:
            logger.info(f"Validating backup LLM config for {agent_id}")
            is_valid, error, models = await validate_llm_config(
                provider=config.backup_provider,
                api_key=config.backup_api_key,
                model=config.backup_model,
                api_base=config.backup_api_base,
            )
            validation_results["backup"] = {
                "valid": is_valid,
                "error": error,
                "models_available": models[:10] if models else None,
            }

            if not is_valid and error and "valid" not in error.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"Backup LLM validation failed: {error}",
                )

    # Convert to storage format
    llm_config = config.to_llm_config()
    config_dict = {
        "primary": {
            "provider": llm_config.primary.provider,
            "api_key": llm_config.primary.api_key,
            "model": llm_config.primary.model,
            "api_base": llm_config.primary.api_base,
        }
    }
    if llm_config.backup:
        config_dict["backup"] = {
            "provider": llm_config.backup.provider,
            "api_key": llm_config.backup.api_key,
            "model": llm_config.backup.model,
            "api_base": llm_config.backup.api_base,
        }

    # Save to registry (encrypts API keys)
    success = manager.agent_registry.set_llm_config(
        agent.agent_id,
        config_dict,
        occurrence_id=agent.occurrence_id,
        server_id=agent.server_id,
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to save LLM configuration",
        )

    result: Dict[str, Any] = {
        "agent_id": agent.agent_id,
        "message": "LLM configuration updated successfully",
        "validation": validation_results if validate else "skipped",
    }

    # Restart container if requested
    if restart:
        try:
            # Regenerate compose file with new LLM config
            await manager.regenerate_agent_compose(agent.agent_id)

            # Restart the container
            container_name = f"ciris-agent-{agent.name}"
            restarted = await manager.restart_container(container_name, server_id=agent.server_id)
            result["restarted"] = restarted
            if restarted:
                result["message"] += " and container restarted"
            else:
                result["warning"] = "Config saved but container restart failed"
        except Exception as e:
            logger.error(f"Failed to restart container for {agent_id}: {e}")
            result["warning"] = f"Config saved but restart failed: {str(e)}"
    else:
        result["message"] += " (restart skipped)"

    return result


@router.delete("/agents/{agent_id}/llm")
async def delete_llm_configuration(
    agent_id: str,
    restart: bool = Query(True, description="Restart agent container after deletion"),
    occurrence_id: Optional[str] = Query(None, description="Occurrence ID for disambiguation"),
    server_id: Optional[str] = Query(None, description="Server ID for disambiguation"),
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Delete LLM configuration for an agent.

    After deletion, the agent will fall back to environment variables.

    Args:
        agent_id: The agent ID
        restart: Whether to restart container after deletion (default: true)
        occurrence_id: Optional occurrence ID for multi-instance disambiguation
        server_id: Optional server ID for multi-server disambiguation

    Returns:
        Success message
    """
    # Resolve agent
    agent = resolve_agent(manager, agent_id, occurrence_id, server_id)

    # Clear LLM config
    success = manager.agent_registry.clear_llm_config(
        agent.agent_id,
        occurrence_id=agent.occurrence_id,
        server_id=agent.server_id,
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete LLM configuration",
        )

    result: Dict[str, Any] = {
        "agent_id": agent.agent_id,
        "message": "LLM configuration deleted. Agent will use environment variables.",
    }

    # Restart container if requested
    if restart:
        try:
            await manager.regenerate_agent_compose(agent.agent_id)
            container_name = f"ciris-agent-{agent.name}"
            restarted = await manager.restart_container(container_name, server_id=agent.server_id)
            result["restarted"] = restarted
        except Exception as e:
            logger.error(f"Failed to restart container for {agent_id}: {e}")
            result["warning"] = f"Config deleted but restart failed: {str(e)}"

    return result


@router.post("/agents/{agent_id}/llm/validate")
async def validate_llm_config_endpoint(
    agent_id: str,
    config: LLMValidateRequest,
    occurrence_id: Optional[str] = Query(None, description="Occurrence ID for disambiguation"),
    server_id: Optional[str] = Query(None, description="Server ID for disambiguation"),
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> LLMValidateResponse:
    """
    Validate LLM configuration without saving.

    Tests the API key by calling the provider's /v1/models endpoint.
    Does not consume tokens or modify agent configuration.

    Args:
        agent_id: The agent ID (for auth context)
        config: LLM configuration to validate
        occurrence_id: Optional occurrence ID for multi-instance disambiguation
        server_id: Optional server ID for multi-server disambiguation

    Returns:
        Validation result with available models if valid
    """
    # Resolve agent (just for validation/authorization)
    resolve_agent(manager, agent_id, occurrence_id, server_id)

    # Validate
    is_valid, error, models = await validate_llm_config(
        provider=config.provider,
        api_key=config.api_key,
        model=config.model,
        api_base=config.api_base,
    )

    return LLMValidateResponse(
        valid=is_valid,
        error=error,
        models_available=models[:20] if models else None,  # Limit to 20 models
    )
