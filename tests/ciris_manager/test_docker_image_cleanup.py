"""
Tests for Docker image cleanup service.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from ciris_manager.docker_image_cleanup import DockerImageCleanup


class TestDockerImageCleanup:
    """Test Docker image cleanup functionality."""

    @pytest.fixture
    def mock_docker_client(self):
        """Create mock Docker client."""
        with patch("ciris_manager.docker_image_cleanup.docker.from_env") as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def cleanup_service(self, mock_docker_client):
        """Create cleanup service with mocked Docker client."""
        return DockerImageCleanup(versions_to_keep=2)

    def test_get_running_images(self, cleanup_service, mock_docker_client):
        """Test getting images from running containers."""
        # Mock containers
        container1 = Mock()
        container1.image.id = "sha256:abc123"
        container1.image.tags = ["ghcr.io/cirisai/ciris-agent:v1.0"]
        
        container2 = Mock()
        container2.image.id = "sha256:def456"
        container2.image.tags = ["ghcr.io/cirisai/ciris-gui:v2.0"]
        
        mock_docker_client.containers.list.return_value = [container1, container2]
        
        # Get running images
        running_images = cleanup_service.get_running_images()
        
        # Check results
        assert "sha256:abc123" in running_images
        assert "sha256:def456" in running_images
        assert "ghcr.io/cirisai/ciris-agent:v1.0" in running_images
        assert "ghcr.io/cirisai/ciris-gui:v2.0" in running_images

    def test_group_images_by_repository(self, cleanup_service):
        """Test grouping images by repository."""
        # Mock images
        image1 = Mock()
        image1.tags = ["ghcr.io/cirisai/ciris-agent:v1.0", "ghcr.io/cirisai/ciris-agent:latest"]
        
        image2 = Mock()
        image2.tags = ["ghcr.io/cirisai/ciris-agent:v0.9"]
        
        image3 = Mock()
        image3.tags = ["ghcr.io/cirisai/ciris-gui:v1.0"]
        
        images = [image1, image2, image3]
        
        # Group images
        grouped = cleanup_service.group_images_by_repository(images)
        
        # Check results
        assert "ghcr.io/cirisai/ciris-agent" in grouped
        assert "ghcr.io/cirisai/ciris-gui" in grouped
        assert len(grouped["ghcr.io/cirisai/ciris-agent"]) == 2
        assert len(grouped["ghcr.io/cirisai/ciris-gui"]) == 1

    def test_sort_images_by_created(self, cleanup_service):
        """Test sorting images by creation date."""
        # Mock images with different creation times
        image1 = Mock()
        image1.attrs = {"Created": "2025-01-01T10:00:00Z"}
        
        image2 = Mock()
        image2.attrs = {"Created": "2025-01-02T10:00:00Z"}
        
        image3 = Mock()
        image3.attrs = {"Created": "2025-01-03T10:00:00Z"}
        
        images = [image1, image3, image2]
        
        # Sort images
        sorted_images = cleanup_service.sort_images_by_created(images)
        
        # Check order (newest first)
        assert sorted_images[0] == image3
        assert sorted_images[1] == image2
        assert sorted_images[2] == image1

    def test_cleanup_repository_images_keeps_recent(self, cleanup_service, mock_docker_client):
        """Test cleanup keeps recent versions."""
        # Mock images
        image1 = Mock()
        image1.id = "sha256:newest"
        image1.tags = ["ghcr.io/cirisai/ciris-agent:v3.0"]
        image1.attrs = {"Created": "2025-01-03T10:00:00Z"}
        
        image2 = Mock()
        image2.id = "sha256:middle"
        image2.tags = ["ghcr.io/cirisai/ciris-agent:v2.0"]
        image2.attrs = {"Created": "2025-01-02T10:00:00Z"}
        
        image3 = Mock()
        image3.id = "sha256:oldest"
        image3.tags = ["ghcr.io/cirisai/ciris-agent:v1.0"]
        image3.attrs = {"Created": "2025-01-01T10:00:00Z"}
        
        images = [image1, image2, image3]
        running_images = set()
        
        # Run cleanup
        removed = cleanup_service.cleanup_repository_images(
            "ghcr.io/cirisai/ciris-agent", 
            images, 
            running_images
        )
        
        # Should remove only the oldest (keeping 2 versions)
        assert removed == 1
        mock_docker_client.images.remove.assert_called_once_with("sha256:oldest", force=True)

    def test_cleanup_keeps_running_images(self, cleanup_service, mock_docker_client):
        """Test cleanup keeps images in use."""
        # Mock images
        image1 = Mock()
        image1.id = "sha256:newest"
        image1.tags = ["ghcr.io/cirisai/ciris-agent:v3.0"]
        image1.attrs = {"Created": "2025-01-03T10:00:00Z"}
        
        image2 = Mock()
        image2.id = "sha256:middle"
        image2.tags = ["ghcr.io/cirisai/ciris-agent:v2.0"]
        image2.attrs = {"Created": "2025-01-02T10:00:00Z"}
        
        image3 = Mock()
        image3.id = "sha256:oldest"
        image3.tags = ["ghcr.io/cirisai/ciris-agent:v1.0"]
        image3.attrs = {"Created": "2025-01-01T10:00:00Z"}
        
        images = [image1, image2, image3]
        # Mark oldest as in use
        running_images = {"sha256:oldest"}
        
        # Run cleanup
        removed = cleanup_service.cleanup_repository_images(
            "ghcr.io/cirisai/ciris-agent", 
            images, 
            running_images
        )
        
        # Should not remove any (2 recent + 1 in use)
        assert removed == 0
        mock_docker_client.images.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_images(self, cleanup_service, mock_docker_client):
        """Test full cleanup process."""
        # Mock running containers
        container = Mock()
        container.image.id = "sha256:running"
        container.image.tags = ["ghcr.io/cirisai/ciris-agent:v2.0"]
        mock_docker_client.containers.list.return_value = [container]
        
        # Mock all images
        image1 = Mock()
        image1.id = "sha256:newest"
        image1.tags = ["ghcr.io/cirisai/ciris-agent:v3.0"]
        image1.attrs = {"Created": "2025-01-03T10:00:00Z"}
        
        image2 = Mock()
        image2.id = "sha256:running"
        image2.tags = ["ghcr.io/cirisai/ciris-agent:v2.0"]
        image2.attrs = {"Created": "2025-01-02T10:00:00Z"}
        
        image3 = Mock()
        image3.id = "sha256:oldest"
        image3.tags = ["ghcr.io/cirisai/ciris-agent:v1.0"]
        image3.attrs = {"Created": "2025-01-01T10:00:00Z"}
        
        mock_docker_client.images.list.return_value = [image1, image2, image3]
        
        # Mock prune response
        mock_docker_client.images.prune.return_value = {"ImagesDeleted": []}
        
        # Run cleanup
        results = await cleanup_service.cleanup_images()
        
        # Check results
        assert "ghcr.io/cirisai/ciris-agent" in results
        # Should remove 1 image (oldest) - keeping 2 versions and the running one is one of them
        assert results["ghcr.io/cirisai/ciris-agent"] == 1
        
        # Check prune was called
        mock_docker_client.images.prune.assert_called_once()