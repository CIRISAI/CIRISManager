"""
Deployment state persistence.

Handles loading and saving deployment state to disk.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles  # type: ignore

from ciris_manager.models import DeploymentStatus

logger = logging.getLogger(__name__)


class DeploymentState:
    """
    Manages persistent storage of deployment state.

    Handles serialization/deserialization of deployments to JSON,
    atomic file writes, and recovery detection.
    """

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        """
        Initialize deployment state manager.

        Args:
            state_dir: Directory for state files. Defaults to /var/lib/ciris-manager
                      with fallback to temp directory.
        """
        if state_dir:
            self.state_dir = state_dir
        else:
            self.state_dir = Path("/var/lib/ciris-manager")
            try:
                self.state_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                # Fall back to temp directory for testing
                import tempfile

                self.state_dir = Path(tempfile.gettempdir()) / "ciris-manager"
                self.state_dir.mkdir(parents=True, exist_ok=True)

        self.deployment_state_file = self.state_dir / "deployment_state.json"

    def load(
        self,
        deployments: Dict[str, DeploymentStatus],
        pending_deployments: Dict[str, DeploymentStatus],
    ) -> tuple[Optional[str], Optional[DeploymentStatus]]:
        """
        Load deployment state from persistent storage.

        Args:
            deployments: Dict to populate with loaded deployments
            pending_deployments: Dict to populate with pending deployments

        Returns:
            Tuple of (current_deployment_id, pending_recovery_deployment)
        """
        current_deployment: Optional[str] = None
        pending_recovery: Optional[DeploymentStatus] = None

        if not self.deployment_state_file.exists():
            return current_deployment, pending_recovery

        try:
            with open(self.deployment_state_file, "r") as f:
                state = json.load(f)

            # Restore deployments
            for deployment_id, deployment_data in state.get("deployments", {}).items():
                deployments[deployment_id] = DeploymentStatus(**deployment_data)

            # Restore pending deployments
            for deployment_id, deployment_data in state.get("pending_deployments", {}).items():
                pending_deployments[deployment_id] = DeploymentStatus(**deployment_data)

            # Restore current deployment
            current_deployment = state.get("current_deployment")

            logger.info(
                f"Loaded deployment state with {len(deployments)} deployments "
                f"and {len(pending_deployments)} pending deployments"
            )

            # Check for in-progress deployments that need recovery
            if current_deployment and current_deployment in deployments:
                deployment = deployments[current_deployment]
                if deployment.status == "in_progress":
                    if deployment.agents_pending_restart or deployment.agents_in_progress:
                        logger.warning(
                            f"Found interrupted deployment {current_deployment} after restart. "
                            f"Agents pending restart: {deployment.agents_pending_restart}, "
                            f"Agents in progress: {list(deployment.agents_in_progress.keys())}"
                        )
                        pending_recovery = deployment
                        logger.info(
                            "Deployment recovery deferred - will run on first async operation"
                        )
                    else:
                        logger.warning(
                            f"Found in-progress deployment {current_deployment} after restart. "
                            "Marking as failed due to manager restart during deployment."
                        )
                        deployment.status = "failed"
                        deployment.completed_at = datetime.now(timezone.utc).isoformat()
                        deployment.message = "Deployment interrupted by manager restart"
                        current_deployment = None
                        self.save_sync(deployments, pending_deployments, current_deployment)

            # Scan for stale in-progress deployments
            stale_threshold = datetime.now(timezone.utc).timestamp() - (10 * 60)  # 10 minutes
            for deployment_id, deployment in list(deployments.items()):
                if deployment.status == "in_progress" and deployment.started_at:
                    started_timestamp = datetime.fromisoformat(
                        deployment.started_at.replace("Z", "+00:00")
                    ).timestamp()
                    if started_timestamp < stale_threshold:
                        logger.warning(
                            f"Found stale in-progress deployment {deployment_id} after restart. "
                            f"Started at {deployment.started_at}, marking as failed."
                        )
                        deployment.status = "failed"
                        deployment.completed_at = datetime.now(timezone.utc).isoformat()
                        deployment.message = "Deployment marked as failed - stale after manager restart"
                        self.save_sync(deployments, pending_deployments, current_deployment)

        except Exception as e:
            logger.warning(f"Failed to load deployment state: {e}")

        return current_deployment, pending_recovery

    def save_sync(
        self,
        deployments: Dict[str, DeploymentStatus],
        pending_deployments: Dict[str, DeploymentStatus],
        current_deployment: Optional[str],
    ) -> None:
        """
        Save deployment state synchronously.

        Args:
            deployments: All deployments to save
            pending_deployments: Pending deployments to save
            current_deployment: Current deployment ID or None
        """
        try:
            state = {
                "deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in deployments.items()
                },
                "pending_deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in pending_deployments.items()
                },
                "current_deployment": current_deployment,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            # Write to temp file first, then move atomically
            temp_file = self.deployment_state_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(state, f, indent=2)

            # Atomic rename
            temp_file.replace(self.deployment_state_file)
            logger.debug(f"Saved deployment state with {len(deployments)} deployments")
        except Exception as e:
            logger.error(f"Failed to save deployment state: {e}")

    async def save_async(
        self,
        deployments: Dict[str, DeploymentStatus],
        pending_deployments: Dict[str, DeploymentStatus],
        current_deployment: Optional[str],
    ) -> None:
        """
        Save deployment state asynchronously.

        Args:
            deployments: All deployments to save
            pending_deployments: Pending deployments to save
            current_deployment: Current deployment ID or None
        """
        try:
            state = {
                "deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in deployments.items()
                },
                "pending_deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in pending_deployments.items()
                },
                "current_deployment": current_deployment,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            # Write to temp file first, then move atomically
            temp_file = self.deployment_state_file.with_suffix(".tmp")
            async with aiofiles.open(temp_file, "w") as f:
                await f.write(json.dumps(state, indent=2))

            # Atomic rename (still sync as it's a filesystem operation)
            temp_file.replace(self.deployment_state_file)
            logger.debug(f"Saved deployment state with {len(deployments)} deployments")
        except Exception as e:
            logger.error(f"Failed to save deployment state: {e}")


def add_event(
    deployment: Optional[DeploymentStatus],
    event_type: str,
    message: str,
    details: Optional[dict] = None,
) -> None:
    """
    Add an event to a deployment's timeline.

    Args:
        deployment: The deployment to add event to (can be None)
        event_type: Type of event (e.g., "started", "completed", "failed")
        message: Human-readable event message
        details: Optional additional details dict
    """
    if not deployment:
        return

    event: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "message": message,
    }
    if details:
        event["details"] = details
    deployment.events.append(event)
