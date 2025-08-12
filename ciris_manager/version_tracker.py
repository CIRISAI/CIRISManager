"""
Version tracking system for CIRISManager deployments.
Tracks n/n-1/n-2 versions for all container types (agents, GUI, nginx).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
import asyncio
import aiofiles  # type: ignore
import logging

logger = logging.getLogger(__name__)


@dataclass
class ContainerVersion:
    """Represents a version of a container."""

    image: str  # Full image name with tag
    digest: Optional[str] = None  # Image digest for verification
    deployed_at: Optional[str] = None  # ISO timestamp
    deployment_id: Optional[str] = None  # Associated deployment ID
    deployed_by: Optional[str] = None  # Operator who deployed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class VersionState:
    """Current version state for a container type."""

    n_plus_1: Optional[ContainerVersion] = None  # Staged/pending version
    n: Optional[ContainerVersion] = None  # Current version
    n_minus_1: Optional[ContainerVersion] = None  # Previous version
    n_minus_2: Optional[ContainerVersion] = None  # Older version

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "n_plus_1": self.n_plus_1.to_dict() if self.n_plus_1 else None,
            "n": self.n.to_dict() if self.n else None,
            "n_minus_1": self.n_minus_1.to_dict() if self.n_minus_1 else None,
            "n_minus_2": self.n_minus_2.to_dict() if self.n_minus_2 else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VersionState":
        """Create from dictionary."""
        return cls(
            n_plus_1=ContainerVersion(**data["n_plus_1"]) if data.get("n_plus_1") else None,
            n=ContainerVersion(**data["n"]) if data.get("n") else None,
            n_minus_1=ContainerVersion(**data["n_minus_1"]) if data.get("n_minus_1") else None,
            n_minus_2=ContainerVersion(**data["n_minus_2"]) if data.get("n_minus_2") else None,
        )


class VersionTracker:
    """
    Tracks version history for all container types.
    Maintains n/n-1/n-2 versions with optional n+1 for staged deployments.
    """

    def __init__(self, data_dir: str = "/var/lib/ciris-manager"):
        """Initialize version tracker with persistent storage."""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.version_file = self.data_dir / "version_state.json"

        # Version state for each container type
        self.state: Dict[str, VersionState] = {
            "agents": VersionState(),
            "gui": VersionState(),
            "nginx": VersionState(),
        }

        # Lock for concurrent access
        self._lock = asyncio.Lock()

        # Flag to track if we've loaded state
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        """Ensure state has been loaded from disk."""
        if not self._loaded:
            await self._load_state()
            self._loaded = True

    async def _load_state(self) -> None:
        """Load version state from disk."""
        if not self.version_file.exists():
            logger.info("No existing version state found, starting fresh")
            return

        try:
            async with aiofiles.open(self.version_file, "r") as f:
                data = json.loads(await f.read())

            for container_type, state_data in data.items():
                if container_type in self.state:
                    self.state[container_type] = VersionState.from_dict(state_data)

            logger.info(f"Loaded version state from {self.version_file}")
        except Exception as e:
            logger.error(f"Failed to load version state: {e}")

    async def _save_state(self) -> None:
        """Save version state to disk."""
        try:
            data = {container_type: state.to_dict() for container_type, state in self.state.items()}

            # Write atomically using temp file
            temp_file = self.version_file.with_suffix(".tmp")
            async with aiofiles.open(temp_file, "w") as f:
                await f.write(json.dumps(data, indent=2))

            # Atomic rename
            temp_file.replace(self.version_file)

            logger.debug(f"Saved version state to {self.version_file}")
        except Exception as e:
            logger.error(f"Failed to save version state: {e}")
            raise

    async def stage_version(
        self,
        container_type: str,
        image: str,
        digest: Optional[str] = None,
        deployment_id: Optional[str] = None,
        deployed_by: Optional[str] = None,
    ) -> None:
        """
        Stage a new version as n+1 (pending deployment).

        Args:
            container_type: Type of container (agents, gui, nginx)
            image: Full image name with tag
            digest: Optional image digest
            deployment_id: Associated deployment ID
            deployed_by: Operator staging the deployment
        """
        async with self._lock:
            if container_type not in self.state:
                raise ValueError(f"Unknown container type: {container_type}")

            self.state[container_type].n_plus_1 = ContainerVersion(
                image=image,
                digest=digest,
                deployed_at=datetime.utcnow().isoformat(),
                deployment_id=deployment_id,
                deployed_by=deployed_by,
            )

            await self._save_state()
            logger.info(f"Staged {container_type} version {image} as n+1")

    async def promote_staged_version(
        self, container_type: str, deployment_id: Optional[str] = None
    ) -> None:
        """
        Promote staged version (n+1) to current (n).
        Shifts all versions down: n+1→n, n→n-1, n-1→n-2, n-2 is dropped.

        Args:
            container_type: Type of container to promote
            deployment_id: Deployment ID for tracking
        """
        async with self._lock:
            if container_type not in self.state:
                raise ValueError(f"Unknown container type: {container_type}")

            state = self.state[container_type]

            if not state.n_plus_1:
                logger.warning(f"No staged version for {container_type}, nothing to promote")
                return

            # Shift versions down
            old_n_minus_1 = state.n_minus_1
            state.n_minus_2 = old_n_minus_1
            state.n_minus_1 = state.n
            state.n = state.n_plus_1
            state.n_plus_1 = None

            # Update deployment ID if provided
            if deployment_id and state.n:
                state.n.deployment_id = deployment_id
                state.n.deployed_at = datetime.utcnow().isoformat()

            await self._save_state()
            logger.info(f"Promoted {container_type} staged version to current")

    async def record_deployment(
        self,
        container_type: str,
        image: str,
        digest: Optional[str] = None,
        deployment_id: Optional[str] = None,
        deployed_by: Optional[str] = None,
    ) -> None:
        """
        Record a direct deployment (bypassing staging).
        Shifts versions: new→n, n→n-1, n-1→n-2.

        Args:
            container_type: Type of container
            image: Full image name with tag
            digest: Optional image digest
            deployment_id: Associated deployment ID
            deployed_by: Operator who deployed
        """
        async with self._lock:
            if container_type not in self.state:
                raise ValueError(f"Unknown container type: {container_type}")

            state = self.state[container_type]

            # Create new version
            new_version = ContainerVersion(
                image=image,
                digest=digest,
                deployed_at=datetime.utcnow().isoformat(),
                deployment_id=deployment_id,
                deployed_by=deployed_by,
            )

            # Shift versions down
            state.n_minus_2 = state.n_minus_1
            state.n_minus_1 = state.n
            state.n = new_version

            # Clear any staged version
            state.n_plus_1 = None

            await self._save_state()
            logger.info(f"Recorded deployment of {container_type} version {image}")

    async def get_rollback_options(self, container_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get available rollback options.

        Args:
            container_type: Specific container type or None for all

        Returns:
            Dictionary with rollback options for each container type
        """
        await self._ensure_loaded()
        async with self._lock:
            if container_type:
                if container_type not in self.state:
                    raise ValueError(f"Unknown container type: {container_type}")

                state = self.state[container_type]
                return {
                    "current": state.n.to_dict() if state.n else None,
                    "n_minus_1": state.n_minus_1.to_dict() if state.n_minus_1 else None,
                    "n_minus_2": state.n_minus_2.to_dict() if state.n_minus_2 else None,
                    "staged": state.n_plus_1.to_dict() if state.n_plus_1 else None,
                }

            # Return all container types
            result = {}
            for ctype, state in self.state.items():
                result[ctype] = {
                    "current": state.n.to_dict() if state.n else None,
                    "n_minus_1": state.n_minus_1.to_dict() if state.n_minus_1 else None,
                    "n_minus_2": state.n_minus_2.to_dict() if state.n_minus_2 else None,
                    "staged": state.n_plus_1.to_dict() if state.n_plus_1 else None,
                }
            return result

    async def get_version_history(
        self, container_type: str, include_staged: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get version history for a container type.

        Args:
            container_type: Type of container
            include_staged: Whether to include staged (n+1) version

        Returns:
            List of versions in order [n+1, n, n-1, n-2]
        """
        async with self._lock:
            if container_type not in self.state:
                raise ValueError(f"Unknown container type: {container_type}")

            state = self.state[container_type]
            history = []

            if include_staged and state.n_plus_1:
                history.append({"position": "n+1", "status": "staged", **state.n_plus_1.to_dict()})

            if state.n:
                history.append({"position": "n", "status": "current", **state.n.to_dict()})

            if state.n_minus_1:
                history.append(
                    {"position": "n-1", "status": "previous", **state.n_minus_1.to_dict()}
                )

            if state.n_minus_2:
                history.append({"position": "n-2", "status": "older", **state.n_minus_2.to_dict()})

            return history

    async def clear_staged(self, container_type: Optional[str] = None) -> None:
        """
        Clear staged (n+1) version.

        Args:
            container_type: Specific container type or None for all
        """
        async with self._lock:
            if container_type:
                if container_type not in self.state:
                    raise ValueError(f"Unknown container type: {container_type}")
                self.state[container_type].n_plus_1 = None
            else:
                # Clear all staged versions
                for state in self.state.values():
                    state.n_plus_1 = None

            await self._save_state()
            logger.info(f"Cleared staged versions for {container_type or 'all containers'}")

    async def validate_rollback(self, target_versions: Dict[str, str]) -> Dict[str, Any]:
        """
        Validate if rollback is safe with given target versions.

        Args:
            target_versions: Map of container_type to target image

        Returns:
            Validation result with any warnings or errors
        """
        async with self._lock:
            result: Dict[str, Any] = {"valid": True, "warnings": [], "errors": []}

            for container_type, target_image in target_versions.items():
                if container_type not in self.state:
                    result["errors"].append(f"Unknown container type: {container_type}")
                    result["valid"] = False
                    continue

                state = self.state[container_type]

                # Check if target is in our version history
                found = False
                for version in [state.n, state.n_minus_1, state.n_minus_2]:
                    if version and version.image == target_image:
                        found = True
                        break

                if not found:
                    result["warnings"].append(
                        f"{container_type}: Target version {target_image} not in tracked history"
                    )

            # Add compatibility checks here in the future
            # For now, just warn about mixed version rollback
            unique_targets = len(set(target_versions.values()))
            if unique_targets > 1:
                result["warnings"].append(
                    "Rolling back to different versions across container types"
                )

            return result


# Global instance
_version_tracker: Optional[VersionTracker] = None


def get_version_tracker() -> VersionTracker:
    """Get or create the global version tracker instance."""
    global _version_tracker
    if _version_tracker is None:
        _version_tracker = VersionTracker()
    return _version_tracker
