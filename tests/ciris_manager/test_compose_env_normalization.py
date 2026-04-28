"""Regression tests for normalize_compose_env.

Background: production datum agent was perpetually upgraded with a stale
`OPENAI_MODEL_NAME=google/gemma-4-31B-it` (a non-existent Together model) even
after the on-disk `.env` was corrected. Root cause: the `regenerate_agent_compose`
path called `service_config["environment"].get(...)` assuming dict, but Docker
Compose `environment:` accepts BOTH dict-form `{KEY: value}` AND list-form
`["KEY=value"]`. Docker SDK's `Config.Env` always returns the list form. When
list-form input reached the regen path, `.get()` raised
`'list' object has no attribute 'get'`, the orchestrator caught it at
`orchestrator.py:3584` ("using old env"), and re-anchored the stale model name
into the next container — every redeploy.
"""

import pytest

from ciris_manager.compose_generator import normalize_compose_env


def test_dict_passthrough():
    """Dict input returns equivalent dict (with str-coerced values)."""
    env = {"FOO": "bar", "PORT": "8080"}
    assert normalize_compose_env(env) == {"FOO": "bar", "PORT": "8080"}


def test_dict_coerces_non_string_values():
    """Compose YAML happily yields ints/bools/None — must round-trip as strings."""
    env = {"PORT": 8080, "DEBUG": True, "EMPTY": None}
    out = normalize_compose_env(env)
    assert out == {"PORT": "8080", "DEBUG": "True", "EMPTY": ""}


def test_list_form_parses_to_dict():
    """The actual production failure mode: Docker SDK Config.Env list."""
    env = [
        "OPENAI_MODEL_NAME=google/gemma-4-31B-it",
        "OPENAI_API_BASE=https://api.together.xyz/v1/",
        "CIRIS_AGENT_ID=datum",
    ]
    out = normalize_compose_env(env)
    assert out == {
        "OPENAI_MODEL_NAME": "google/gemma-4-31B-it",
        "OPENAI_API_BASE": "https://api.together.xyz/v1/",
        "CIRIS_AGENT_ID": "datum",
    }
    # The actual call that used to crash:
    assert out.get("CIRIS_ADAPTER", "") == ""
    assert "discord" in (out.get("OPENAI_API_BASE", "") + ",discord").split(",")


def test_list_form_handles_values_containing_equals():
    """API keys and tokens often contain `=` — only split on the FIRST one."""
    env = ["TOKEN=abc=def=ghi", "URL=https://x.y/z?k=v"]
    out = normalize_compose_env(env)
    assert out == {"TOKEN": "abc=def=ghi", "URL": "https://x.y/z?k=v"}


def test_list_form_bare_key_yields_empty_string():
    """Compose passes bare `KEY` through from host env; no host => empty."""
    out = normalize_compose_env(["BARE_KEY", "WITH_VAL=hello"])
    assert out == {"BARE_KEY": "", "WITH_VAL": "hello"}


def test_list_form_skips_non_string_items():
    """Defensive: malformed YAML won't crash the regen path."""
    out = normalize_compose_env(["GOOD=yes", 42, None, {"nested": "bad"}])
    assert out == {"GOOD": "yes"}


def test_none_returns_empty_dict():
    """Missing `environment:` field is common and must be safe."""
    assert normalize_compose_env(None) == {}


def test_empty_dict_returns_empty_dict():
    assert normalize_compose_env({}) == {}


def test_empty_list_returns_empty_dict():
    assert normalize_compose_env([]) == {}


def test_unsupported_type_raises_clearly():
    """If something truly weird shows up, fail loud rather than silently."""
    with pytest.raises(TypeError, match="Unsupported environment type"):
        normalize_compose_env("FOO=bar")  # raw string is not valid Compose env


def test_normalized_output_is_callsite_compatible():
    """The downstream call sites in manager.py:699+ all do current_env.get(...).
    Verify both input forms produce something those calls work on."""
    list_form = ["CIRIS_ADAPTER=api,discord", "CIRIS_MOCK_LLM=true"]
    dict_form = {"CIRIS_ADAPTER": "api,discord", "CIRIS_MOCK_LLM": "true"}

    for env in (list_form, dict_form):
        normalized = normalize_compose_env(env)
        assert "discord" in normalized.get("CIRIS_ADAPTER", "").split(",")
        assert normalized.get("CIRIS_MOCK_LLM") == "true"
