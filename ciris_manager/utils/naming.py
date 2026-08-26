"""Canonical names for the things an agent owns.

These names have been wrong in three separate places already - the watchdog
filtered on a `ciris-agent-` prefix that has never existed in production and
matched zero containers while reporting itself healthy, and the API reported
that same name back to operators. Non-default occurrences were dropped
entirely, so both scouts resolved to one container name.

One definition, used everywhere, so a name can only be wrong once.
"""

from typing import Optional

DEFAULT_OCCURRENCE = "default"


def container_name(agent_id: str, occurrence_id: Optional[str] = None) -> str:
    """The Docker container name for an agent occurrence.

    `ciris-{agent_id}` for the default occurrence, with the occurrence id
    appended otherwise - matching what the compose generator emits and what
    `docker ps` actually shows:

        ciris-datum
        ciris-scout-remote-test-dahrb9
        ciris-scout-remote-test-dahrb9-002

    There is no `ciris-agent-` prefix. Verify against a real host before
    reintroducing one.
    """
    if occurrence_id and occurrence_id != DEFAULT_OCCURRENCE:
        return f"ciris-{agent_id}-{occurrence_id}"
    return f"ciris-{agent_id}"
