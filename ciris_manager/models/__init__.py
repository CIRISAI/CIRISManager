"""
Pydantic models for CIRIS Manager CLI tool.

These models provide type-safe data structures and validation
for configuration files, API responses, and CLI operations.
"""

# Import legacy models from models.py file for backward compatibility
# Note: models.py exists alongside models/ directory during migration
import importlib.util
from pathlib import Path

_models_py_path = Path(__file__).parent.parent / "models.py"
_spec = importlib.util.spec_from_file_location("ciris_manager.legacy_models", _models_py_path)
if _spec and _spec.loader:
    _legacy = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_legacy)

    # Re-export legacy models for backward compatibility
    AgentInfo = _legacy.AgentInfo  # Legacy AgentInfo from models.py
    CreateAgentRequest = _legacy.CreateAgentRequest
    UpdateNotification = _legacy.UpdateNotification
    DeploymentStatus = _legacy.DeploymentStatus
    AgentUpdateResponse = _legacy.AgentUpdateResponse
    OAuthToken = _legacy.OAuthToken
    OAuthUser = _legacy.OAuthUser
    OAuthSession = _legacy.OAuthSession
    JWTPayload = _legacy.JWTPayload
    PortAllocation = _legacy.PortAllocation

# Import new modular agent models (noqa: E402 needed because legacy module loading must happen first)
from ciris_manager.models.agent import (  # noqa: E402
    AgentConfig,
    AgentCreate,
    AgentUpdate,
    AgentStatus,
    # AgentInfo,  # Commented out - using legacy AgentInfo from models.py for now
    AgentListItem,
    AgentMaintenanceMode,
    AgentOAuthStatus,
)
from ciris_manager.models.backup import (  # noqa: E402
    AgentBackup,
    AgentBackupData,
    BackupMetadata,
    RestoreOptions,
    RestoreResult,
)
from ciris_manager.models.deployment import (  # noqa: E402
    DeploymentNotification,
    DeploymentStatusDetailed,  # New fully-typed version
    DeploymentEvent,
    DeploymentHistory,
    RollbackOption,
    CanaryGroup,
)
from ciris_manager.models.server import (  # noqa: E402
    ServerInfo,
    ServerDetails,
    ServerStats,
    ServerComparison,
)
from ciris_manager.models.template import (  # noqa: E402
    TemplateInfo,
    TemplateDetails,
    TemplateEnvironment,
    TemplateValidation,
    TemplateListResponse,
)
from ciris_manager.models.system import (  # noqa: E402
    SystemHealth,
    SystemStatus,
    PortAllocation,
    PortRange,
    AllocatedPortsResponse,
    DeploymentToken,
    DeploymentTokenInfo,
    SystemMetrics,
    StatusResponse,
)
from ciris_manager.models.llm import (  # noqa: E402
    LLMProvider,
    LLMProviderConfig,
    LLMConfig,
    LLMConfigResponse,
    LLMProviderConfigRedacted,
    LLMConfigUpdate,
    LLMValidateRequest,
    LLMValidateResponse,
    PROVIDER_DEFAULTS,
    redact_api_key,
    redact_provider_config,
    redact_llm_config,
)

__all__ = [
    # Legacy models from models.py (backward compatibility)
    "AgentInfo",  # Legacy version from models.py
    "CreateAgentRequest",
    "UpdateNotification",
    "DeploymentStatus",
    "AgentUpdateResponse",
    "OAuthToken",
    "OAuthUser",
    "OAuthSession",
    "JWTPayload",
    "PortAllocation",
    # New agent models from models/agent.py
    "AgentConfig",
    "AgentCreate",
    "AgentUpdate",
    "AgentStatus",
    "AgentListItem",
    "AgentMaintenanceMode",
    "AgentOAuthStatus",
    # Backup models
    "AgentBackup",
    "AgentBackupData",
    "BackupMetadata",
    "RestoreOptions",
    "RestoreResult",
    # Deployment models
    "DeploymentNotification",
    "DeploymentStatus",  # Legacy version from models.py
    "DeploymentStatusDetailed",  # New fully-typed version
    "DeploymentEvent",
    "DeploymentHistory",
    "RollbackOption",
    "CanaryGroup",
    # Server models
    "ServerInfo",
    "ServerDetails",
    "ServerStats",
    "ServerComparison",
    # Template models
    "TemplateInfo",
    "TemplateDetails",
    "TemplateEnvironment",
    "TemplateValidation",
    "TemplateListResponse",
    # System models
    "SystemHealth",
    "SystemStatus",
    "PortRange",
    "AllocatedPortsResponse",
    "DeploymentToken",
    "DeploymentTokenInfo",
    "SystemMetrics",
    "StatusResponse",
    # LLM models
    "LLMProvider",
    "LLMProviderConfig",
    "LLMConfig",
    "LLMConfigResponse",
    "LLMProviderConfigRedacted",
    "LLMConfigUpdate",
    "LLMValidateRequest",
    "LLMValidateResponse",
    "PROVIDER_DEFAULTS",
    "redact_api_key",
    "redact_provider_config",
    "redact_llm_config",
]
