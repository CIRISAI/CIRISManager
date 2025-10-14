"""
Pydantic models for backup and restore operations.

These models define data structures for creating, managing, and restoring
agent backups in the CIRIS Manager system.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class BackupMetadata(BaseModel):
    """
    Metadata for a CIRIS Manager backup.

    Provides information about backup creation, contents, and version compatibility.
    """

    timestamp: str = Field(description="Backup timestamp in format YYYYMMDD_HHMMSS")
    date: str = Field(description="ISO 8601 formatted backup creation date")
    hostname: str = Field(description="Hostname of the server where backup was created")
    version: str = Field(description="CIRIS Manager version at time of backup")
    included_paths: List[str] = Field(description="List of file paths included in the backup")
    backup_size: str = Field(description="Human-readable backup file size (e.g., '45M', '1.2G')")
    agent_count: Optional[int] = Field(
        default=None, description="Number of agents included in backup"
    )
    agents: Optional[List[str]] = Field(
        default=None, description="List of agent IDs included in backup"
    )
    description: Optional[str] = Field(
        default=None, description="Optional description of backup purpose"
    )


class AgentBackupData(BaseModel):
    """
    Individual agent's backup data.

    Contains all necessary information to restore a single agent.
    """

    agent_id: str = Field(description="Unique agent identifier")
    name: str = Field(description="Human-friendly agent name")
    port: int = Field(description="Allocated port number")
    template: str = Field(description="Template used to create agent")
    compose_file: str = Field(description="Path to docker-compose.yml")
    created_at: str = Field(description="ISO 8601 timestamp of agent creation")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Agent metadata including deployment and canary group"
    )
    oauth_status: Optional[str] = Field(default=None, description="OAuth configuration status")
    service_token: Optional[str] = Field(
        default=None, description="Encrypted service token for authentication"
    )
    admin_password: Optional[str] = Field(default=None, description="Encrypted admin password")
    current_version: Optional[str] = Field(default=None, description="Current agent version")
    last_work_state_at: Optional[str] = Field(
        default=None, description="ISO 8601 timestamp when agent last entered WORK state"
    )
    version_transitions: List[Dict[str, Any]] = Field(
        default_factory=list, description="History of version transitions"
    )
    do_not_autostart: bool = Field(
        default=False, description="Whether to prevent automatic restart"
    )
    server_id: str = Field(default="main", description="Server hosting the agent")
    environment_vars: Optional[Dict[str, str]] = Field(
        default=None, description="Environment variables for the agent"
    )


class AgentBackup(BaseModel):
    """
    Complete backup bundle with multiple agents.

    Contains all agent data, configuration, and metadata needed for restoration.
    """

    metadata: BackupMetadata = Field(description="Backup metadata and information")
    agents: List[AgentBackupData] = Field(description="List of agents included in this backup")
    registry_version: str = Field(default="1.0", description="Agent registry format version")
    port_allocations: Dict[str, int] = Field(
        default_factory=dict, description="Mapping of agent IDs to allocated ports"
    )
    docker_compose_content: Optional[str] = Field(
        default=None, description="Content of docker-compose.yml if available"
    )
    nginx_config: Optional[str] = Field(
        default=None, description="Nginx configuration at time of backup"
    )


class RestoreOptions(BaseModel):
    """
    Options for restore operation.

    Controls how backup data should be restored and what conflicts to resolve.
    """

    force: bool = Field(
        default=False, description="Skip confirmation prompts and overwrite existing data"
    )
    restore_agents: bool = Field(
        default=True, description="Restore agent configurations and metadata"
    )
    restore_config: bool = Field(default=True, description="Restore manager configuration files")
    restore_templates: bool = Field(default=True, description="Restore agent templates")
    overwrite_existing: bool = Field(
        default=False, description="Overwrite agents with matching IDs"
    )
    start_services: bool = Field(
        default=False, description="Automatically start services after restore"
    )
    target_server: Optional[str] = Field(
        default=None, description="Target server ID for restoration (None = use original)"
    )
    port_remap: Optional[Dict[str, int]] = Field(
        default=None, description="Remap agent ports during restore (agent_id -> new_port)"
    )
    exclude_agents: List[str] = Field(
        default_factory=list, description="List of agent IDs to exclude from restore"
    )
    include_only: Optional[List[str]] = Field(
        default=None, description="If set, only restore these agent IDs"
    )
    dry_run: bool = Field(default=False, description="Simulate restore without making changes")
    backup_existing: bool = Field(
        default=True, description="Create backup of existing configuration before restore"
    )


class RestoreResult(BaseModel):
    """
    Result of a restore operation.

    Provides detailed information about what was restored and any errors encountered.
    """

    success: bool = Field(description="Whether restore completed successfully")
    agents_restored: List[str] = Field(
        default_factory=list, description="List of agent IDs successfully restored"
    )
    agents_skipped: List[str] = Field(default_factory=list, description="List of agent IDs skipped")
    agents_failed: List[str] = Field(
        default_factory=list, description="List of agent IDs that failed to restore"
    )
    errors: List[str] = Field(
        default_factory=list, description="List of error messages encountered"
    )
    warnings: List[str] = Field(default_factory=list, description="List of warning messages")
    pre_restore_backup: Optional[str] = Field(
        default=None, description="Path to pre-restore backup if created"
    )
    restored_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO 8601 timestamp of restore completion",
    )
    duration_seconds: Optional[float] = Field(
        default=None, description="Duration of restore operation in seconds"
    )
