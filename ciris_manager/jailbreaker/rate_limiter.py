"""
Rate limiting for jailbreaker endpoints.
"""

import asyncio
import time
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter with global and per-user limits."""

    def __init__(self, global_limit_seconds: int = 300, user_limit_seconds: int = 3600):
        """
        Initialize rate limiter.

        Args:
            global_limit_seconds: Global cooldown between any resets (default: 5 minutes)
            user_limit_seconds: Per-user cooldown between resets (default: 1 hour)
        """
        self.global_limit_seconds = global_limit_seconds
        self.user_limit_seconds = user_limit_seconds

        # Track last reset timestamps
        self._last_global_reset: Optional[float] = None
        self._user_resets: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, user_id: str) -> tuple[bool, Optional[int]]:
        """
        Check if user can perform a reset.

        Args:
            user_id: Discord user ID

        Returns:
            Tuple of (allowed, next_allowed_timestamp)
        """
        async with self._lock:
            current_time = time.time()

            # Check global rate limit
            if self._last_global_reset is not None:
                time_since_global = current_time - self._last_global_reset
                if time_since_global < self.global_limit_seconds:
                    next_allowed = int(self._last_global_reset + self.global_limit_seconds)
                    logger.debug(
                        f"Global rate limit hit, {self.global_limit_seconds - time_since_global:.1f}s remaining"
                    )
                    return False, next_allowed

            # Check per-user rate limit
            if user_id in self._user_resets:
                time_since_user = current_time - self._user_resets[user_id]
                if time_since_user < self.user_limit_seconds:
                    next_allowed = int(self._user_resets[user_id] + self.user_limit_seconds)
                    logger.debug(
                        f"User {user_id} rate limit hit, {self.user_limit_seconds - time_since_user:.1f}s remaining"
                    )
                    return False, next_allowed

            return True, None

    async def record_reset(self, user_id: str) -> None:
        """
        Record that a reset was performed.

        Args:
            user_id: Discord user ID
        """
        async with self._lock:
            current_time = time.time()
            self._last_global_reset = current_time
            self._user_resets[user_id] = current_time

            logger.info(
                f"Recorded reset for user {user_id} at {datetime.fromtimestamp(current_time)}"
            )

    async def cleanup_old_entries(self) -> None:
        """Clean up old user reset entries to prevent memory bloat."""
        async with self._lock:
            current_time = time.time()
            cutoff_time = current_time - (
                self.user_limit_seconds * 2
            )  # Keep entries for 2x the limit

            old_users = [
                user_id
                for user_id, reset_time in self._user_resets.items()
                if reset_time < cutoff_time
            ]

            for user_id in old_users:
                del self._user_resets[user_id]

            if old_users:
                logger.debug(f"Cleaned up rate limit entries for {len(old_users)} users")

    def get_next_global_reset(self) -> Optional[int]:
        """Get timestamp when next global reset is allowed."""
        if self._last_global_reset is None:
            return None
        return int(self._last_global_reset + self.global_limit_seconds)

    def get_next_user_reset(self, user_id: str) -> Optional[int]:
        """Get timestamp when user can reset again."""
        if user_id not in self._user_resets:
            return None
        return int(self._user_resets[user_id] + self.user_limit_seconds)

    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        current_time = time.time()

        stats = {
            "global_limit_seconds": self.global_limit_seconds,
            "user_limit_seconds": self.user_limit_seconds,
            "tracked_users": len(self._user_resets),
            "last_global_reset": None,
            "seconds_until_next_global": None,
        }

        if self._last_global_reset:
            stats["last_global_reset"] = int(self._last_global_reset)
            time_remaining = self.global_limit_seconds - (current_time - self._last_global_reset)
            stats["seconds_until_next_global"] = max(0, int(time_remaining))

        return stats


def parse_rate_limit_string(limit_str: str) -> int:
    """
    Parse rate limit string like "1/5minutes" or "1/hour" into seconds.

    Args:
        limit_str: Rate limit string (e.g., "1/5minutes", "1/hour")

    Returns:
        Number of seconds for the rate limit period
    """
    try:
        # Handle formats like "1/5minutes", "1/hour", "1/30seconds"
        if "/" not in limit_str:
            raise ValueError("Rate limit must be in format 'count/period'")

        count_str, period_str = limit_str.split("/", 1)
        count = int(count_str)

        if count != 1:
            raise ValueError("Only '1/period' format supported currently")

        period_lower = period_str.lower()

        # Parse time periods
        if period_lower.endswith("seconds") or period_lower.endswith("second"):
            multiplier_str = period_lower.replace("seconds", "").replace("second", "")
            multiplier = int(multiplier_str) if multiplier_str else 1
            return multiplier

        elif period_lower.endswith("minutes") or period_lower.endswith("minute"):
            multiplier_str = period_lower.replace("minutes", "").replace("minute", "")
            multiplier = int(multiplier_str) if multiplier_str else 1
            return multiplier * 60

        elif period_lower.endswith("hours") or period_lower.endswith("hour"):
            multiplier_str = period_lower.replace("hours", "").replace("hour", "")
            multiplier = int(multiplier_str) if multiplier_str else 1
            return multiplier * 3600

        elif period_lower.endswith("days") or period_lower.endswith("day"):
            multiplier_str = period_lower.replace("days", "").replace("day", "")
            multiplier = int(multiplier_str) if multiplier_str else 1
            return multiplier * 86400

        else:
            raise ValueError(f"Unsupported time period: {period_str}")

    except (ValueError, AttributeError) as e:
        logger.error(f"Failed to parse rate limit string '{limit_str}': {e}")
        raise ValueError(f"Invalid rate limit format: {limit_str}")
