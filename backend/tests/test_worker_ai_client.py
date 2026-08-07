from __future__ import annotations

import types

from server_api.services.ai_client import SharedAiClient
from server_api.worker import _build_shared_ai_client


def test_disabled_flag_returns_none():
    """ai_decision_enabled=False -> _build_shared_ai_client returns None."""
    config = types.SimpleNamespace(ai_decision_enabled=False)
    result = _build_shared_ai_client(config, saved_ai=None)
    assert result is None


def test_saved_ai_produces_client_with_matching_base_url():
    """ai_decision_enabled=True + saved_ai with full fields -> SharedAiClient with matching base_url."""
    saved_ai = types.SimpleNamespace(
        provider="openai_compatible",
        base_url="https://saved.example.com",
        model="saved-model",
        api_key="sk-saved-key-12345",
    )
    config = types.SimpleNamespace(ai_decision_enabled=True)
    result = _build_shared_ai_client(config, saved_ai=saved_ai)
    assert isinstance(result, SharedAiClient)
    assert result.base_url == "https://saved.example.com"


def test_settings_fallback_produces_client_with_real_key():
    """ai_decision_enabled=True, saved_ai=None, config with complete non-placeholder fields -> non-None SharedAiClient."""
    config = types.SimpleNamespace(
        ai_decision_enabled=True,
        ai_provider="openai_compatible",
        ai_base_url="https://settings.example.com",
        ai_model="settings-model",
        ai_api_key="sk-test-1234567890",
        ai_timeout_seconds=30,
        ai_max_retries=3,
        ai_retry_backoff_seconds=2.0,
    )
    result = _build_shared_ai_client(config, saved_ai=None)
    assert result is not None
    assert isinstance(result, SharedAiClient)
    assert result.base_url == "https://settings.example.com"


def test_settings_fallback_empty_base_url_returns_none():
    """ai_decision_enabled=True, saved_ai=None, ai_base_url empty -> None."""
    config = types.SimpleNamespace(
        ai_decision_enabled=True,
        ai_provider="openai_compatible",
        ai_base_url="",
        ai_model="some-model",
        ai_api_key="sk-test-key-123",
        ai_timeout_seconds=30,
        ai_max_retries=3,
        ai_retry_backoff_seconds=2.0,
    )
    result = _build_shared_ai_client(config, saved_ai=None)
    assert result is None
