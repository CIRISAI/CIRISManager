"""
Template routes - template listing and details.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict

import aiofiles  # type: ignore
import yaml
from fastapi import APIRouter, Depends, HTTPException

from .dependencies import get_manager, get_auth_dependency
from .models import TemplateListResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["templates"])

# Get auth dependency
auth_dependency = get_auth_dependency()


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(
    manager: Any = Depends(get_manager),
) -> TemplateListResponse:
    """List available templates."""
    # Get pre-approved templates from manifest (if it exists)
    pre_approved = manager.template_verifier.list_pre_approved_templates()

    # Scan template directory for all available templates
    all_templates = {}
    templates_dir = Path(manager.config.manager.templates_directory)

    if templates_dir.exists():
        for template_file in templates_dir.glob("*.yaml"):
            template_name = template_file.stem
            # For now, just return the template name and description
            # The actual config should be loaded when a specific template is selected
            # Just return template metadata - GUI gets env vars from separate endpoint
            desc = f"{template_name.replace('-', ' ').title()} agent template"
            all_templates[template_name] = desc

    # For development: if no manifest exists, treat some templates as pre-approved
    if not pre_approved and all_templates:
        # Common templates that don't need special approval
        default_pre_approved = ["echo", "scout", "sage", "test"]
        pre_approved_list = [t for t in default_pre_approved if t in all_templates]
    else:
        pre_approved_list = list(pre_approved.keys())

    return TemplateListResponse(templates=all_templates, pre_approved=pre_approved_list)


@router.get("/templates/{template_name}/details")
async def get_template_details(
    template_name: str,
    manager: Any = Depends(get_manager),
) -> Dict[str, Any]:
    """Get detailed information about a specific template including stewardship tier."""
    # Validate template name to prevent path traversal
    if not re.match(r"^[a-zA-Z0-9_-]+$", template_name):
        raise HTTPException(status_code=400, detail="Invalid template name")

    # Additional check for path traversal attempts
    if ".." in template_name or "/" in template_name or "\\" in template_name:
        raise HTTPException(status_code=400, detail="Invalid template name")

    templates_dir = Path(manager.config.manager.templates_directory)
    template_file = templates_dir / f"{template_name}.yaml"

    # Ensure the resolved path is within the templates directory
    try:
        template_file = template_file.resolve()
        templates_dir_resolved = templates_dir.resolve()
        if not str(template_file).startswith(str(templates_dir_resolved)):
            raise HTTPException(status_code=400, detail="Invalid template path")
    except (OSError, RuntimeError):
        raise HTTPException(status_code=400, detail="Invalid template path")

    if not template_file.exists():
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")

    try:
        async with aiofiles.open(template_file, "r") as f:
            content = await f.read()
            template_data = yaml.safe_load(content)

        # Extract stewardship tier from stewardship section
        stewardship_tier = template_data.get("stewardship", {}).get("stewardship_tier", 1)

        return {
            "name": template_name,
            "description": template_data.get("description", ""),
            "stewardship_tier": stewardship_tier,
            "requires_wa_review": stewardship_tier >= 4,
        }
    except Exception as e:
        logger.error(f"Failed to load template {template_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to load template details")


@router.get("/env/default")
async def get_default_env(
    manager: Any = Depends(get_manager),
    _user: dict = auth_dependency,
) -> Dict[str, str]:
    """Get default environment variables for agent creation."""
    # Try to read from production .env file first
    env_file_path = Path("/home/ciris/.env")
    if env_file_path.exists():
        try:
            async with aiofiles.open(env_file_path, "r") as f:
                content = await f.read()
            # Filter out sensitive values and keep only keys we want to expose
            lines = []
            sensitive_keys = {
                "DISCORD_BOT_TOKEN",
                "OPENAI_API_KEY",
                "CIRIS_OPENAI_API_KEY_2",
                "CIRIS_OPENAI_VISION_KEY",
            }

            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key = line.split("=", 1)[0].strip()
                    # Keep the key but clear sensitive values
                    if key in sensitive_keys:
                        lines.append(f"{key}=")
                    else:
                        lines.append(line)

            # Add any missing essential keys
            existing_keys = {line.split("=")[0] for line in lines if "=" in line}
            if "CIRIS_API_PORT" not in existing_keys:
                lines.append("CIRIS_API_PORT=8080")
            if "CIRIS_API_HOST" not in existing_keys:
                lines.append("CIRIS_API_HOST=0.0.0.0")

            return {"content": "\n".join(lines)}
        except Exception as e:
            logger.warning(f"Failed to read default .env file: {e}")

    # Fallback to hardcoded defaults if file doesn't exist
    env_vars = [
        # Core CIRIS requirements
        "LLM_PROVIDER=openai",
        "OPENAI_API_KEY=",  # User must provide
        "DATABASE_URL=sqlite:////app/data/ciris_engine.db",
        "CIRIS_API_HOST=0.0.0.0",
        "CIRIS_API_PORT=8080",  # Will be dynamically assigned
        "JWT_SECRET_KEY=generate-with-openssl-rand-hex-32",
        "ENVIRONMENT=production",
        "LOG_LEVEL=INFO",
        # Discord
        "DISCORD_BOT_TOKEN=",
        "DISCORD_CHANNEL_IDS=",
        "DISCORD_DEFERRAL_CHANNEL_ID=",
        "WA_USER_IDS=",
        # OAuth
        "OAUTH_CALLBACK_BASE_URL=https://agents.ciris.ai",
    ]

    return {"content": "\n".join(env_vars)}
