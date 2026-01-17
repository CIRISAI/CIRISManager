"""
Deployment routes - update orchestration, canary deployment, version management.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ciris_manager.models import DeploymentStatus, UpdateNotification

from .dependencies import (
    get_manager,
    get_auth_dependency,
    get_deployment_orchestrator,
    deployment_auth,
    resolve_agent,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deployment"])

# Get auth dependency based on mode
auth_dependency = get_auth_dependency()


# ==========================================================================
# CD ORCHESTRATION ENDPOINTS
# ==========================================================================


@router.post("/updates/notify")
async def notify_update(
    notification: UpdateNotification,
    manager: Any = Depends(get_manager),
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = Depends(deployment_auth),
) -> Dict[str, Any]:
    """
    Receive update notification from CD pipeline.

    This is the single API call from GitHub Actions to trigger deployment.
    CIRISManager evaluates and stages if needed (Wisdom-Based Deferral).
    """
    try:
        # Validate repo authorization for the provided images
        source_repo = _user.get("source_repo", "legacy")

        # Enforce repo-specific image restrictions
        if source_repo == "agent":
            # Agent repo can only update agent images
            if notification.gui_image or notification.nginx_image:
                raise HTTPException(
                    status_code=403, detail="Agent repository can only update agent images"
                )
            if not notification.agent_image:
                raise HTTPException(
                    status_code=400, detail="Agent repository must provide agent_image"
                )
        elif source_repo == "gui":
            # GUI repo can only update GUI images
            if notification.agent_image or notification.nginx_image:
                raise HTTPException(
                    status_code=403, detail="GUI repository can only update GUI images"
                )
            if not notification.gui_image:
                raise HTTPException(status_code=400, detail="GUI repository must provide gui_image")
        # Legacy token can update anything (backwards compatibility)

        # Get current agents with runtime status
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        # Evaluate and potentially stage deployment
        deployment_id = await deployment_orchestrator.evaluate_and_stage(notification, agents)

        # Check if deployment was staged or started immediately
        if deployment_id in deployment_orchestrator.pending_deployments:
            staged_status = deployment_orchestrator.pending_deployments[deployment_id]
            logger.info(f"Staged deployment {deployment_id} for human review")

            # Determine deployment type for clearer messaging
            deployment_type = "Update"
            if "GUI" in staged_status.message:
                deployment_type = "GUI Update"
            elif staged_status.agents_total > 0:
                deployment_type = "Agent Update"

            return {
                "deployment_id": deployment_id,
                "status": "staged",
                "message": f"{deployment_type} staged for human review (Wisdom-Based Deferral)",
                "agents_affected": staged_status.agents_total,
                "deployment_type": deployment_type.lower().replace(" ", "_"),
            }
        else:
            deploy_status: Optional[DeploymentStatus] = deployment_orchestrator.deployments.get(
                deployment_id
            )
            if deploy_status:
                logger.info(f"Auto-started low-risk deployment {deployment_id}")
                return {
                    "deployment_id": deployment_id,
                    "status": deploy_status.status,
                    "message": deploy_status.message,
                    "agents_affected": deploy_status.agents_total,
                }
            else:
                # No-op deployment (no updates needed)
                return {
                    "deployment_id": deployment_id,
                    "status": "completed",
                    "message": "No updates needed",
                    "agents_affected": 0,
                }

    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process update notification: {e}")
        raise HTTPException(status_code=500, detail="Failed to process update")


@router.get("/updates/events/{deployment_id}")
async def get_deployment_events(
    deployment_id: str,
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Get timeline of events for a specific deployment."""
    deployment = deployment_orchestrator.deployments.get(
        deployment_id
    ) or deployment_orchestrator.pending_deployments.get(deployment_id)

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    return {
        "deployment_id": deployment_id,
        "status": deployment.status,
        "events": deployment.events if hasattr(deployment, "events") else [],
        "started_at": deployment.started_at,
        "completed_at": deployment.completed_at,
    }


