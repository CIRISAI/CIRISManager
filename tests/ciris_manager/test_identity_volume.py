"""Tests for persisting an agent's node identity across recreates.

Found 2026-10-21 while test-claiming a production agent offline. The agent's
embedded ciris-server keeps its node identity in /app/identity, and agent
containers did not mount it. Every deploy recreated the container and so
minted a new node; an owner's claim (bound to the old node key) was lost on
the next upgrade, and the agent came up unowned.

The fix has to reach EXISTING agents, not only new ones: a remote recreate
copies the old container's Binds verbatim, so changing the compose generator
alone would never add the mount. The recreate therefore moves the old
container's identity onto a host bind first, and refuses to recreate if it
cannot.
"""

import io
import os
import tarfile
from unittest.mock import MagicMock

import pytest

from ciris_manager.identity_volume import (
    IDENTITY_PATH,
    IdentityVolumeError,
    has_identity_bind,
    identity_host_dir,
    prepare_identity_dir,
    with_identity_bind,
)

PROD_BINDS = [
    "/opt/ciris/agents/datum/data:/app/data:rw",
    "/opt/ciris/agents/datum/data_archive:/app/data_archive:rw",
    "/opt/ciris/agents/datum/logs:/app/logs:rw",
    "/opt/ciris/agents/datum/config:/app/config:rw",
    "/opt/ciris/agents/datum/audit_keys:/app/audit_keys:rw",
    "/opt/ciris/agents/datum/.secrets:/app/.secrets:rw",
    "/home/ciris/shared/oauth:/home/ciris/shared/oauth:ro",
]


# ── bind arithmetic ───────────────────────────────────────────────────────────


def test_prod_binds_have_no_identity_mount():
    assert not has_identity_bind(PROD_BINDS)


def test_identity_dir_sits_beside_data():
    assert identity_host_dir(PROD_BINDS) == "/opt/ciris/agents/datum/identity"


def test_no_data_bind_means_no_anchor():
    assert identity_host_dir(["/x/logs:/app/logs"]) is None
    assert identity_host_dir([]) is None
    assert identity_host_dir(None) is None


def test_with_identity_bind_adds_once():
    binds = with_identity_bind(PROD_BINDS, "/opt/ciris/agents/datum/identity")
    assert binds[-1] == f"/opt/ciris/agents/datum/identity:{IDENTITY_PATH}"
    assert has_identity_bind(binds)
    assert with_identity_bind(binds, "/elsewhere") == binds
    assert not has_identity_bind(PROD_BINDS), "input list must not be mutated"


def test_a_similar_path_is_not_the_identity_mount():
    assert not has_identity_bind(["/a/identity:/app/identity_old", "/b:/app/data/identity"])


def test_generator_mounts_identity(tmp_path):
    from ciris_manager.compose_generator import ComposeGenerator

    gen = ComposeGenerator(docker_registry="ghcr.io/cirisai", default_image="ciris-agent:latest")
    volumes = gen._build_volumes(tmp_path / "datum", "/home/ciris/shared/oauth")
    assert f"{tmp_path / 'datum'}/identity:/app/identity" in volumes


# ── the recreate refuses to mint a new node ───────────────────────────────────


def _orchestrator():
    from ciris_manager.deployment.orchestrator import DeploymentOrchestrator

    return DeploymentOrchestrator.__new__(DeploymentOrchestrator)


def _old_container():
    c = MagicMock()
    c.image.id = "sha256:old"
    c.get_archive.return_value = (iter([b"tar-", b"bytes"]), {})
    return c


def test_recreate_moves_identity_and_adds_bind(monkeypatch):
    calls = {}

    def fake_prepare(client, image, host_dir, archive=None):
        calls.update(image=image, host_dir=host_dir, archive=archive)

    monkeypatch.setattr("ciris_manager.identity_volume.prepare_identity_dir", fake_prepare)
    old = _old_container()
    config = {"volumes": list(PROD_BINDS)}

    assert _orchestrator()._persist_identity_volume(MagicMock(), old, config, "ciris-datum")

    assert calls == {
        "image": "sha256:old",
        "host_dir": "/opt/ciris/agents/datum/identity",
        "archive": b"tar-bytes",
    }
    assert "/opt/ciris/agents/datum/identity:/app/identity" in config["volumes"]
    old.start.assert_not_called()


def test_recreate_aborts_and_restores_old_container_on_failure(monkeypatch):
    def failing_prepare(*a, **k):
        raise IdentityVolumeError("refusing: host identity directory is not empty")

    monkeypatch.setattr("ciris_manager.identity_volume.prepare_identity_dir", failing_prepare)
    old = _old_container()
    config = {"volumes": list(PROD_BINDS)}

    assert not _orchestrator()._persist_identity_volume(MagicMock(), old, config, "ciris-datum")

    old.start.assert_called_once()
    assert config["volumes"] == PROD_BINDS, "must not mount a directory it failed to prepare"


