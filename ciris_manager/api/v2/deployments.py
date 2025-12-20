"""
Deployments namespace - CD integration and deployment orchestration.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel

from .models import Deployment
from ciris_manager.api.auth import get_current_user_dependency as get_current_user
from ciris_manager.manager_core import get_manager
from ciris_manager.deployment import get_deployment_orchestrator
from ciris_manager.models import UpdateNotification


router = APIRouter(prefix="/deployments", tags=["deployments"])


class WebhookPayload(BaseModel):
    """GitHub Actions webhook payload."""

    agent_image: Optional[str] = None
    gui_image: Optional[str] = None
    nginx_image: Optional[str] = None
    message: str
    strategy: str = "immediate"
    source: str = "github_actions"
    commit_sha: Optional[str] = None
    version: Optional[str] = None


class CreateDeploymentRequest(BaseModel):
    """Request to create a new deployment."""

    components: Dict[str, str]  # component -> version
    strategy: str = "immediate"
    message: Optional[str] = None


class TargetDeploymentRequest(BaseModel):
    """Request to deploy to specific agent(s)."""

    agent_id: str
    version: str
    message: Optional[str] = None
    dry_run: bool = False


@router.post("/webhook")
async def github_webhook(payload: WebhookPayload) -> Dict[str, Any]:
    """
    GitHub Actions webhook for CD integration.
    No auth required - webhook has its own validation.
    """
    orchestrator = get_deployment_orchestrator()

    # Create update notification
    notification = UpdateNotification(
        agent_image=payload.agent_image,
        gui_image=payload.gui_image,
        nginx_image=payload.nginx_image,
        message=payload.message,
        strategy=payload.strategy,
        source=payload.source,
        commit_sha=payload.commit_sha,
        version=payload.version,
        changelog=None,
        risk_level="low",
        metadata={},
    )

    # Process notification
    deployment_id = await orchestrator.process_update_notification(notification)

    return {"status": "received", "deployment_id": deployment_id, "strategy": payload.strategy}


@router.get("")
async def list_deployments(
    status: Optional[str] = None, limit: int = 50, _user: Dict[str, str] = Depends(get_current_user)
) -> List[Deployment]:
    """
    List all deployments.
    """
    orchestrator = get_deployment_orchestrator()

    deployments = []
    for dep_id, dep in orchestrator.deployments.items():
        deployment = Deployment(
            id=dep_id,
            status=dep.status,
            strategy=dep.strategy or "immediate",
            targets=[],  # Simplified
            versions={},  # Simplified
            created_at=datetime.fromisoformat(dep.staged_at)
            if dep.staged_at
            else datetime.utcnow(),
        )

        if not status or deployment.status == status:
            deployments.append(deployment)

    # Sort by created_at descending
    deployments.sort(key=lambda x: x.created_at, reverse=True)

    return deployments[:limit]


@router.post("")
async def create_deployment(
    request: CreateDeploymentRequest, _user: Dict[str, str] = Depends(get_current_user)
) -> Deployment:
    """
    Create a new deployment.
    """
    orchestrator = get_deployment_orchestrator()

    # Create notification from request
    notification = UpdateNotification(
        agent_image=request.components.get("agent"),
        gui_image=request.components.get("gui"),
        nginx_image=request.components.get("nginx"),
        message=request.message or "Manual deployment via v2 API",
        strategy=request.strategy,
        source="v2_api",
        commit_sha=None,
        version=None,
        changelog=None,
        risk_level="low",
        metadata={"created_by": _user.get("email", "unknown")},
    )

    # Process notification
    deployment_id = await orchestrator.process_update_notification(notification)

    return Deployment(
        id=deployment_id,
        status="staged",
        strategy=request.strategy,
        targets=list(request.components.keys()),
        versions=request.components,
        created_at=datetime.utcnow(),
    )


@router.get("/{deployment_id}")
async def get_deployment(
    deployment_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Deployment:
    """
    Get deployment details.
    """
    orchestrator = get_deployment_orchestrator()

    if deployment_id not in orchestrator.deployments:
        raise HTTPException(status_code=404, detail=f"Deployment {deployment_id} not found")

    dep = orchestrator.deployments[deployment_id]

    return Deployment(
        id=deployment_id,
        status=dep.status,
        strategy=dep.strategy or "immediate",  # Provide default if None
        targets=[],  # Simplified
        versions={},  # Simplified
        created_at=datetime.fromisoformat(dep.staged_at) if dep.staged_at else datetime.utcnow(),
        executed_at=datetime.fromisoformat(dep.updated_at)
        if dep.status == "executing" and dep.updated_at
        else None,
        completed_at=datetime.fromisoformat(dep.updated_at)
        if dep.status == "complete" and dep.updated_at
        else None,
    )


@router.delete("/{deployment_id}")
async def cancel_deployment(
    deployment_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Cancel a deployment.
    """
    orchestrator = get_deployment_orchestrator()

    await orchestrator.cancel_deployment(deployment_id)

    return {"status": "cancelled", "deployment_id": deployment_id}


