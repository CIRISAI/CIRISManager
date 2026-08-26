"""The canonical container name, and the endpoint we hand operators.

Both have been wrong in production. The watchdog filtered on a `ciris-agent-`
prefix that has never existed and matched zero containers while reporting
itself healthy; the API reported that same non-existent name back through
`ciris-manager-client agent get`, so anyone who copied it into `docker logs`
got "no such container". Non-default occurrences were dropped entirely, so
both scouts collapsed onto a single name.
"""

import pytest
from unittest.mock import Mock

from ciris_manager.utils.naming import container_name


class TestContainerName:
    def test_default_occurrence_has_no_suffix(self):
        assert container_name("datum") == "ciris-datum"

    def test_explicit_default_is_still_unsuffixed(self):
        assert container_name("datum", "default") == "ciris-datum"

    def test_non_default_occurrence_is_suffixed(self):
        assert (
            container_name("scout-remote-test-dahrb9", "002")
            == "ciris-scout-remote-test-dahrb9-002"
        )

    def test_two_occurrences_of_one_agent_do_not_collide(self):
        """The bug that made both scouts resolve to one container."""
        assert container_name("scout-remote-test-dahrb9") != container_name(
            "scout-remote-test-dahrb9", "002"
        )

    def test_never_emits_the_ciris_agent_prefix(self):
        """`ciris-agent-` matches nothing on a real host. Verified via docker ps."""
        for occurrence in (None, "default", "002"):
            assert not container_name("datum", occurrence).startswith("ciris-agent-")

    @pytest.mark.parametrize(
        "agent_id,occurrence,expected",
        [
            ("datum", None, "ciris-datum"),
            ("echo-core-jm2jy2", None, "ciris-echo-core-jm2jy2"),
            ("scout-remote-test-dahrb9", None, "ciris-scout-remote-test-dahrb9"),
            ("scout-remote-test-dahrb9", "002", "ciris-scout-remote-test-dahrb9-002"),
        ],
    )
    def test_matches_names_observed_in_production(self, agent_id, occurrence, expected):
        """These four are what `docker ps` shows across the fleet today."""
        assert container_name(agent_id, occurrence) == expected


class TestAgentEndpoint:
    """A remote agent is not on localhost, and saying so is worse than useless -
    the port may well be occupied locally by something unrelated."""

    @staticmethod
    def _manager(is_local, vpc_ip):
        server = Mock(is_local=is_local, vpc_ip=vpc_ip)
        manager = Mock()
        manager.docker_client.get_server_config.return_value = server
        return manager

    def test_remote_agent_uses_vpc_ip(self):
        from ciris_manager.api.routes.agents import _agent_endpoint

        agent = Mock(port=8002, server_id="scout2")
        manager = self._manager(is_local=False, vpc_ip="10.10.0.6")
        assert _agent_endpoint(manager, agent) == "http://10.10.0.6:8002"

    def test_local_agent_uses_localhost(self):
        from ciris_manager.api.routes.agents import _agent_endpoint

        agent = Mock(port=8001, server_id="main")
        manager = self._manager(is_local=True, vpc_ip=None)
        assert _agent_endpoint(manager, agent) == "http://localhost:8001"

    def test_unknown_server_still_answers(self):
        """An unresolvable server_id must not turn a GET into a 500."""
        from ciris_manager.api.routes.agents import _agent_endpoint

        agent = Mock(port=8003, server_id="nope")
        manager = Mock()
        manager.docker_client.get_server_config.side_effect = ValueError("unknown server")
        assert _agent_endpoint(manager, agent) == "http://localhost:8003"
