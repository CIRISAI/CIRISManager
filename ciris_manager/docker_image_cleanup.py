"""
Docker image cleanup service.

Removes old Docker images to prevent disk space issues.
Keeps N-2 versions or the oldest version currently in use by agents.
"""

import asyncio
import logging
from typing import List, Set, Dict, Optional, Any
from datetime import datetime
import docker

logger = logging.getLogger(__name__)


class DockerImageCleanup:
    """Manages cleanup of old Docker images."""

    def __init__(self, versions_to_keep: int = 2):
        """
        Initialize Docker image cleanup service.

        Args:
            versions_to_keep: Number of recent versions to keep (default: 2)
        """
        self.versions_to_keep = versions_to_keep
        self.client = docker.from_env()

    def get_running_images(self) -> Set[str]:
        """
        Get set of images currently used by running containers.

        Returns:
            Set of image IDs and tags in use
        """
        running_images = set()

        try:
            containers = self.client.containers.list()
            for container in containers:
                # Add both image ID and tags
                if container.image:
                    if container.image.id:
                        running_images.add(container.image.id)
                    for tag in container.image.tags:
                        running_images.add(tag)

        except Exception as e:
            logger.error(f"Failed to get running containers: {e}")

        return running_images

    def group_images_by_repository(self, images: List) -> Dict[str, List]:
        """
        Group Docker images by repository name.

        Args:
            images: List of Docker image objects

        Returns:
            Dictionary mapping repository names to list of images
        """
        grouped: Dict[str, List] = {}

        for image in images:
            if not image.tags:
                continue

            # Track repositories we've added this image to
            repos_added = set()

            for tag in image.tags:
                # Parse repository from tag (e.g., "ghcr.io/cirisai/ciris-agent:v1.0")
                if ":" in tag:
                    repo = tag.rsplit(":", 1)[0]
                else:
                    repo = tag

                # Only add image once per repository
                if repo not in repos_added:
                    if repo not in grouped:
                        grouped[repo] = []
                    grouped[repo].append(image)
                    repos_added.add(repo)

        return grouped

    def sort_images_by_created(self, images: List) -> List:
        """
        Sort images by creation date, newest first.

        Args:
            images: List of Docker image objects

        Returns:
            Sorted list of images
        """

        def get_created_time(image: Any) -> datetime:
            try:
                # Parse creation time from image attributes
                created = image.attrs.get("Created", "")
                if created:
                    return datetime.fromisoformat(created.replace("Z", "+00:00"))
                return datetime.min
            except Exception:
                return datetime.min

        return sorted(images, key=get_created_time, reverse=True)

    def cleanup_repository_images(
        self, repo_name: str, images: List, running_images: Set[str]
    ) -> int:
        """
        Clean up old images for a specific repository.

        Args:
            repo_name: Repository name
            images: List of images for this repository
            running_images: Set of images currently in use

        Returns:
            Number of images removed
        """
        # Sort images by creation date (newest first)
        sorted_images = self.sort_images_by_created(images)

        # Keep track of kept versions
        kept_versions = 0
        removed_count = 0

        for image in sorted_images:
            # Check if image is in use
            in_use = False
            if image.id in running_images:
                in_use = True
            else:
                for tag in image.tags:
                    if tag in running_images:
                        in_use = True
                        break

            # Keep if in use
            if in_use:
                logger.info(f"Keeping {image.tags} - currently in use")
                kept_versions += 1
                continue

            # Keep if within versions_to_keep limit
            if kept_versions < self.versions_to_keep:
                logger.info(
                    f"Keeping {image.tags} - within keep limit ({kept_versions + 1}/{self.versions_to_keep})"
                )
                kept_versions += 1
                continue

            # Remove old image
            try:
                logger.info(f"Removing old image: {image.tags}")
                self.client.images.remove(image.id, force=True)
                removed_count += 1
            except Exception as e:
                logger.error(f"Failed to remove image {image.tags}: {e}")

        return removed_count

    async def cleanup_images(self, target_repos: Optional[List[str]] = None) -> Dict[str, int]:
        """
        Clean up old Docker images.

        Args:
            target_repos: Optional list of repository names to clean up.
                         If None, cleans up common CIRIS repos.

        Returns:
            Dictionary mapping repository names to number of images removed
        """
        if target_repos is None:
            target_repos = [
                "ghcr.io/cirisai/ciris-agent",
                "ghcr.io/cirisai/ciris-gui",
                "ciris-agent",
                "ciris-gui",
            ]

        logger.info(f"Starting Docker image cleanup for repos: {target_repos}")

        try:
            # Get images currently in use
            running_images = self.get_running_images()
            logger.info(f"Found {len(running_images)} images in use")

            # Get all images
            all_images = self.client.images.list()
            logger.info(f"Found {len(all_images)} total images")

            # Group by repository
            grouped_images = self.group_images_by_repository(all_images)

            # Clean up each target repository
            cleanup_results = {}

            for repo in target_repos:
                if repo in grouped_images:
                    images = grouped_images[repo]
                    logger.info(f"Processing {repo}: {len(images)} images")
                    removed = self.cleanup_repository_images(repo, images, running_images)
                    cleanup_results[repo] = removed
                else:
                    logger.info(f"No images found for repository: {repo}")
                    cleanup_results[repo] = 0

            # Also clean up dangling images
            try:
                dangling = self.client.images.prune(filters={"dangling": True})
                if dangling and dangling.get("ImagesDeleted"):
                    logger.info(f"Removed {len(dangling.get('ImagesDeleted', []))} dangling images")
                else:
                    logger.info("No dangling images to remove")
            except Exception as e:
                logger.error(f"Failed to prune dangling images: {e}")

            return cleanup_results

        except Exception as e:
            logger.error(f"Image cleanup failed: {e}")
            return {}

    async def run_periodic_cleanup(self, interval_hours: int = 24) -> None:
        """
        Run cleanup periodically.

        Args:
            interval_hours: Hours between cleanup runs (default: 24)
        """
        while True:
            try:
                logger.info("Running periodic Docker image cleanup")
                results = await self.cleanup_images()

                total_removed = sum(results.values())
                logger.info(f"Cleanup completed. Removed {total_removed} images total")

                for repo, count in results.items():
                    if count > 0:
                        logger.info(f"  {repo}: removed {count} images")

            except Exception as e:
                logger.error(f"Periodic cleanup failed: {e}")

            # Wait for next run
            await asyncio.sleep(interval_hours * 3600)