@router.post("/{deployment_id}/execute")
async def execute_deployment(
    deployment_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Execute a staged deployment.
    """
    orchestrator = get_deployment_orchestrator()

    if deployment_id not in orchestrator.deployments:
        raise HTTPException(status_code=404, detail=f"Deployment {deployment_id} not found")

    await orchestrator.launch_deployment(deployment_id)

    return {
        "status": "executing",
        "deployment_id": deployment_id,
        "message": "Deployment execution started",
    }


@router.post("/{deployment_id}/pause")
async def pause_deployment(
    deployment_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Pause a deployment.
    """
    orchestrator = get_deployment_orchestrator()

    await orchestrator.pause_deployment(deployment_id)

    return {"status": "paused", "deployment_id": deployment_id}


@router.post("/{deployment_id}/rollback")
async def rollback_deployment(
    deployment_id: str,
    reason: Optional[str] = None,
    _user: Dict[str, str] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Rollback a deployment.
    """
    orchestrator = get_deployment_orchestrator()

    await orchestrator.start_rollback(
        deployment_id=deployment_id,
        target_version="n_minus_1",  # Rollback to previous
        rollback_targets={"agent": ["all"], "gui": True, "nginx": False},
        reason=reason or "Manual rollback via v2 API",
    )

    return {
        "status": "rollback_initiated",
        "deployment_id": deployment_id,
        "rollback_deployment_id": f"rollback-{deployment_id}",
        "message": "Rollback initiated",
    }


@router.post("/target")
async def deploy_to_target(
    request: TargetDeploymentRequest, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Deploy to specific agent(s).
    Replaces old /updates/deploy-single.
    """
    if request.dry_run:
        return {
            "status": "dry_run",
            "agent_id": request.agent_id,
            "version": request.version,
            "message": "Dry run - no changes made",
        }

    orchestrator = get_deployment_orchestrator()

    # Create targeted notification
    notification = UpdateNotification(
        agent_image=request.version,
        gui_image=None,
        nginx_image=None,
        message=request.message or f"Targeted deployment to {request.agent_id}",
        strategy="immediate",
        source="v2_api_target",
        commit_sha=None,
        version=None,
        changelog=None,
        risk_level="low",
        metadata={"target_agent": request.agent_id, "created_by": _user.get("email", "unknown")},
    )

    # Get agent info
    manager = get_manager()
    agent = manager.agent_registry.get_agent(request.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {request.agent_id} not found")

    # Create agent info object with all required fields
    from ciris_manager.models import AgentInfo

    # Determine server_id and deployment_type
    server_id = agent.server_id if hasattr(agent, "server_id") else "main"
    deployment_type = "FULL" if server_id == "main" else "API_ONLY"

    agent_info = AgentInfo(
        agent_id=request.agent_id,
        agent_name=agent.name,
        container_name=f"ciris-agent-{request.agent_id}",
        status="running",
        template=agent.template if hasattr(agent, "template") else "unknown",
        deployment=agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")
        if hasattr(agent, "metadata")
        else "CIRIS_DISCORD_PILOT",
        server_id=server_id,
        deployment_type=deployment_type,
        # Optional fields with defaults
        api_port=agent.port if hasattr(agent, "port") else None,
        image=request.version,
        oauth_status=None,
        service_token=agent.metadata.get("service_token") if hasattr(agent, "metadata") else None,
        version=None,
        codename=None,
        code_hash=None,
        cognitive_state=None,
        mock_llm=None,
        discord_enabled=None,
        created_at=None,
        health="unknown",
        api_endpoint=None,
        update_available=False,
    )

    # Start single agent deployment
    deployment_status = await orchestrator.start_single_agent_deployment(notification, agent_info)

    return {
        "status": "initiated",
        "deployment_id": deployment_status.deployment_id,
        "agent_id": request.agent_id,
        "version": request.version,
        "message": f"Deployment to {request.agent_id} initiated",
    }
