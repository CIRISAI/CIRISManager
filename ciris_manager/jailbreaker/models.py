"""
Jailbreaker models and configuration.
"""

from pydantic import BaseModel
from enum import Enum
from typing import Optional
import os


class ResetStatus(str, Enum):
    """Status of agent reset operation."""
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    AGENT_NOT_FOUND = "agent_not_found"
    ERROR = "error"


class ResetResult(BaseModel):
    """Result of jailbreaker reset operation."""
    status: ResetStatus
    message: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    next_allowed_reset: Optional[int] = None  # Unix timestamp


class JailbreakerConfig(BaseModel):
    """Configuration for jailbreaker service."""
    
    # Discord OAuth settings
    discord_client_id: str
    discord_client_secret: str
    discord_guild_id: str = "1364300186003968060"  # CIRIS Discord guild
    jailbreak_role_name: str = "jailbreak"
    
    # Target agent to reset
    target_agent_id: str = "datum"
    
    # Agent service token for API calls
    agent_service_token: Optional[str] = None
    
    # Rate limiting
    global_rate_limit: str = "1/5minutes"  # Global endpoint limit
    user_rate_limit: str = "1/hour"        # Per-user limit
    
    # OAuth callback URL
    callback_url: str = "https://agents.ciris.ai/manager/v1/jailbreaker/callback"
    redirect_url: str = "https://agents.ciris.ai/jailbreaker/result"
    
    @classmethod
    def from_env(cls) -> "JailbreakerConfig":
        """Create config from environment variables."""
        return cls(
            discord_client_id=os.getenv("DISCORD_CLIENT_ID", ""),
            discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", ""),
            discord_guild_id=os.getenv("DISCORD_GUILD_ID", "1364300186003968060"),
            jailbreak_role_name=os.getenv("JAILBREAK_ROLE_NAME", "jailbreak"),
            target_agent_id=os.getenv("JAILBREAK_TARGET_AGENT", "datum"),
            agent_service_token=os.getenv("JAILBREAK_AGENT_SERVICE_TOKEN"),
        )


class DiscordUser(BaseModel):
    """Discord user information from OAuth."""
    id: str
    username: str
    discriminator: str
    avatar: Optional[str] = None


class DiscordGuildMember(BaseModel):
    """Discord guild member with roles."""
    user: DiscordUser
    roles: list[str]  # Role IDs
    nick: Optional[str] = None