@router.get("/updates/events/{deployment_id}/stream")
async def stream_deployment_events(
    deployment_id: str,
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> StreamingResponse:
    """
    Stream deployment events via Server-Sent Events (SSE).

    Streams real-time events as they occur during deployment.
    Automatically closes when deployment completes or fails.
    """

    async def event_generator():
        """Generate SSE events for deployment status updates."""
        last_event_count = 0
        terminal_statuses = {"completed", "failed", "cancelled", "rejected", "rolled_back"}

        while True:
            # Get current deployment state
            deployment = deployment_orchestrator.deployments.get(
                deployment_id
            ) or deployment_orchestrator.pending_deployments.get(deployment_id)

            if not deployment:
                # Deployment not found - send error and close
                error_event = {
                    "type": "error",
                    "message": f"Deployment {deployment_id} not found",
                    "timestamp": asyncio.get_event_loop().time(),
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                return

            # Get current events
            events = deployment.events if hasattr(deployment, "events") else []
            current_event_count = len(events)

            # Send any new events
            if current_event_count > last_event_count:
                for event in events[last_event_count:]:
                    yield f"data: {json.dumps(event)}\n\n"
                last_event_count = current_event_count

            # Send periodic status update
            status_event = {
                "type": "status",
                "deployment_id": deployment_id,
                "status": deployment.status,
                "agents_updated": getattr(deployment, "agents_updated", 0),
                "agents_failed": getattr(deployment, "agents_failed", 0),
                "agents_total": getattr(deployment, "agents_total", 0),
                "canary_phase": getattr(deployment, "canary_phase", None),
            }
            yield f"data: {json.dumps(status_event)}\n\n"

            # Check if deployment reached terminal state
            if deployment.status in terminal_statuses:
                close_event = {
                    "type": "close",
                    "status": deployment.status,
                    "message": f"Deployment {deployment.status}",
                }
                yield f"data: {json.dumps(close_event)}\n\n"
                return

            # Wait before next poll
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/updates/status", response_model=Optional[DeploymentStatus])
async def get_deployment_status(
    deployment_id: Optional[str] = None,
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Optional[DeploymentStatus]:
    """
    Get deployment status.

    If deployment_id is not provided, returns current active deployment.
    """
    if deployment_id:
        return await deployment_orchestrator.get_deployment_status(deployment_id)
    else:
        return await deployment_orchestrator.get_current_deployment()


@router.get("/updates/pending/all")
async def get_all_pending_deployments(
    manager: Any = Depends(get_manager),
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get all pending deployments (supports multiple staged deployments).

    Returns all staged deployments and information about what 'latest' points to.
    """
    # Get all pending deployments
    all_pending = []
    for dep_id, deployment in deployment_orchestrator.pending_deployments.items():
        dep_info = {
            "deployment_id": dep_id,
            "staged_at": deployment.staged_at,
            "affected_agents": deployment.agents_total,
            "status": deployment.status,
        }
        if deployment.notification:
            dep_info.update(
                {
                    "agent_image": deployment.notification.agent_image,
                    "gui_image": deployment.notification.gui_image,
                    "strategy": deployment.notification.strategy,
                    "message": deployment.notification.message,
                    "version": deployment.notification.version,
                    "commit_sha": deployment.notification.commit_sha,
                }
            )
        all_pending.append(dep_info)

    # Sort by staged_at (newest first)
    all_pending.sort(key=lambda x: str(x.get("staged_at", "")), reverse=True)

    # Get current 'latest' tag info
    latest_info = {}
    try:
        # Try to get digest of current latest tag locally
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "images",
            "ghcr.io/cirisai/ciris-agent:latest",
            "--format",
            "{{.ID}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout = b""

        if proc.returncode == 0 and stdout.strip():
            latest_info["local_image_id"] = stdout.decode().strip()[:12]  # Short ID

        # Try to get what version is currently running
        agents = (
            await deployment_orchestrator.manager.get_agent_statuses()
            if deployment_orchestrator.manager
            else []
        )
        if agents:
            # Get version from first agent (they should all be the same in production)
            for agent in agents:
                if agent.get("is_running"):
                    latest_info["running_version"] = agent.get("current_version", "unknown")
                    break
    except Exception as e:
        logger.warning(f"Could not get latest tag info: {e}")

    return {
        "deployments": all_pending,
        "latest_tag": latest_info,
        "total_pending": len(all_pending),
    }


@router.get("/updates/pending")
async def get_pending_deployment(
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get pending deployment details if any.

    Returns staged deployment waiting for operator approval or failed deployment blocking new ones.
    """
    # First check for actual pending deployments
    pending = await deployment_orchestrator.get_pending_deployment()
    if pending:
        result = {
            "pending": True,
            "deployment_id": pending.deployment_id,
            "staged_at": pending.staged_at,
            "affected_agents": pending.agents_total,
        }
        if pending.notification:
            result.update(
                {
                    "agent_image": pending.notification.agent_image,
                    "gui_image": pending.notification.gui_image,
                    "strategy": pending.notification.strategy,
                    "message": pending.notification.message,
                    "version": pending.notification.version,
                    "commit_sha": pending.notification.commit_sha,
                }
            )
        return result

    # Check if there's a failed deployment blocking new ones
    current = await deployment_orchestrator.get_current_deployment()
    if current and current.status == "failed":
        result = {
            "pending": True,  # Still blocking, so return true
            "deployment_id": current.deployment_id,
            "status": "failed",
            "staged_at": current.started_at,
            "affected_agents": current.agents_total,
            "message": current.message or "Deployment failed",
        }
        if current.notification:
            result.update(
                {
                    "agent_image": current.notification.agent_image,
                    "gui_image": current.notification.gui_image,
                    "strategy": current.notification.strategy,
                    "version": current.notification.version,
                    "commit_sha": current.notification.commit_sha,
                }
            )
        return result

    return {"pending": False}


@router.get("/updates/preview/{deployment_id}")
async def preview_deployment(
    deployment_id: str,
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get a preview of what a deployment will do.
    Shows which agents need updates and which are already current.
    Designed for scale - efficiently checks all agents.
    """
    preview = await deployment_orchestrator.get_deployment_preview(deployment_id)
    return preview


@router.get("/updates/shutdown-reasons/{deployment_id}")
async def get_shutdown_reasons(
    deployment_id: str,
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Get the shutdown reasons that will be sent to each agent."""
    return await deployment_orchestrator.get_shutdown_reasons_preview(deployment_id)


@router.post("/updates/launch")
async def launch_deployment(
    request: Dict[str, str],
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, str]:
    """
    Launch a staged deployment.

    Requires operator approval to start canary rollout.
    """
    deployment_id = request.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id required")

    success = await deployment_orchestrator.launch_staged_deployment(deployment_id)
    if success:
        return {"status": "launched", "deployment_id": deployment_id}
    else:
        raise HTTPException(status_code=404, detail="Deployment not found or not pending")


@router.post("/updates/cancel")
async def cancel_deployment(
    request: Dict[str, str],
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, str]:
    """
    Cancel a stuck deployment.

    Clears the deployment lock to allow starting a new deployment.
    """
    deployment_id = request.get("deployment_id")
    reason = request.get("reason", "Cancelled due to stuck state")

    if not deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id required")

    success = await deployment_orchestrator.cancel_stuck_deployment(deployment_id, reason)
    if success:
        return {"status": "cancelled", "deployment_id": deployment_id}
    else:
        raise HTTPException(status_code=404, detail="Deployment not found")


@router.post("/updates/reject")
async def reject_deployment(
    request: Dict[str, str],
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, str]:
    """
    Reject a staged deployment.

    Cancels the deployment and logs the rejection reason.
    """
    deployment_id = request.get("deployment_id")
    reason = request.get("reason", "Rejected by operator")

    if not deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id required")

    success = await deployment_orchestrator.reject_staged_deployment(deployment_id, reason)
    if success:
        return {"status": "rejected", "deployment_id": deployment_id}
    else:
        raise HTTPException(status_code=404, detail="Deployment not found or not pending")


@router.post("/updates/retry")
async def retry_deployment(
    request: Dict[str, str],
    manager: Any = Depends(get_manager),
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Retry a failed/cancelled deployment.

    Creates a new deployment using the original notification from the failed deployment.
    """
    deployment_id = request.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id required")

    # Find the original deployment (check both active and pending)
    original = deployment_orchestrator.deployments.get(
        deployment_id
    ) or deployment_orchestrator.pending_deployments.get(deployment_id)

    if not original:
        raise HTTPException(status_code=404, detail="Original deployment not found")

    if not original.notification:
        raise HTTPException(
            status_code=400,
            detail="Original deployment has no notification data to retry",
        )

    # Check if deployment can be retried (must be in terminal failed state)
    retryable_statuses = {"failed", "cancelled", "rejected", "rolled_back"}
    if original.status not in retryable_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry deployment in '{original.status}' state. "
            f"Only {retryable_statuses} deployments can be retried.",
        )

    # Get current agents
    from ciris_manager.docker_discovery import DockerAgentDiscovery

    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()

    # Stage a new deployment with the same notification
    new_deployment_id = await deployment_orchestrator.stage_deployment(
        original.notification, agents
    )

    logger.info(f"Retrying deployment {deployment_id} as new deployment {new_deployment_id}")

    return {
        "status": "staged",
        "original_deployment_id": deployment_id,
        "new_deployment_id": new_deployment_id,
        "message": "New deployment staged from original. Use /updates/launch to start.",
    }


@router.post("/updates/pause")
async def pause_deployment(
    request: Dict[str, str],
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, str]:
    """
    Pause an active deployment.

    Stops further agent updates but keeps deployment active.
    """
    deployment_id = request.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id required")

    success = await deployment_orchestrator.pause_deployment(deployment_id)
    if success:
        return {"status": "paused", "deployment_id": deployment_id}
    else:
        raise HTTPException(status_code=404, detail="Deployment not found or not active")


@router.post("/updates/rollback")
async def rollback_deployment(
    request: Dict[str, Any],
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, str]:
    """
    Rollback a deployment.

    Reverts updated agents to specified or previous version.

    Request body:
    {
        "deployment_id": "deploy-123",
        "target_version": "n-1" | "n-2" | "specific-version",  # Optional, defaults to n-1
        "target_versions": {  # Optional, for granular control
            "agents": {"agent1": "n-1", "agent2": "n-2"},
            "gui": "n-1",
            "nginx": "n-2"
        }
    }
    """
    deployment_id = request.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id required")

    target_version = request.get("target_version", "n-1")
    target_versions = request.get("target_versions", None)

    success = await deployment_orchestrator.rollback_deployment(
        deployment_id, target_version=target_version, target_versions=target_versions
    )
    if success:
        return {
            "status": "rolling_back",
            "deployment_id": deployment_id,
            "target_version": target_version,
        }
    else:
        raise HTTPException(status_code=404, detail="Deployment not found")


@router.get("/updates/current-images")
async def get_current_images(
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Get current running container images."""
    images = await deployment_orchestrator.get_current_images()
    return images


@router.get("/updates/history")
async def get_deployment_history(
    limit: int = 10,
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Get deployment history."""
    history = await deployment_orchestrator.get_deployment_history(limit)
    return {"deployments": history}


@router.get("/updates/rollback-options")
async def get_rollback_options(
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get available rollback options for all container types.
    Returns n-1 and n-2 versions for agents, GUI, and nginx containers.
    Uses DeploymentOrchestrator as single source of truth.
    """
    # Get rollback options from deployment history
    # For now, return empty structure - TODO: implement rollback from deployment history
    result = {
        "agent": {
            "current": None,  # TODO: Get from deployment orchestrator
            "n_minus_1": None,  # TODO: Get from deployment history
            "n_minus_2": None,  # TODO: Get from deployment history
        },
        "gui": {
            "current": None,  # GUI tracked separately
            "n_minus_1": None,
            "n_minus_2": None,
        },
        "nginx": {
            "current": None,  # Nginx rarely changes
            "n_minus_1": None,
            "n_minus_2": None,
        },
        # Legacy support
        "agents": {},  # Deprecated - use "agent" instead
    }

    return result


@router.get("/updates/rollback/{deployment_id}/versions")
async def get_rollback_versions(
    deployment_id: str,
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get available rollback versions for a deployment.

    Returns version history for all components that can be rolled back.
    """
    versions = await deployment_orchestrator.get_rollback_versions(deployment_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Deployment not found or no versions available")
    return versions


@router.get("/updates/rollback-proposals")
async def get_rollback_proposals(
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Get active rollback proposals requiring operator decision."""
    proposals = getattr(deployment_orchestrator, "rollback_proposals", {})

    # Return active proposals
    active_proposals = []
    for dep_id, proposal in proposals.items():
        if dep_id in deployment_orchestrator.deployments:
            deployment = deployment_orchestrator.deployments[dep_id]
            if deployment.status == "rollback_proposed":
                active_proposals.append(proposal)

    return {"proposals": active_proposals, "count": len(active_proposals)}


@router.post("/updates/approve-rollback")
async def approve_rollback(
    request: Dict[str, Any],
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Approve a proposed rollback."""
    deployment_id = request.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id required")

    proposals = getattr(deployment_orchestrator, "rollback_proposals", {})
    if deployment_id not in proposals:
        raise HTTPException(status_code=404, detail="Rollback proposal not found")

    # Execute the rollback
    success = await deployment_orchestrator.rollback_deployment(deployment_id)

    if success:
        # Remove proposal
        del proposals[deployment_id]
        return {"status": "rollback_started", "deployment_id": deployment_id}
    else:
        raise HTTPException(status_code=404, detail="Deployment not found")


@router.post("/updates/deploy-single")
async def deploy_single_agent(
    request: Dict[str, Any],
    manager: Any = Depends(get_manager),
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Deploy a specific version to a single agent for testing.

    This endpoint allows targeted deployment to individual agents,
    respecting the consensual deployment system.

    Request body:
    {
        "agent_id": "datum",
        "agent_image": "ghcr.io/cirisai/ciris-agent:v1.4.5",
        "message": "Testing new feature X",
        "strategy": "immediate",  # immediate recommended for single agent
        "metadata": {...}
    }
    """
    agent_id = request.get("agent_id")
    agent_image = request.get("agent_image")
    message = request.get("message", "Single agent test deployment")
    strategy = request.get("strategy", "immediate")
    metadata = request.get("metadata", {})
    occurrence_id = request.get("occurrence_id")
    server_id = request.get("server_id")

    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    if not agent_image:
        raise HTTPException(status_code=400, detail="agent_image is required")

    # Validate the agent exists using composite key resolution
    resolve_agent(manager, agent_id, occurrence_id=occurrence_id, server_id=server_id)

    # Get the discovered agent info
    from ciris_manager.docker_discovery import DockerAgentDiscovery

    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()

    # Match by agent_id, occurrence_id, and server_id
    target_agent = next(
        (
            a
            for a in agents
            if a.agent_id == agent_id
            and (occurrence_id is None or a.occurrence_id == occurrence_id)
            and (server_id is None or a.server_id == server_id)
        ),
        None,
    )
    if not target_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Create a targeted update notification
    notification = UpdateNotification(
        agent_image=agent_image,
        gui_image=None,
        nginx_image=None,
        message=message,
        strategy=strategy,
        source="manager_ui",
        commit_sha=None,
        version=None,
        changelog=None,
        risk_level="low",
        metadata={
            **metadata,
            "single_agent_deployment": True,
            "target_agent": agent_id,
            "initiated_by": _user.get("email", "unknown"),
        },
    )

    # Start deployment for just this agent
    try:
        deployment_status = await deployment_orchestrator.start_single_agent_deployment(
            notification, target_agent
        )
    except ValueError as e:
        # Deployment already in progress
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        f"Single agent deployment {deployment_status.deployment_id} started for {agent_id} "
        f"by {_user.get('email', 'unknown')}"
    )

    return {
        "deployment_id": deployment_status.deployment_id,
        "agent_id": agent_id,
        "status": deployment_status.status,
        "message": deployment_status.message,
        "image": agent_image,
    }


@router.get("/updates/latest/changelog")
async def get_latest_changelog() -> Dict[str, Any]:
    """
    Get recent commits for changelog information.

    Returns formatted changelog entries that can be included in update notifications.
    This endpoint returns mock data for now but could be enhanced to fetch from
    actual repositories or CI/CD systems.
    """
    # For now, return structured changelog data
    # In production, this could:
    # 1. Fetch from GitHub API using the commit SHA
    # 2. Parse from a CHANGELOG.md file
    # 3. Extract from CI/CD metadata

    return {
        "latest": {
            "version": "latest",
            "date": "2025-08-01",
            "changes": [
                {
                    "type": "fix",
                    "description": "Memory leak in telemetry service",
                    "risk": "low",
                },
                {
                    "type": "feat",
                    "description": "Enhanced update notifications with context",
                    "risk": "low",
                },
                {
                    "type": "security",
                    "description": "Removed hardcoded deployment token",
                    "risk": "critical",
                },
            ],
        },
        "summary": "3 changes: 1 fix, 1 feature, 1 security update",
        "recommended_action": "update",
        "breaking_changes": False,
    }


# ==========================================================================
# CANARY DEPLOYMENT GROUP MANAGEMENT
# ==========================================================================


@router.get("/canary/groups")
async def get_canary_groups(
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """Get agents organized by canary deployment groups."""
    from ciris_manager.docker_discovery import DockerAgentDiscovery

    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()

    # Get canary group assignments from registry
    groups: Dict[str, List[Dict[str, Any]]] = {
        "explorer": [],
        "early_adopter": [],
        "general": [],
        "unassigned": [],
    }

    for agent in agents:
        registry_agent = manager.agent_registry.get_agent(agent.agent_id)
        metadata = (
            registry_agent.metadata
            if registry_agent and hasattr(registry_agent, "metadata")
            else {}
        )
        group = metadata.get("canary_group", "unassigned")

        agent_data = {
            "agent_id": agent.agent_id,
            "agent_name": agent.agent_name,
            "status": agent.status,
            "version": agent.version or "unknown",
            "code_hash": agent.code_hash or "unknown",
            "last_updated": metadata.get("last_updated", "never"),
        }

        if group not in groups:
            group = "unassigned"
        groups[group].append(agent_data)

    # Calculate group sizes
    total = len(agents)
    group_stats = {
        "explorer": {
            "count": len(groups["explorer"]),
            "target_percentage": 10,
            "actual_percentage": round(len(groups["explorer"]) / total * 100) if total > 0 else 0,
        },
        "early_adopter": {
            "count": len(groups["early_adopter"]),
            "target_percentage": 20,
            "actual_percentage": round(len(groups["early_adopter"]) / total * 100)
            if total > 0
            else 0,
        },
        "general": {
            "count": len(groups["general"]),
            "target_percentage": 70,
            "actual_percentage": round(len(groups["general"]) / total * 100) if total > 0 else 0,
        },
        "unassigned": {
            "count": len(groups["unassigned"]),
            "target_percentage": 0,
            "actual_percentage": round(len(groups["unassigned"]) / total * 100) if total > 0 else 0,
        },
    }

    return {"groups": groups, "stats": group_stats, "total_agents": total}


@router.put("/canary/agent/{agent_id}/group")
async def update_agent_canary_group(
    agent_id: str,
    request: Dict[str, str],
    manager: Any = Depends(get_manager),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, str]:
    """Update an agent's canary deployment group."""
    group = request.get("group")
    valid_groups = ["explorer", "early_adopter", "general", "unassigned"]
    if group not in valid_groups:
        raise HTTPException(
            status_code=400, detail=f"Invalid group. Must be one of: {', '.join(valid_groups)}"
        )

    # Set to None if unassigned
    group_value = None if group == "unassigned" else group

    if manager.agent_registry.set_canary_group(agent_id, group_value):
        return {"status": "success", "agent_id": agent_id, "group": group}
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


# ==========================================================================
# VERSION ADOPTION TRACKING
# ==========================================================================


@router.get("/versions/adoption")
async def get_version_adoption(
    manager: Any = Depends(get_manager),
    deployment_orchestrator: Any = Depends(get_deployment_orchestrator),
    _user: Dict[str, str] = auth_dependency,
) -> Dict[str, Any]:
    """
    Get version adoption data for all agents.

    Returns information about:
    - Current latest versions
    - Agent adoption status
    - Deployment history
    """
    # Get all agents with their metadata
    from ciris_manager.docker_discovery import DockerAgentDiscovery

    discovery = DockerAgentDiscovery(
        manager.agent_registry, docker_client_manager=manager.docker_client
    )
    agents = discovery.discover_agents()

    # Get agent metadata from registry
    agent_versions = []
    for agent in agents:
        registry_agent = manager.agent_registry.get_agent(agent.agent_id)
        if registry_agent:
            metadata = registry_agent.metadata if hasattr(registry_agent, "metadata") else {}
            current_images = metadata.get("current_images", {})

            agent_versions.append(
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.agent_name,
                    "status": agent.status,
                    "version": agent.version or "unknown",
                    "code_hash": agent.code_hash or "unknown",
                    "codename": agent.codename or "unknown",
                    "current_agent_image": current_images.get("agent", "unknown"),
                    "current_gui_image": current_images.get("gui", "unknown"),
                    "last_updated": metadata.get("last_updated", "never"),
                }
            )
        else:
            agent_versions.append(
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.agent_name,
                    "status": agent.status,
                    "version": agent.version or "unknown",
                    "code_hash": agent.code_hash or "unknown",
                    "codename": agent.codename or "unknown",
                    "current_agent_image": "unknown",
                    "current_gui_image": "unknown",
                    "last_updated": "never",
                }
            )

    # Get latest versions from environment or config
    latest_agent_image = os.getenv("CIRIS_LATEST_AGENT_IMAGE", "ghcr.io/cirisai/ciris-agent:latest")
    latest_gui_image = os.getenv("CIRIS_LATEST_GUI_IMAGE", "ghcr.io/cirisai/ciris-gui:latest")

    # Get current deployment if any
    current_deployment = await deployment_orchestrator.get_current_deployment()

    # Get recent deployments
    recent_deployments = []
    for dep_id, status in deployment_orchestrator.deployments.items():
        if status.completed_at:  # Only show completed deployments
            recent_deployments.append(
                {
                    "deployment_id": dep_id,
                    "started_at": status.started_at,
                    "completed_at": status.completed_at,
                    "agents_updated": status.agents_updated,
                    "agents_total": status.agents_total,
                    "message": status.message,
                    "status": status.status,
                }
            )

    # Sort by completed_at descending
    recent_deployments.sort(key=lambda x: str(x["completed_at"] or ""), reverse=True)
    recent_deployments = recent_deployments[:10]  # Last 10 deployments

    return {
        "latest_versions": {
            "agent_image": latest_agent_image,
            "gui_image": latest_gui_image,
        },
        "agent_versions": agent_versions,
        "current_deployment": current_deployment.model_dump() if current_deployment else None,
        "recent_deployments": recent_deployments,
    }
