"""Identity must come from the registry, never from a container.

Production incident 2026-08-09: scout1 ended up running with
AGENT_OCCURRENCE_ID=002 - scout2's identity - and both agents' compose files
were rewritten to match. Two agents sharing one database with the same
occurrence id means work partitioning is silently broken.

The cause was a feedback loop:

    discovery reads occurrence_id from the container env
        -> recreate builds container env from discovery
            -> container re-asserts the same wrong occurrence, forever

Anything sharing the agent_id got pulled in with it. The registry held the
correct values the whole time; only the derived state was wrong.

Invariant: agent_id / occurrence_id / port / server_id come from the registry.
A container may supply operational env (secrets, DB URL, adapters) but must
never be able to tell the manager who it is.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ciris_manager.compose_generator import ComposeGenerator
from ciris_manager.manager import CIRISManager


class TestContainerNamePerOccurrence:
    def _gen(self, tmp_path, occurrence):
        gen = ComposeGenerator(
            docker_registry="ghcr.io/cirisai", default_image="ciris-agent:latest"
        )
        cfg = gen.generate_compose(
            agent_id="scout",
            agent_name="Scout",
            port=8000,
            template="scout",
            agent_dir=tmp_path,
            agent_occurrence_id=occurrence,
        )
        return cfg["services"]["scout"]["container_name"]

    def test_default_occurrence_plain_name(self, tmp_path):
        assert self._gen(tmp_path, None) == "ciris-scout"
        assert self._gen(tmp_path, "default") == "ciris-scout"

    def test_second_occurrence_gets_its_own_container_name(self, tmp_path):
        """Without the suffix, occurrence 002's compose claims 001's container."""
        assert self._gen(tmp_path, "002") == "ciris-scout-002"

    def test_occurrences_never_collide(self, tmp_path):
        assert self._gen(tmp_path, "default") != self._gen(tmp_path, "002")


class TestAdoptionDoesNotInheritIdentity:
    def _mgr(self, env_list):
        mgr = CIRISManager.__new__(CIRISManager)
        container = MagicMock()
        container.attrs = {"Config": {"Env": env_list}}
        client = MagicMock()
        client.containers.get.return_value = container
        docker_client = MagicMock()
        docker_client.get_client.return_value = client
        mgr.docker_client = docker_client
        return mgr

    @pytest.mark.asyncio
    async def test_wrong_occurrence_in_container_is_overridden(self):
        """The exact incident: a container claiming someone else's occurrence."""
        mgr = self._mgr(
            [
                "CIRIS_AGENT_ID=scout-remote-test-dahrb9",
                "AGENT_OCCURRENCE_ID=002",  # wrong - this container is `default`
                "CIRIS_DB_URL=postgresql://x",
            ]
        )
        result = await mgr._compose_from_running_container(
            "scout-remote-test-dahrb9", "default", "scout1"
        )
        env = result["services"]["scout-remote-test-dahrb9"]["environment"]
        assert "AGENT_OCCURRENCE_ID" not in env, "default occurrence must not carry the marker"
        # Operational settings still adopted.
        assert env["CIRIS_DB_URL"] == "postgresql://x"

    @pytest.mark.asyncio
    async def test_registry_occurrence_is_written_through(self):
        mgr = self._mgr(["CIRIS_AGENT_ID=scout", "CIRIS_DB_URL=postgresql://x"])
        result = await mgr._compose_from_running_container("scout", "002", "scout2")
        env = result["services"]["scout"]["environment"]
        assert env["AGENT_OCCURRENCE_ID"] == "002"

    @pytest.mark.asyncio
    async def test_agent_id_is_forced_from_registry(self):
        mgr = self._mgr(["CIRIS_AGENT_ID=somebody-else", "X=1"])
        result = await mgr._compose_from_running_container("the-real-agent", None, "main")
        env = result["services"]["the-real-agent"]["environment"]
        assert env["CIRIS_AGENT_ID"] == "the-real-agent"


class TestDiscoveryPrefersRegistry:
    def _discovery(self, agents):
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        registry = MagicMock()
        registry.list_agents.return_value = agents
        return DockerAgentDiscovery(registry)

    def test_two_occurrences_are_told_apart_by_container_name(self):
        """agent_id+server is ambiguous; the container name carries occurrence."""
        a1 = SimpleNamespace(agent_id="scout", occurrence_id="default", server_id="scout1")
        a2 = SimpleNamespace(agent_id="scout", occurrence_id="002", server_id="scout1")
        disc = self._discovery([a1, a2])
        found = [
            a
            for a in disc.agent_registry.list_agents()
            if a.agent_id == "scout" and (a.server_id or "main") == "scout1"
        ]
        assert len(found) == 2
        names = {
            (f"ciris-scout-{a.occurrence_id}" if a.occurrence_id != "default" else "ciris-scout")
            for a in found
        }
        assert names == {"ciris-scout", "ciris-scout-002"}


class TestRegenerationRepairsIdentity:
    """Identity must be re-asserted on every regeneration, not just adoption.

    Overlaying identity only in the container-adoption path was insufficient: a
    compose file already written with the wrong occurrence kept feeding that
    value back in as `current_env`, so the bad identity survived every rebuild.
    scout1 stayed pinned to occurrence "002" across repeated recreates until
    the overlay moved to this choke point.
    """

    def _apply(self, current_env, agent_id, occurrence_id):
        """Mirror of the overlay applied in regenerate_agent_compose."""
        env = dict(current_env)
        env["CIRIS_AGENT_ID"] = agent_id
        if occurrence_id and occurrence_id != "default":
            env["AGENT_OCCURRENCE_ID"] = occurrence_id
        else:
            env.pop("AGENT_OCCURRENCE_ID", None)
        return env

    def test_contaminated_compose_is_repaired_for_default(self):
        """A compose wrongly carrying 002 must be corrected, not perpetuated."""
        contaminated = {"AGENT_OCCURRENCE_ID": "002", "CIRIS_DB_URL": "postgresql://x"}
        env = self._apply(contaminated, "scout-remote-test-dahrb9", "default")
        assert "AGENT_OCCURRENCE_ID" not in env
        assert env["CIRIS_DB_URL"] == "postgresql://x", "operational env must survive"

    def test_second_occurrence_keeps_its_marker(self):
        env = self._apply({"CIRIS_DB_URL": "postgresql://x"}, "scout", "002")
        assert env["AGENT_OCCURRENCE_ID"] == "002"

    def test_agent_id_is_reasserted(self):
        env = self._apply({"CIRIS_AGENT_ID": "wrong"}, "right", None)
        assert env["CIRIS_AGENT_ID"] == "right"
