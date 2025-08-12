"""
Audit logging for deployment actions.

Tracks human decisions on deployments for compliance and analysis.
"""

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Audit log location
AUDIT_LOG_PATH = Path("/var/log/ciris-manager/audit.jsonl")


def audit_deployment_action(
    action: str,
    deployment_id: str,
    details: Optional[Dict[str, Any]] = None,
    user: Optional[str] = None,
) -> None:
    """
    Log a deployment action for audit purposes.
    
    Args:
        action: Action taken (launch, reject, pause, rollback)
        deployment_id: Deployment identifier
        details: Additional details about the action
        user: User who performed the action
    """
    try:
        # Ensure audit directory exists
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "deployment_id": deployment_id,
            "user": user or "system",
            "details": details or {},
        }
        
        # Append to audit log (JSONL format)
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
            
        logger.info(f"Audit: {action} deployment {deployment_id} by {user or 'system'}")
        
    except Exception as e:
        # Don't fail operations due to audit logging issues
        logger.error(f"Failed to write audit log: {e}")