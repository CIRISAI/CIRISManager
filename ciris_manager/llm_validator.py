"""
LLM configuration validation service.

Validates API keys by calling the /v1/models endpoint without consuming tokens.
Supports OpenAI-compatible providers: OpenAI, Together, Groq, OpenRouter.
"""

import logging
from typing import Optional, Tuple, List

import httpx

from ciris_manager.models.llm import PROVIDER_DEFAULTS, LLMProvider

logger = logging.getLogger(__name__)

# Timeout for validation requests (seconds)
VALIDATION_TIMEOUT = 15.0


async def validate_llm_config(
    provider: LLMProvider,
    api_key: str,
    model: str,
    api_base: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[List[str]]]:
    """
    Validate LLM configuration by testing the API connection.

    Calls the /v1/models endpoint to validate the API key without consuming tokens.
    Also checks if the specified model is accessible.

    Args:
        provider: Provider name (openai, together, groq, openrouter, custom)
        api_key: API key to validate
        model: Model identifier to check access for
        api_base: Custom API base URL (uses provider default if not provided)

    Returns:
        Tuple of (is_valid, error_message, available_models)
        - is_valid: True if API key is valid and model is accessible
        - error_message: Error description if validation failed, None otherwise
        - available_models: List of available model IDs if API key is valid
    """
    # Determine API base URL
    if api_base:
        base_url = api_base.rstrip("/")
    else:
        base_url = PROVIDER_DEFAULTS.get(provider, "https://api.openai.com/v1")

    models_url = f"{base_url}/models"

    # Log validation attempt (without exposing full key)
    key_hint = f"{api_key[:4]}...{api_key[-3:]}" if len(api_key) > 7 else "***"
    logger.info(f"Validating LLM config: provider={provider}, model={model}, key={key_hint}")

    try:
        async with httpx.AsyncClient(timeout=VALIDATION_TIMEOUT) as client:
            response = await client.get(
                models_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code == 401:
                logger.warning(f"LLM validation failed: Invalid API key for {provider}")
                return (False, "Invalid API key - authentication failed", None)

            if response.status_code == 403:
                logger.warning(f"LLM validation failed: Access denied for {provider}")
                return (False, "Access denied - check API key permissions", None)

            if response.status_code == 404:
                # Some providers don't expose /models endpoint
                logger.info(f"Provider {provider} does not expose /models endpoint, testing chat")
                return await _validate_via_chat(client, base_url, api_key, model)

            if response.status_code == 429:
                logger.warning(f"LLM validation failed: Rate limited by {provider}")
                return (False, "Rate limited - try again later", None)

            if response.status_code != 200:
                logger.warning(
                    f"LLM validation failed: Unexpected status {response.status_code} from {provider}"
                )
                return (
                    False,
                    f"API error: HTTP {response.status_code} - {response.text[:100]}",
                    None,
                )

            # Parse models response
            # Handle different response formats:
            # - OpenAI style: {"data": [{...}, {...}]}
            # - Together style: [{...}, {...}] (direct list)
            data = response.json()
            if isinstance(data, list):
                models_list = data
            elif isinstance(data, dict):
                models_list = data.get("data", [])
            else:
                models_list = []
            available_models = [
                m.get("id", "") if isinstance(m, dict) else str(m) for m in models_list if m
            ]

            logger.info(f"Found {len(available_models)} models from {provider}")

            # Check if requested model is available
            # Some providers use different model ID formats, so do a fuzzy match
            model_accessible = _model_is_accessible(model, available_models)

            if not model_accessible:
                # Model not in list, but API key is valid
                # This could be fine - some providers don't list all models
                logger.warning(
                    f"Model '{model}' not found in {provider} model list, "
                    f"but API key is valid. Available: {available_models[:10]}"
                )
                return (
                    True,
                    f"API key valid, but model '{model}' not found in available models. "
                    f"This may still work if the model exists.",
                    available_models,
                )

            logger.info(f"LLM validation successful: {provider}/{model}")
            return (True, None, available_models)

    except httpx.TimeoutException:
        logger.error(f"LLM validation timeout for {provider}")
        return (False, f"Connection timeout to {provider} API", None)

    except httpx.ConnectError as e:
        logger.error(f"LLM validation connection error for {provider}: {e}")
        return (False, f"Could not connect to {provider} API: {str(e)}", None)

    except Exception as e:
        logger.error(f"LLM validation error for {provider}: {e}")
        return (False, f"Validation error: {str(e)}", None)


async def _validate_via_chat(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
) -> Tuple[bool, Optional[str], Optional[List[str]]]:
    """
    Fallback validation via minimal chat completion request.

    Used when /models endpoint is not available.
    Sends a minimal request with max_tokens=1 to minimize cost.
    """
    chat_url = f"{base_url}/chat/completions"

    try:
        response = await client.post(
            chat_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
        )

        if response.status_code == 401:
            return (False, "Invalid API key - authentication failed", None)

        if response.status_code == 403:
            return (False, "Access denied - check API key permissions", None)

        if response.status_code == 404:
            return (False, f"Model '{model}' not found", None)

        if response.status_code == 429:
            return (False, "Rate limited - try again later", None)

        if response.status_code in [200, 201]:
            logger.info(f"Chat validation successful for model {model}")
            return (True, None, [model])

        return (
            False,
            f"API error: HTTP {response.status_code} - {response.text[:100]}",
            None,
        )

    except Exception as e:
        logger.error(f"Chat validation error: {e}")
        return (False, f"Chat validation error: {str(e)}", None)


def _model_is_accessible(requested_model: str, available_models: List[str]) -> bool:
    """
    Check if a model is accessible in the available models list.

    Performs exact match and fuzzy matching for common variations.
    """
    # Exact match
    if requested_model in available_models:
        return True

    # Lowercase match
    requested_lower = requested_model.lower()
    for model in available_models:
        if model.lower() == requested_lower:
            return True

    # Partial match for models with version suffixes
    # e.g., "gpt-4o" might match "gpt-4o-2024-08-06"
    for model in available_models:
        if model.lower().startswith(requested_lower):
            return True
        if requested_lower.startswith(model.lower()):
            return True

    return False


async def validate_primary_config(
    provider: LLMProvider,
    api_key: str,
    model: str,
    api_base: Optional[str] = None,
) -> dict:
    """
    Validate primary LLM configuration and return structured result.

    Args:
        provider: Provider name
        api_key: API key to validate
        model: Model identifier
        api_base: Custom API base URL

    Returns:
        Dictionary with validation result:
        {
            "valid": bool,
            "error": str or None,
            "models_available": list or None
        }
    """
    is_valid, error, models = await validate_llm_config(provider, api_key, model, api_base)
    return {
        "valid": is_valid,
        "error": error,
        "models_available": models,
    }
