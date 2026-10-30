"""OAuth returns on an API-only host are forwarded to the web client's origin.

The agent accepts only a same-origin path as an OAuth return (an absolute
cross-origin URL is refused as an open redirect). A web client on another
origin (scout.ciris.ai in front of scoutapilb.ciris.ai) therefore sends a
path, the browser lands on the API host, and the API host's nginx forwards it.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from ciris_manager.config.settings import ServerConfig
from ciris_manager.nginx_manager import NginxManager


def _remote(web_client_origin=None) -> str:
    with tempfile.TemporaryDirectory() as d:
        nm = NginxManager(
            config_dir=d,
            hostname="scoutapilb.ciris.ai",
            web_client_origin=web_client_origin,
        )
        return nm.generate_config([])


def test_forwards_oauth_returns_with_the_query():
    config = _remote("https://scout.ciris.ai")
    assert "location = /oauth-complete.html {" in config
    assert "location ^~ /oauth/ {" in config
    assert config.count("return 302 https://scout.ciris.ai$request_uri;") == 2


def test_forwards_are_declared_before_the_api_only_catch_all():
    config = _remote("https://scout.ciris.ai")
    assert config.index("location = /oauth-complete.html") < config.index(
        'return 404 "Agent server - API only'
    )


def test_no_forward_without_an_origin():
    config = _remote(None)
    assert "/oauth-complete.html" not in config
    assert "location ^~ /oauth/" not in config


def test_main_server_never_forwards():
    with tempfile.TemporaryDirectory() as d:
        nm = NginxManager(
            config_dir=d, hostname="agents.ciris.ai", web_client_origin="https://scout.ciris.ai"
        )
        assert "return 302 https://scout.ciris.ai" not in nm.generate_config([])


@pytest.mark.parametrize(
    "bad",
    [
        "http://scout.ciris.ai",
        "https://scout.ciris.ai/path",
        "https://scout.ciris.ai?x=1",
        "https://scout.ciris.ai#f",
        "https://user@scout.ciris.ai",
        "https://scout.ciris.ai;return",
        "scout.ciris.ai",
    ],
)
def test_origin_must_be_a_bare_https_origin(bad):
    with pytest.raises(ValidationError):
        ServerConfig(server_id="scout1", hostname="scoutapilb.ciris.ai", web_client_origin=bad)


def test_trailing_slash_is_normalised():
    s = ServerConfig(
        server_id="scout1",
        hostname="scoutapilb.ciris.ai",
        web_client_origin="https://scout.ciris.ai/",
    )
    assert s.web_client_origin == "https://scout.ciris.ai"


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx not installed")
def test_generated_config_parses(tmp_path: Path):
    conf = tmp_path / "nginx.conf"
    conf.write_text(_remote("https://scout.ciris.ai"))
    r = subprocess.run(["nginx", "-t", "-c", str(conf)], capture_output=True, text=True)
    assert "syntax is ok" in r.stderr or "certificate" in r.stderr, r.stderr
