"""
Core manager access for API routes.
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ciris_manager.manager import CIRISManager

# Global manager instance
_manager: Optional["CIRISManager"] = None


def set_manager(manager: "CIRISManager") -> None:
    """Set the global manager instance."""
    global _manager
    _manager = manager


def get_manager() -> "CIRISManager":
    """Get the global manager instance."""
    if _manager is None:
        raise RuntimeError("Manager not initialized. Call set_manager() first.")
    return _manager
