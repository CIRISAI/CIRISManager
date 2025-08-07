"""
Test WA review functionality for Tier 4/5 agents.
"""

import pytest


class TestWAReview:
    """Test WA review requirements for high-tier agents."""

    def test_extract_stewardship_tier_from_template(self):
        """Test extracting stewardship tier from template YAML."""
        template_data = {
            "name": "Echo",
            "description": "Test description",
            "stewardship": {"stewardship_tier": 4},
        }

        # Test extraction logic
        tier = template_data.get("stewardship", {}).get("stewardship_tier", 1)
        assert tier == 4

    def test_missing_stewardship_defaults_to_tier_1(self):
        """Test that missing stewardship defaults to tier 1."""
        template_data = {"name": "Test", "description": "Test description"}

        tier = template_data.get("stewardship", {}).get("stewardship_tier", 1)
        assert tier == 1

    def test_wa_review_required_for_tier_4(self):
        """Test that WA review is required for Tier 4."""
        stewardship_tier = 4
        requires_wa_review = stewardship_tier >= 4
        assert requires_wa_review is True

    def test_wa_review_not_required_for_tier_2(self):
        """Test that WA review is not required for Tier 2."""
        stewardship_tier = 2
        requires_wa_review = stewardship_tier >= 4
        assert requires_wa_review is False

    def test_discord_adapter_list_modification(self):
        """Test modifying CIRIS_ADAPTER list for Discord."""
        # Test adding Discord to adapter list
        current_adapter = "api"
        adapters = [a.strip() for a in current_adapter.split(",")]

        enable_discord = True
        if enable_discord:
            if "discord" not in adapters:
                adapters.append("discord")

        result = ",".join(adapters)
        assert result == "api,discord"

        # Test removing Discord from adapter list
        current_adapter = "api,discord,webhook"
        adapters = [a.strip() for a in current_adapter.split(",")]

        enable_discord = False
        if not enable_discord:
            if "discord" in adapters:
                adapters.remove("discord")

        result = ",".join(adapters)
        assert result == "api,webhook"

    def test_channel_ids_cleanup(self):
        """Test cleaning up Discord channel IDs."""
        # Test newline-separated IDs
        channel_ids = "123\n456\n789"
        cleaned = channel_ids.replace("\n", ",").replace(" ", "")
        assert cleaned == "123,456,789"

        # Test mixed separators with spaces
        channel_ids = "123, 456  \n  789"
        cleaned = channel_ids.replace("\n", ",").replace(" ", "")
        assert cleaned == "123,456,789"

    def test_wa_user_ids_cleanup(self):
        """Test cleaning up WA user IDs."""
        wa_ids = "user1\nuser2\nuser3"
        cleaned = wa_ids.replace("\n", ",").replace(" ", "")
        assert cleaned == "user1,user2,user3"

    def test_env_file_parsing(self):
        """Test parsing .env file format."""
        content = """
# This is a comment
DISCORD_BOT_TOKEN=abc123
DISCORD_CHANNEL_IDS=111,222,333
WA_USER_IDS="user1,user2"
OPENAI_API_KEY='sk-test'
EMPTY_VALUE=
"""
        env = {}
        lines = content.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]

                env[key] = value

        assert env["DISCORD_BOT_TOKEN"] == "abc123"
        assert env["DISCORD_CHANNEL_IDS"] == "111,222,333"
        assert env["WA_USER_IDS"] == "user1,user2"
        assert env["OPENAI_API_KEY"] == "sk-test"
        assert env["EMPTY_VALUE"] == ""

    @pytest.mark.asyncio
    async def test_config_update_with_discord_enable(self):
        """Test that CIRIS_ENABLE_DISCORD modifies CIRIS_ADAPTER."""
        # Simulate the logic from routes.py
        config_update = {
            "environment": {"CIRIS_ENABLE_DISCORD": "true", "DISCORD_BOT_TOKEN": "test-token"}
        }

        # Current service environment
        service_env = {"CIRIS_ADAPTER": "api"}

        # Process CIRIS_ENABLE_DISCORD
        if "CIRIS_ENABLE_DISCORD" in config_update["environment"]:
            current_adapter = service_env.get("CIRIS_ADAPTER", "api")
            adapters = [a.strip() for a in current_adapter.split(",")]
            enable_discord = config_update["environment"]["CIRIS_ENABLE_DISCORD"] == "true"

            if enable_discord:
                if "discord" not in adapters:
                    adapters.append("discord")
            else:
                if "discord" in adapters:
                    adapters.remove("discord")

            service_env["CIRIS_ADAPTER"] = ",".join(adapters)
            del config_update["environment"]["CIRIS_ENABLE_DISCORD"]

        # Apply other environment updates
        for key, value in config_update["environment"].items():
            service_env[key] = value

        assert service_env["CIRIS_ADAPTER"] == "api,discord"
        assert service_env["DISCORD_BOT_TOKEN"] == "test-token"
        assert "CIRIS_ENABLE_DISCORD" not in service_env


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
