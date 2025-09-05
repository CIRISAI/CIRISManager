"""
Discord OAuth and API client for jailbreaker functionality.
"""

import httpx
import logging
from typing import Optional, Dict
import urllib.parse
import secrets

from .models import JailbreakerConfig, DiscordUser, DiscordGuildMember

logger = logging.getLogger(__name__)


class DiscordAuthClient:
    """Handles Discord OAuth flow and API interactions for jailbreaker."""

    DISCORD_API_BASE = "https://discord.com/api/v10"
    DISCORD_OAUTH_BASE = "https://discord.com/api/oauth2"

    def __init__(self, config: JailbreakerConfig):
        self.config = config
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        """Clean up HTTP client."""
        await self._client.aclose()

    def generate_oauth_url(self, state: Optional[str] = None) -> tuple[str, str]:
        """
        Generate Discord OAuth URL for jailbreaker flow.

        Returns:
            Tuple of (auth_url, state)
        """
        if not state:
            state = secrets.token_urlsafe(32)

        params = {
            "client_id": self.config.discord_client_id,
            "redirect_uri": self.config.callback_url,
            "response_type": "code",
            "scope": "identify guilds.members.read",
            "state": state,
            "prompt": "consent",  # Force re-consent to ensure fresh tokens
        }

        auth_url = f"{self.DISCORD_OAUTH_BASE}/authorize?" + urllib.parse.urlencode(params)
        logger.debug(f"Generated Discord OAuth URL with state: {state[:8]}...")

        return auth_url, state

    async def exchange_code_for_token(self, code: str) -> str:
        """
        Exchange OAuth code for access token.

        Args:
            code: OAuth authorization code from Discord

        Returns:
            Access token

        Raises:
            httpx.HTTPStatusError: If token exchange fails
        """
        token_data = {
            "client_id": self.config.discord_client_id,
            "client_secret": self.config.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.callback_url,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        logger.debug("Exchanging OAuth code for Discord token")
        response = await self._client.post(
            f"{self.DISCORD_OAUTH_BASE}/token", data=token_data, headers=headers
        )
        response.raise_for_status()

        token_response = response.json()
        access_token: str = token_response["access_token"]

        logger.debug("Successfully obtained Discord access token")
        return access_token

    async def get_current_user(self, access_token: str) -> DiscordUser:
        """
        Get current user info from Discord.

        Args:
            access_token: Discord OAuth access token

        Returns:
            Discord user information
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        logger.debug("Fetching Discord user info")
        response = await self._client.get(f"{self.DISCORD_API_BASE}/users/@me", headers=headers)
        response.raise_for_status()

        user_data = response.json()
        user = DiscordUser(
            id=user_data["id"],
            username=user_data["username"],
            discriminator=user_data["discriminator"],
            avatar=user_data.get("avatar"),
        )

        logger.debug(f"Retrieved Discord user: {user.username}#{user.discriminator}")
        return user

    async def get_guild_member(
        self, access_token: str, user_id: str
    ) -> Optional[DiscordGuildMember]:
        """
        Get guild member information including roles.

        Args:
            access_token: Discord OAuth access token
            user_id: Discord user ID

        Returns:
            Guild member info or None if not a member
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        logger.debug(f"Checking guild membership for user {user_id}")
        try:
            response = await self._client.get(
                f"{self.DISCORD_API_BASE}/users/@me/guilds/{self.config.discord_guild_id}/member",
                headers=headers,
            )
            response.raise_for_status()

            member_data = response.json()

            # Get user info from member data
            user_info = member_data["user"]
            user = DiscordUser(
                id=user_info["id"],
                username=user_info["username"],
                discriminator=user_info["discriminator"],
                avatar=user_info.get("avatar"),
            )

            member = DiscordGuildMember(
                user=user, roles=member_data["roles"], nick=member_data.get("nick")
            )

            logger.debug(f"User {user.username} is a guild member with {len(member.roles)} roles")
            return member

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(
                    f"User {user_id} is not a member of guild {self.config.discord_guild_id}"
                )
                return None
            raise

    async def get_guild_roles(self) -> Dict[str, str]:
        """
        Get guild roles mapping (role_id -> role_name).

        Note: This requires a bot token, not user OAuth token.
        For now, we'll use the role name directly from config.

        Returns:
            Dict mapping role IDs to role names
        """
        # TODO: If we need dynamic role lookup, we'd need a bot token
        # For now, we'll check role names in has_jailbreak_role
        return {}

    async def has_jailbreak_role(self, access_token: str, user_id: str) -> bool:
        """
        Check if user has the jailbreak role in the guild.

        Args:
            access_token: Discord OAuth access token
            user_id: Discord user ID

        Returns:
            True if user has jailbreak role
        """
        member = await self.get_guild_member(access_token, user_id)
        if not member:
            logger.debug(f"User {user_id} is not a guild member")
            return False

        # For now, we need to check role names via a separate API call
        # or use a bot token to get role details
        # TODO: Implement proper role checking once we have bot token setup

        # Temporary: Log the roles for debugging
        logger.info(f"User {member.user.username} has roles: {member.roles}")

        # For development, we can return True if user is a guild member
        # In production, this needs proper role verification
        return len(member.roles) > 0  # Placeholder - needs proper implementation

    async def verify_jailbreak_permission(
        self, access_token: str
    ) -> tuple[bool, Optional[DiscordUser]]:
        """
        Verify user has jailbreak permission.

        Args:
            access_token: Discord OAuth access token

        Returns:
            Tuple of (has_permission, user_info)
        """
        try:
            # Get user info
            user = await self.get_current_user(access_token)

            # Check if user has jailbreak role
            has_permission = await self.has_jailbreak_role(access_token, user.id)

            logger.info(f"Jailbreak permission check for {user.username}: {has_permission}")
            return has_permission, user

        except Exception as e:
            logger.error(f"Failed to verify jailbreak permission: {e}")
            return False, None
