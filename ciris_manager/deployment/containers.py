"""
Container and image operations for deployments.

Handles Docker image pulling, digest retrieval, and container lifecycle operations.

NOTE: Container start/stop/restart operations are in DockerAgentDiscovery.
This module focuses on deployment-specific operations like image pulling
and version tracking. Use DockerAgentDiscovery for agent lifecycle ops.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles  # type: ignore

from ciris_manager.models import UpdateNotification

logger = logging.getLogger(__name__)


class ContainerOperations:
    """
    Handles Docker container and image operations.

    Provides methods for pulling images, getting digests,
    and managing container lifecycle during deployments.
    """

    def __init__(self, manager: Optional[Any] = None) -> None:
        """
        Initialize container operations.

        Args:
            manager: Reference to CIRISManager for Docker client access
        """
        self.manager = manager

    async def pull_images(self, notification: UpdateNotification) -> Dict[str, Any]:
        """
        Pull Docker images specified in the notification with retry logic.

        Implements retry logic for authentication failures (401 errors):
        - 10 second sleep between retries
        - Maximum 2 retries for auth failures
        - Exponential backoff for other transient errors

        Args:
            notification: Update notification with image details

        Returns:
            Dictionary with success status and any error messages
        """
        results: Dict[str, Any] = {"success": True, "agent_image": None, "gui_image": None}

        try:
            # Pull agent image if specified
            if notification.agent_image:
                agent_result = await self.pull_single_image_with_retry(
                    notification.agent_image, "agent"
                )
                if not agent_result["success"]:
                    results["success"] = False
                    results["error"] = agent_result["error"]
                    return results
                results["agent_image"] = notification.agent_image

            # Pull GUI image if specified
            if notification.gui_image:
                gui_result = await self.pull_single_image_with_retry(notification.gui_image, "GUI")
                if not gui_result["success"]:
                    results["success"] = False
                    results["error"] = gui_result["error"]
                    return results
                results["gui_image"] = notification.gui_image

        except Exception as e:
            logger.error(f"Exception during image pull: {e}")
            results["success"] = False
            results["error"] = str(e)

        return results

    async def pull_single_image_with_retry(self, image: str, image_type: str) -> Dict[str, Any]:
        """
        Pull a single Docker image with retry logic for authentication failures.

        Args:
            image: Docker image name
            image_type: Type of image (for logging) - "agent" or "GUI"

        Returns:
            Dictionary with success status and error message if any
        """
        # Normalize image name to lowercase for Docker
        normalized_image = image.lower()
        max_retries = 2
        retry_delay = 10  # 10 seconds as specified in requirements

        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.info(
                    f"Retrying {image_type} image pull (attempt {attempt + 1}/{max_retries + 1}): {normalized_image}"
                )

            logger.info(f"Pulling {image_type} image: {normalized_image}")

            try:
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "pull",
                    normalized_image,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    logger.info(f"Successfully pulled {image_type} image: {image}")
                    return {"success": True}

                # Parse error message
                error_msg = stderr.decode() if stderr else f"Failed to pull {image_type} image"

                # Check if this is an authentication error (401)
                is_auth_error = (
                    "401" in error_msg
                    or "unauthorized" in error_msg.lower()
                    or "authentication" in error_msg.lower()
                )

                if is_auth_error and attempt < max_retries:
                    logger.warning(
                        f"Authentication error pulling {image_type} image (attempt {attempt + 1}): {error_msg}"
                    )
                    logger.info(f"Waiting {retry_delay} seconds before retry...")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    # Final attempt or non-auth error
                    if is_auth_error:
                        logger.error(
                            f"Authentication failed after {max_retries + 1} attempts for {image_type} image: {error_msg}"
                        )
                    else:
                        logger.error(f"Failed to pull {image_type} image: {error_msg}")

                    return {
                        "success": False,
                        "error": f"{image_type} image pull failed: {error_msg}",
                    }

            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"Exception pulling {image_type} image (attempt {attempt + 1}): {e}"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Exception pulling {image_type} image after retries: {e}")
                    return {"success": False, "error": f"{image_type} image pull failed: {str(e)}"}

        # This should never be reached, but mypy requires it
        return {"success": False, "error": f"Unexpected error in {image_type} image pull"}

    async def get_local_image_digest(self, image_tag: str) -> Optional[str]:
        """
        Get the digest of a locally pulled Docker image.

        Args:
            image_tag: Docker image tag (e.g., ghcr.io/cirisai/ciris-agent:latest)

        Returns:
            Image digest or None if not found
        """
        try:
            # Use docker inspect to get image details
            result = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                image_tag,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.warning(f"Failed to inspect image {image_tag}: {stderr.decode()}")
                return None

            # Parse JSON output
            image_data = json.loads(stdout.decode())
            if image_data and len(image_data) > 0:
                # Get the RepoDigests field which contains the image digest
                repo_digests = image_data[0].get("RepoDigests", [])
                if repo_digests:
                    # Extract digest from format like "ghcr.io/cirisai/ciris-agent@sha256:abc123..."
                    for digest in repo_digests:
                        if "@sha256:" in digest:
                            return str(digest.split("@")[-1])  # Return just the sha256:... part

                # Fallback to Id if no RepoDigests
                image_id = image_data[0].get("Id", "")
                if image_id:
                    return str(image_id)

            return None

        except Exception as e:
            logger.error(f"Error getting local image digest for {image_tag}: {e}")
            return None

    async def get_container_image_digest(self, container_name: str) -> Optional[str]:
        """
        Get the digest of the image used by a running container.

        Args:
            container_name: Name of the container

        Returns:
            Image digest or None if not found
        """
        try:
            # Get container details
            result = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.warning(f"Failed to inspect container {container_name}: {stderr.decode()}")
                return None

            # Parse JSON output
            container_data = json.loads(stdout.decode())
            if container_data and len(container_data) > 0:
                # Get the image ID the container is using
                image_id = container_data[0].get("Image", "")
                if image_id:
                    # If it's already a digest, return it
                    if image_id.startswith("sha256:"):
                        return str(image_id)

                    # Otherwise get the full image details
                    image_name = container_data[0].get("Config", {}).get("Image", "")
                    if image_name:
                        # Get digest of the image the container is using
                        digest = await self.get_local_image_digest(image_name)
                        return digest if digest else None

            return None

        except Exception as e:
            logger.error(f"Error getting container image digest for {container_name}: {e}")
            return None

    async def wait_for_container_stop(self, container_name: str, timeout: int = 60) -> bool:
        """
        Wait for a container to stop.

        Args:
            container_name: Name of the container to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if container stopped, False if timeout
        """
        import time

        start_time = time.time()
        poll_interval = 2  # seconds

        while time.time() - start_time < timeout:
            try:
                result = await asyncio.create_subprocess_exec(
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await result.communicate()

                if result.returncode != 0:
                    # Container doesn't exist or other error - consider it stopped
                    logger.debug(f"Container {container_name} no longer exists")
                    return True

                is_running = stdout.decode().strip().lower() == "true"
                if not is_running:
                    logger.debug(f"Container {container_name} has stopped")
                    return True

            except Exception as e:
                logger.warning(f"Error checking container {container_name} status: {e}")

            await asyncio.sleep(poll_interval)

        logger.warning(f"Timeout waiting for container {container_name} to stop")
        return False

    async def trigger_image_cleanup(self) -> None:
        """
        Trigger cleanup of old Docker images on all servers.

        This removes dangling images and old versions to free disk space.
        """
        if not self.manager or not hasattr(self.manager, "image_cleanup"):
            logger.debug("No image cleanup manager available")
            return

        try:
            # Trigger cleanup on the image cleanup manager
            await self.manager.image_cleanup.cleanup_all_servers()
            logger.info("Triggered image cleanup on all servers")
        except Exception as e:
            logger.warning(f"Failed to trigger image cleanup: {e}")

    async def store_container_version(
        self, container_type: str, new_image: str, state_dir: Optional[Path] = None
    ) -> None:
        """
        Store container version history for rollback capability.

        Maintains n, n-1, n-2 version history for infrastructure containers.

        Args:
            container_type: Type of container (gui, nginx, etc.)
            new_image: New image being deployed
            state_dir: Directory for version files (defaults to /var/lib/ciris-manager)
        """
        try:
            # Use provided state_dir or default
            if state_dir is None:
                state_dir = Path("/var/lib/ciris-manager")
                try:
                    state_dir.mkdir(parents=True, exist_ok=True)
                except PermissionError:
                    # Fall back to temp directory
                    import tempfile

                    state_dir = Path(tempfile.gettempdir()) / "ciris-manager"
                    state_dir.mkdir(parents=True, exist_ok=True)

            metadata_file = state_dir / f"{container_type}_versions.json"

            versions: Dict[str, Any] = {}
            if metadata_file.exists():
                async with aiofiles.open(metadata_file, "r") as f:
                    content = await f.read()
                    versions = json.loads(content)

            # Rotate versions
            current = versions.get("current")
            if current and current != new_image:  # Only rotate if actually different
                # Move n-1 to n-2 first
                n1 = versions.get("n-1")
                if n1:
                    versions["n-2"] = n1
                # Then move current to n-1
                versions["n-1"] = current

            # Store new version
            versions["current"] = new_image
            versions["updated_at"] = datetime.now(timezone.utc).isoformat()

            async with aiofiles.open(metadata_file, "w") as f:
                await f.write(json.dumps(versions, indent=2))

            logger.info(f"Stored {container_type} version: {new_image}")

        except Exception as e:
            logger.error(f"Failed to store {container_type} version: {e}")

    async def get_stored_versions(
        self, container_type: str, state_dir: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Get stored version history for a container type.

        Args:
            container_type: Type of container (gui, nginx, etc.)
            state_dir: Directory for version files

        Returns:
            Dictionary with current, n-1, n-2 versions
        """
        try:
            if state_dir is None:
                state_dir = Path("/var/lib/ciris-manager")

            metadata_file = state_dir / f"{container_type}_versions.json"

            if not metadata_file.exists():
                return {}

            async with aiofiles.open(metadata_file, "r") as f:
                content = await f.read()
                return json.loads(content)

        except Exception as e:
            logger.error(f"Failed to get {container_type} versions: {e}")
            return {}
