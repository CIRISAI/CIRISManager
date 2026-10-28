"""
Persist an agent's node identity across container recreates.

The agent's embedded ciris-server keeps its node identity - the node key, the
substrate key, their ML-DSA halves and the owner's user seed - in
`/app/identity`. Agent containers were created without a mount there, so the
identity lived in the container's writable layer and every deploy, upgrade or
config-change recreate minted a NEW node. A claim (owner-binding to the node
key) did not survive the next deploy: the owner was bound to a key that no
longer existed, and the replacement node came up unowned.

This module does three things:

- recognises whether a container's binds already include `/app/identity`;
- derives the host directory for it next to the agent's `/app/data` bind;
- prepares that directory on the agent's own host: optionally seeded with the
  old container's `/app/identity` (the migration), owned by the container user
  (1000:1000), mode 0700.

Preparation runs in a one-shot container from the agent's own image, as root,
with only the identity directory mounted. It deliberately does not use
`docker exec` into ciris-nginx: that container does not mount /opt/ciris, so a
write there lands in nginx's own layer and the host never sees it (see
tests/ciris_manager/test_compose_sync_durability.py).

When migrating, it refuses to write into a non-empty host directory. A node identity is the
node; silently replacing one with another is exactly the failure this exists
to stop.
"""

import logging
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

IDENTITY_PATH = "/app/identity"
DATA_PATH = "/app/data"
CONTAINER_UID = "1000:1000"

# Mounted at /target in the helper container. /tmp/identity holds the old
# container's identity when migrating (put there by put_archive before start).
_PREPARE_SCRIPT = (
    "set -e; "
    "if [ -d /tmp/identity ]; then "
    'if [ -n "$(ls -A /target 2>/dev/null)" ]; then '
    'echo "refusing: host identity directory is not empty" >&2; exit 3; fi; '
    "cp -a /tmp/identity/. /target/; fi; "
    f"chown -R {CONTAINER_UID} /target; chmod 700 /target"
)


class IdentityVolumeError(RuntimeError):
    """The identity directory could not be prepared; do not recreate."""


def _container_path(bind: str) -> Optional[str]:
    parts = bind.split(":")
    return parts[1] if len(parts) >= 2 else None


def has_identity_bind(binds: Optional[Iterable[str]]) -> bool:
    """Does this bind list already mount /app/identity?"""
    return any(_container_path(b) == IDENTITY_PATH for b in binds or [])


def identity_host_dir(binds: Optional[Iterable[str]]) -> Optional[str]:
    """Host directory for /app/identity: a sibling of the /app/data bind's source.

    Returns None when there is no /app/data bind to anchor it to.
    """
    for b in binds or []:
        if _container_path(b) == DATA_PATH:
            source = b.split(":")[0].rstrip("/")
            if "/" not in source:
                return None
            return source.rsplit("/", 1)[0] + "/identity"
    return None


def with_identity_bind(binds: Optional[Iterable[str]], host_dir: str) -> List[str]:
    """The bind list with /app/identity added (unchanged if already present)."""
    binds = list(binds or [])
    if has_identity_bind(binds):
        return binds
    return binds + [f"{host_dir}:{IDENTITY_PATH}"]


def read_identity_archive(container) -> Optional[bytes]:
    """Tar of the container's /app/identity, or None if it has none.

    Works on a stopped container. The archive's root entry is `identity/`.
    """
    import docker

    try:
        stream, _ = container.get_archive(IDENTITY_PATH)
    except docker.errors.NotFound:
        return None
    return b"".join(stream)


def prepare_identity_dir(
    docker_client, image: str, host_dir: str, archive: Optional[bytes] = None
) -> None:
    """Create host_dir on the agent's host, seeded from `archive` if given.

    Without an archive this is idempotent: an existing identity is kept and only
    its ownership is (re)asserted. With one, it refuses a non-empty directory.
    Raises IdentityVolumeError on that refusal or any other helper failure.
    """
    import docker

    spec = dict(
        image=image,
        entrypoint=["sh", "-c", _PREPARE_SCRIPT],
        command=[],
        user="root",
        volumes={host_dir: {"bind": "/target", "mode": "rw"}},
        network_mode="none",
        labels={"ai.ciris.manager.helper": "identity-volume"},
    )
    helper = None
    try:
        try:
            helper = docker_client.containers.create(**spec)
        except docker.errors.ImageNotFound:
            # A new agent's image may not be on its host yet (create, unlike run, never pulls).
            docker_client.images.pull(image)
            helper = docker_client.containers.create(**spec)
        if archive is not None and not helper.put_archive("/tmp", archive):
            raise IdentityVolumeError(f"could not stage the old identity for {host_dir}")
        helper.start()
        result = helper.wait(timeout=120)
        code = result.get("StatusCode") if isinstance(result, dict) else result
        if code != 0:
            output = helper.logs()
            text = output.decode(errors="replace") if isinstance(output, bytes) else str(output)
            raise IdentityVolumeError(f"preparing {host_dir} failed (exit {code}): {text.strip()}")
    except IdentityVolumeError:
        raise
    except Exception as e:
        raise IdentityVolumeError(f"preparing {host_dir} failed: {e}") from e
    finally:
        if helper is not None:
            try:
                helper.remove(force=True)
            except Exception as e:
                logger.warning(f"Could not remove identity helper container: {e}")

    logger.info(
        f"Prepared agent identity directory {host_dir} "
        f"({'migrated from the old container' if archive else 'empty'})"
    )