def test_already_mounted_is_left_alone(monkeypatch):
    monkeypatch.setattr(
        "ciris_manager.identity_volume.prepare_identity_dir",
        lambda *a, **k: pytest.fail("must not touch an identity that already persists"),
    )
    binds = PROD_BINDS + ["/opt/ciris/agents/datum/identity:/app/identity"]
    config = {"volumes": list(binds)}
    old = _old_container()

    assert _orchestrator()._persist_identity_volume(MagicMock(), old, config, "ciris-datum")
    assert config["volumes"] == binds
    old.get_archive.assert_not_called()


def test_remote_recreate_calls_the_migration_before_removing():
    """Guard the wiring: removing first would destroy the only copy."""
    import inspect

    from ciris_manager.deployment.orchestrator import DeploymentOrchestrator

    src = inspect.getsource(DeploymentOrchestrator._recreate_agent_container)
    migrate = src.index("self._persist_identity_volume(")
    remove = src.index("old_container.remove()")
    assert migrate < remove
    assert src.index("self._persist_local_identity_volume(") < src.index('"up", "-d"')


# ── real Docker: the helper container does what it claims ─────────────────────

IMAGE = "debian:bookworm-slim"


def _docker():
    try:
        import docker

        client = docker.from_env()
        client.images.get(IMAGE)
        return client
    except Exception:
        return None


docker_client = _docker()
needs_docker = pytest.mark.skipif(docker_client is None, reason=f"needs local Docker and {IMAGE}")


@needs_docker
def test_real_migration_round_trip(tmp_path):
    """Seed a container's /app/identity, stop it, migrate, and read it back on the host."""
    from ciris_manager.identity_volume import read_identity_archive

    seed = os.urandom(32)
    old = docker_client.containers.create(IMAGE, command=["true"])
    try:
        # /app does not exist in this image, so the tar carries it from /.
        old.put_archive("/", _app_identity_tar({"node.ed25519.seed": seed, "user/u.seed": b"u"}))
        archive = read_identity_archive(old)
        assert archive is not None

        # The agent dir exists on a real host; only identity/ is new.
        (tmp_path / "agent").mkdir()
        host_dir = tmp_path / "agent" / "identity"
        prepare_identity_dir(docker_client, IMAGE, str(host_dir), archive)

        assert (host_dir / "node.ed25519.seed").read_bytes() == seed
        assert (host_dir / "user" / "u.seed").read_bytes() == b"u"
        st = host_dir.stat()
        assert (st.st_uid, st.st_gid) == (1000, 1000)
        assert oct(st.st_mode & 0o777) == "0o700"

        # A second migration into the now-populated directory must refuse.
        with pytest.raises(IdentityVolumeError, match="not empty"):
            prepare_identity_dir(docker_client, IMAGE, str(host_dir), archive)
        assert (host_dir / "node.ed25519.seed").read_bytes() == seed

        # Without an archive it is idempotent and keeps the identity.
        prepare_identity_dir(docker_client, IMAGE, str(host_dir))
        assert (host_dir / "node.ed25519.seed").read_bytes() == seed
    finally:
        old.remove(force=True)


@needs_docker
def test_real_container_without_identity_yields_none():
    from ciris_manager.identity_volume import read_identity_archive

    c = docker_client.containers.create(IMAGE, command=["true"])
    try:
        assert read_identity_archive(c) is None
    finally:
        c.remove(force=True)


@needs_docker
def test_real_fresh_dir_is_writable_by_the_agent_user(tmp_path):
    (tmp_path / "fresh").mkdir()
    host_dir = tmp_path / "fresh" / "identity"
    prepare_identity_dir(docker_client, IMAGE, str(host_dir))
    out = docker_client.containers.run(
        IMAGE,
        ["sh", "-c", "touch /app/identity/probe && echo ok"],
        user="1000:1000",
        volumes={str(host_dir): {"bind": "/app/identity", "mode": "rw"}},
        remove=True,
    )
    assert out.strip() == b"ok"


def _app_identity_tar(files: dict) -> bytes:
    """Like _identity_tar, rooted at app/identity so it can be put at /."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, mode in (("app", 0o755), ("app/identity", 0o700), ("app/identity/user", 0o700)):
            d = tarfile.TarInfo(name)
            d.type, d.mode, d.uid, d.gid = tarfile.DIRTYPE, mode, 1000, 1000
            tar.addfile(d)
        for name, data in files.items():
            info = tarfile.TarInfo(f"app/identity/{name}")
            info.size, info.mode, info.uid, info.gid = len(data), 0o600, 1000, 1000
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()
