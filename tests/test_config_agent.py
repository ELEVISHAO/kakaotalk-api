"""Tests for HTTP agent settings loading."""
import pytest

from kakao_mcp import config


def test_load_settings_requires_api_key(monkeypatch):
    monkeypatch.delenv("KAKAO_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("KAKAO_AGENT_HOST", "127.0.0.1")
    with pytest.raises(RuntimeError, match="KAKAO_AGENT_API_KEY"):
        config.load_agent_settings()


def test_non_loopback_requires_allow_ips(monkeypatch):
    monkeypatch.setenv("KAKAO_AGENT_API_KEY", "secret")
    monkeypatch.setenv("KAKAO_AGENT_HOST", "0.0.0.0")
    monkeypatch.delenv("KAKAO_AGENT_ALLOW_IPS", raising=False)
    with pytest.raises(RuntimeError, match="KAKAO_AGENT_ALLOW_IPS"):
        config.load_agent_settings()


def test_loopback_allow_ips_optional(monkeypatch):
    monkeypatch.setenv("KAKAO_AGENT_API_KEY", "secret")
    monkeypatch.setenv("KAKAO_AGENT_HOST", "127.0.0.1")
    monkeypatch.delenv("KAKAO_AGENT_ALLOW_IPS", raising=False)
    s = config.load_agent_settings()
    assert s.api_key == "secret"
    assert s.allow_ips == []
    assert s.port == 8765


def test_normalize_room_title_nfc():
    composed = "한패스"
    # Decomposed form of same Hangul if available; NFC should stabilize comparison
    assert config.normalize_room_title(composed) == composed
