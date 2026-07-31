"""Tests for occurrence handling: compose naming and adoption.

Occurrences of the same agent share `<agents_dir>/<agent_id>/`, so the compose
filename has to carry the occurrence id. `create_agent` hard-coded
"docker-compose.yml" regardless, meaning a second occurrence silently
overwrote the first one's compose - which is why scout2's registry entry had
to be hand-edited to `docker-compose-002.yml`.

Separately, scout2 was created directly through the Docker API and so had no
compose file anywhere. Every config change failed with "Could not fetch compose
file from remote server", because the manager had nothing to regenerate from.
The running container is the authoritative record of an agent's environment and
is always reachable, so it is now the adoption seed.
"""

from unittest.mock import MagicMock

import pytest

from ciris_manager.manager import CIRISManager


class TestComposeFilename:
    def test_default_occurrence_uses_plain_name(self):
        assert CIRISManager.compose_filename(None) == "docker-compose.yml"
        assert CIRISManager.compose_filename("default") == "docker-compose.yml"

    def test_non_default_occurrence_is_qualified(self):
        assert CIRISManager.compose_filename("002") == "docker-compose-002.yml"
        assert CIRISManager.compose_filename("003") == "docker-compose-003.yml"

    def test_occurrences_do_not_collide(self):
        """The whole point: two occurrences must not share a filename."""
        assert CIRISManager.compose_filename("default") != CIRISManager.compose_filename("002")

    def test_matches_scout2_registry_entry(self):
        """Convention must match what production already records for scout2."""
        assert CIRISManager.compose_filename("002") == "docker-compose-002.yml"


class TestAdoptFromRunningContainer:
    def _manager(self, container):
        mgr = CIRISManager.__new__(CIRISManager)
        client = MagicMock()
        if container is None:
            import docker.errors

            client.containers.get.side_effect = docker.errors.NotFound("nope")
        else:
            client.containers.get.return_value = container
        docker_client = MagicMock()
        docker_client.get_client.return_value = client
        mgr.docker_client = docker_client
        return mgr, client

    @pytest.mark.asyncio
    async def test_adopts_environment_from_container(self):
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": [
                    "CIRIS_AGENT_ID=scout-remote-test-dahrb9",
                    "AGENT_OCCURRENCE_ID=002",
                    "OPENAI_API_BASE=https://api.groq.com/openai/v1",
                    "MALFORMED_NO_EQUALS",
                ]
            }
        }
        mgr, client = self._manager(container)

        result = await mgr._compose_from_running_container(
            "scout-remote-test-dahrb9", "002", "scout2"
        )

        env = result["services"]["scout-remote-test-dahrb9"]["environment"]
        assert env["AGENT_OCCURRENCE_ID"] == "002"
        assert env["OPENAI_API_BASE"] == "https://api.groq.com/openai/v1"
        # A value-less entry must not crash or produce a bogus key/value.
        assert "MALFORMED_NO_EQUALS" not in env

    @pytest.mark.asyncio
    async def test_uses_occurrence_qualified_container_name(self):
        container = MagicMock()
        container.attrs = {"Config": {"Env": ["A=1"]}}
        mgr, client = self._manager(container)

        await mgr._compose_from_running_container("scout-remote-test-dahrb9", "002", "scout2")
        client.containers.get.assert_called_once_with("ciris-scout-remote-test-dahrb9-002")

    @pytest.mark.asyncio
    async def test_default_occurrence_uses_plain_container_name(self):
        container = MagicMock()
        container.attrs = {"Config": {"Env": ["A=1"]}}
        mgr, client = self._manager(container)

        await mgr._compose_from_running_container("scout-remote-test-dahrb9", "default", "scout1")
        client.containers.get.assert_called_once_with("ciris-scout-remote-test-dahrb9")

    @pytest.mark.asyncio
    async def test_missing_container_returns_none(self):
        mgr, _ = self._manager(None)
        assert await mgr._compose_from_running_container("gone", None, "main") is None

    @pytest.mark.asyncio
    async def test_container_with_no_env_returns_none(self):
        container = MagicMock()
        container.attrs = {"Config": {"Env": []}}
        mgr, _ = self._manager(container)
        assert await mgr._compose_from_running_container("x", None, "main") is None
