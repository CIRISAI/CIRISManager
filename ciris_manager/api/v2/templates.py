"""
Templates namespace - Agent template management.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List
from pathlib import Path
import yaml

from .models import Template
from ..auth import get_current_user
from ...core import get_manager
from ...template_verifier import TemplateVerifier


router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("")
async def list_templates(_user: Dict[str, str] = Depends(get_current_user)) -> List[Template]:
    """
    List all available templates.
    """
    manager = get_manager()
    templates_dir = Path(manager.config.manager.templates_directory)

    if not templates_dir.exists():
        return []

    templates = []
    verifier = TemplateVerifier()

    for template_file in templates_dir.glob("*.yaml"):
        template_name = template_file.stem

        try:
            with open(template_file, "r") as f:
                template_data = yaml.safe_load(f)

            # Check if pre-approved
            is_pre_approved = verifier.is_pre_approved(template_name, template_file)

            # Get stewardship tier
            stewardship_tier = template_data.get("stewardship", {}).get("stewardship_tier", 1)

            # Get description
            description = template_data.get("description", "No description")

            templates.append(
                Template(
                    name=template_name,
                    description=description,
                    stewardship_tier=stewardship_tier,
                    pre_approved=is_pre_approved,
                    checksum=None,  # We could calculate if needed
                )
            )
        except Exception:
            # Skip invalid templates
            continue

    # Sort by name
    templates.sort(key=lambda x: x.name)

    return templates


@router.get("/{name}")
async def get_template(
    name: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get template details.
    """
    manager = get_manager()
    templates_dir = Path(manager.config.manager.templates_directory)
    template_file = templates_dir / f"{name}.yaml"

    if not template_file.exists():
        raise HTTPException(status_code=404, detail=f"Template {name} not found")

    try:
        with open(template_file, "r") as f:
            template_data = yaml.safe_load(f)

        verifier = TemplateVerifier()
        is_pre_approved = verifier.is_pre_approved(name, template_file)

        # Return template info
        return {
            "name": name,
            "description": template_data.get("description", "No description"),
            "stewardship_tier": template_data.get("stewardship", {}).get("stewardship_tier", 1),
            "pre_approved": is_pre_approved,
            "role_description": template_data.get("role_description"),
            "permitted_actions": template_data.get("permitted_actions", []),
            "guardrails": template_data.get("guardrails_config", {}),
            "full_template": template_data,  # Include full template for reference
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading template: {str(e)}")


@router.post("/{name}/validate")
async def validate_template(
    name: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Validate a template.
    """
    manager = get_manager()
    templates_dir = Path(manager.config.manager.templates_directory)
    template_file = templates_dir / f"{name}.yaml"

    if not template_file.exists():
        raise HTTPException(status_code=404, detail=f"Template {name} not found")

    try:
        # Load template
        with open(template_file, "r") as f:
            template_data = yaml.safe_load(f)

        # Check pre-approval
        verifier = TemplateVerifier()
        is_pre_approved = verifier.is_pre_approved(name, template_file)

        # Validate structure
        validation_errors = []

        # Check required fields
        required_fields = ["name", "description", "stewardship"]
        for field in required_fields:
            if field not in template_data:
                validation_errors.append(f"Missing required field: {field}")

        # Check stewardship structure
        if "stewardship" in template_data:
            stewardship = template_data["stewardship"]
            if "stewardship_tier" not in stewardship:
                validation_errors.append("Missing stewardship_tier in stewardship section")
            if "creator_intent_statement" not in stewardship:
                validation_errors.append("Missing creator_intent_statement in stewardship section")

        # Return validation result
        return {
            "name": name,
            "valid": len(validation_errors) == 0,
            "pre_approved": is_pre_approved,
            "stewardship_tier": template_data.get("stewardship", {}).get("stewardship_tier", 1),
            "errors": validation_errors,
            "warnings": [
                "Template requires WA review"
                if template_data.get("stewardship", {}).get("stewardship_tier", 1) >= 4
                else None
            ]
            if not is_pre_approved
            else [],
        }

    except yaml.YAMLError as e:
        return {
            "name": name,
            "valid": False,
            "errors": [f"YAML parsing error: {str(e)}"],
            "warnings": [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error validating template: {str(e)}")
