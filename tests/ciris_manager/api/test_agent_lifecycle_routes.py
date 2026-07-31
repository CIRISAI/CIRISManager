"""Tests for agent lifecycle route resolution.

Both behaviours here were found on 2026-07-30 while trying to recover the
scout2 agent, which had been down for four weeks. Every recovery attempt
returned HTTP 200 "Agent is starting" and did nothing at all:

1. `agent_id` is not unique. The same agent runs as multiple occurrences across
   servers, and the routes took the first match, so a request aimed at the dead
   scout2 instance was serviced by the healthy scout1 one.
2. Even when correctly targeted, `start_agent` checked
   `Path(registry_agent.compose_file).exists()` on the MANAGER's filesystem.
   For a remote agent that file lives on the agent's host, so the check always
   failed - and with no `else` branch, control fell through to the success
   return without touching the container.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ciris_manager.api.routes.agents import _resolve_unique_agent


def _agent(agent_id, server_id, occurrence_id, container_name=None):
    return SimpleNamespace(
        agent_id=agent_id,
        server_id=server_id,
        occurrence_id=occurrence_id,
        container_name=container_name or f"ciris-{agent_id}",
    )


SCOUT1 = _agent("scout-remote-test-dahrb9", "scout1", "default")
SCOUT2 = _agent("scout-remote-test-dahrb9", "scout2", "002", "ciris-scout-remote-test-dahrb9-002")
DATUM = _agent("datum", "main", None)


class TestResolveUniqueAgent:
    def test_unique_agent_resolves(self):
        assert _resolve_unique_agent([DATUM, SCOUT1], "datum") is DATUM

    def test_missing_agent_is_404(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_unique_agent([DATUM], "nope")
        assert exc.value.status_code == 404

    def test_ambiguous_agent_id_is_409_not_a_silent_guess(self):
        """The scout2 bug: two instances share an agent_id.

        Returning either one is worse than failing - the caller believes the
        instance they named was acted on.
        """
        with pytest.raises(HTTPException) as exc:
            _resolve_unique_agent([SCOUT1, SCOUT2], "scout-remote-test-dahrb9")
        assert exc.value.status_code == 409
        detail = exc.value.detail
        # The error must tell the operator how to disambiguate.
        assert "scout1" in detail and "scout2" in detail
        assert "server_id" in detail

    def test_server_id_disambiguates(self):
        got = _resolve_unique_agent(
            [SCOUT1, SCOUT2], "scout-remote-test-dahrb9", server_id="scout2"
        )
        assert got is SCOUT2

    def test_occurrence_id_disambiguates(self):
        got = _resolve_unique_agent(
            [SCOUT1, SCOUT2], "scout-remote-test-dahrb9", occurrence_id="002"
        )
        assert got is SCOUT2

    def test_both_selectors_together(self):
        got = _resolve_unique_agent(
            [SCOUT1, SCOUT2],
            "scout-remote-test-dahrb9",
            occurrence_id="default",
            server_id="scout1",
        )
        assert got is SCOUT1

    def test_selector_matching_nothing_is_404_not_a_fallback(self):
        """A selector that matches nothing must not fall back to another instance."""
        with pytest.raises(HTTPException) as exc:
            _resolve_unique_agent([SCOUT1, SCOUT2], "scout-remote-test-dahrb9", server_id="scout99")
        assert exc.value.status_code == 404
