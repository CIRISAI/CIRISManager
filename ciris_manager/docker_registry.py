"""
Docker registry client for image digest resolution.

Handles communication with Docker registries to resolve image tags to digests.
"""

import logging
from typing import Optional, Tuple
import httpx

logger = logging.getLogger(__name__)


class DockerRegistryClient:
    """Client for interacting with Docker registries."""

    def __init__(self, auth_token: Optional[str] = None):
        """
        Initialize Docker registry client.

        Args:
            auth_token: Optional GitHub token for ghcr.io authentication
        """
        self.auth_token = auth_token
        self._client = httpx.AsyncClient(timeout=30.0)

    async def resolve_image_digest(self, image_ref: str) -> Optional[str]:
        """
        Resolve an image reference to its digest.

        Args:
            image_ref: Image reference (e.g., "ghcr.io/cirisai/ciris-agent:latest")

        Returns:
            Image digest (e.g., "sha256:abc123...") or None if resolution fails
        """
        try:
            registry, repository, tag = self._parse_image_reference(image_ref)

            # Get authentication token if needed
            auth_header = await self._get_auth_header(registry, repository)

            # Fetch manifest to get digest
            headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
            if auth_header:
                headers["Authorization"] = auth_header

            url = f"https://{registry}/v2/{repository}/manifests/{tag}"
            response = await self._client.get(url, headers=headers)

            if response.status_code == 200:
                # Digest is in the Docker-Content-Digest header
                digest = response.headers.get("Docker-Content-Digest")
                if digest:
                    logger.info(f"Resolved {image_ref} to {digest}")
                    return digest
                else:
                    logger.warning(f"No digest found for {image_ref}")
            else:
                logger.error(f"Failed to resolve {image_ref}: {response.status_code}")

        except Exception as e:
            logger.error(f"Error resolving image digest for {image_ref}: {e}")

        return None

    def _parse_image_reference(self, image_ref: str) -> Tuple[str, str, str]:
        """
        Parse image reference into registry, repository, and tag.

        Args:
            image_ref: Full image reference

        Returns:
            Tuple of (registry, repository, tag)
        """
        # Handle image references with or without protocol
        if "://" in image_ref:
            image_ref = image_ref.split("://", 1)[1]

        # Split registry from the rest
        parts = image_ref.split("/", 1)
        if len(parts) == 2 and ("." in parts[0] or ":" in parts[0]):
            registry = parts[0]
            remainder = parts[1]
        else:
            # Default to Docker Hub
            registry = "registry-1.docker.io"
            remainder = image_ref

        # Split repository and tag
        if "@" in remainder:
            # Already a digest reference
            repository = remainder.split("@")[0]
            tag = remainder.split("@")[1]
        elif ":" in remainder:
            # Tag reference
            repository = remainder.rsplit(":", 1)[0]
            tag = remainder.rsplit(":", 1)[1]
        else:
            # No tag specified, use latest
            repository = remainder
            tag = "latest"

        return registry, repository, tag

    async def _get_auth_header(self, registry: str, repository: str) -> Optional[str]:
        """
        Get authentication header for registry.

        Args:
            registry: Registry hostname
            repository: Repository name

        Returns:
            Authorization header value or None
        """
        if registry == "ghcr.io" and self.auth_token:
            # GitHub Container Registry uses bearer token
            return f"Bearer {self.auth_token}"
        elif registry == "registry-1.docker.io":
            # Docker Hub requires token exchange
            # For now, we'll skip auth for public images
            return None

        return None

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
