"""CIRISManager - Production-grade lifecycle management for CIRIS agents."""

__version__ = "2.2.0"

# Export core functions for v2 API
from .core import get_manager, set_manager

__all__ = ["get_manager", "set_manager"]
