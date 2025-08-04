"""
Security audit logging for CIRISManager.

Tracks service token usage and other security-relevant events.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import hashlib

logger = logging.getLogger(__name__)

# Separate audit logger
audit_logger = logging.getLogger("ciris_manager.security.audit")


class AuditEvent:
    """Security audit event."""

    def __init__(
        self,
        event_type: str,
        agent_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
        success: bool = True,
        details: Optional[Dict[str, Any]] = None,
        token_hash: Optional[str] = None,
    ):
        """
        Create audit event.

        Args:
            event_type: Type of event (e.g., "service_token_auth", "deployment_update")
            agent_id: Agent involved
            deployment_id: Deployment ID if applicable
            success: Whether operation succeeded
            details: Additional context
            token_hash: First 8 chars of SHA256 hash of token (for correlation)
        """
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.event_type = event_type
        self.agent_id = agent_id
        self.deployment_id = deployment_id
        self.success = success
        self.details = details or {}
        self.token_hash = token_hash

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "deployment_id": self.deployment_id,
            "success": self.success,
            "token_hash": self.token_hash,
            "details": self.details,
        }

    def log(self) -> None:
        """Log this audit event."""
        audit_logger.info(json.dumps(self.to_dict()))


def audit_service_token_use(
    agent_id: str,
    deployment_id: Optional[str] = None,
    success: bool = True,
    reason: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """
    Audit service token authentication attempt.

    Args:
        agent_id: Agent being authenticated
        deployment_id: Associated deployment
        success: Whether auth succeeded
        reason: Failure reason if applicable
        token: Token used (will be hashed, not stored)
    """
    token_hash = None
    if token:
        # Only store first 8 chars of hash for correlation
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:8]

    event = AuditEvent(
        event_type="service_token_auth",
        agent_id=agent_id,
        deployment_id=deployment_id,
        success=success,
        details={"reason": reason} if reason else {},
        token_hash=token_hash,
    )
    event.log()


def audit_deployment_action(
    deployment_id: str,
    action: str,
    agent_id: Optional[str] = None,
    success: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Audit deployment-related actions.

    Args:
        deployment_id: Deployment ID
        action: Action taken (e.g., "shutdown_requested", "update_accepted")
        agent_id: Agent involved
        success: Whether action succeeded
        details: Additional context
    """
    event = AuditEvent(
        event_type=f"deployment_{action}",
        agent_id=agent_id,
        deployment_id=deployment_id,
        success=success,
        details=details or {},
    )
    event.log()


def setup_audit_logging(log_dir: Optional[Path] = None) -> None:
    """
    Configure audit logging to file.

    Args:
        log_dir: Directory for audit logs (default: /var/log/ciris-manager)
    """
    if log_dir is None:
        log_dir = Path("/var/log/ciris-manager")

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        audit_file = log_dir / "security-audit.log"

        # Configure audit logger
        handler = logging.FileHandler(audit_file)
        handler.setFormatter(logging.Formatter("%(message)s"))  # JSON format

        audit_logger.addHandler(handler)
        audit_logger.setLevel(logging.INFO)
        audit_logger.propagate = False  # Don't send to root logger

        logger.info(f"Security audit logging configured: {audit_file}")
    except PermissionError:
        logger.warning(f"Cannot create audit log directory {log_dir} - audit logging disabled")
    except Exception as e:
        logger.error(f"Failed to setup audit logging: {e}")
