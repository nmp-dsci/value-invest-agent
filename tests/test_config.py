"""Importing the package and building settings must never need a key or token."""

import os

from value_invest.config import settings


def test_settings_boot_keyless(monkeypatch):
    settings.cache_clear()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = settings()
    assert s.billing in {"subscription", "api"}
    assert s.sample_per_year in (10, 20)  # 10 by default; 20 once .env carries the M2 window
    assert "ANTHROPIC_API_KEY" not in os.environ or os.environ["ANTHROPIC_API_KEY"] == ""
    settings.cache_clear()


def test_llm_module_imports_without_sdk_call():
    from value_invest import llm

    assert llm.resolve_model("sonnet") == "claude-sonnet-5"
    assert llm.resolve_model("claude-opus-5") == "claude-opus-5"


def test_subscription_env_blanks_per_token_billing(monkeypatch):
    from value_invest import llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    env = llm.subscription_env()
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["CLAUDECODE"] == ""
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_require_live_refuses_key_with_subscription(monkeypatch):
    from value_invest import llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    try:
        llm.require_live()
    except llm.BillingError:
        return
    raise AssertionError("expected BillingError")
