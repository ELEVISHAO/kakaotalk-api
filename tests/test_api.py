"""HTTP API tests for auth and core routes."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from kakao_mcp.api import create_app, normalize_client_ip
from kakao_mcp.config import AgentSettings


def _settings(**overrides) -> AgentSettings:
    base = dict(
        api_key="secret",
        host="127.0.0.1",
        port=8765,
        allow_ips=[],
        allowed_file_root=r"C:\KakaoAgent\jobs",
        max_file_size_mb=100,
        job_wait_timeout_sec=60.0,
        job_exec_timeout_sec=300.0,
        log_message_body=False,
    )
    base.update(overrides)
    return AgentSettings(**base)


@pytest.fixture
def mock_service():
    return MagicMock()


@pytest.fixture
def client(mock_service):
    app = create_app(_settings(), service=mock_service)
    return TestClient(app)


@pytest.fixture
def authed_client(client):
    client.headers.update({"X-API-Key": "secret"})
    return client


def test_normalize_ipv4_mapped():
    assert normalize_client_ip("::ffff:10.0.0.12") == "10.0.0.12"


def test_missing_api_key_401(client, mock_service):
    r = client.get("/health")
    assert r.status_code == 401
    assert r.json()["error_code"] == "INVALID_API_KEY"
    mock_service.health.assert_not_called()


def test_wrong_api_key_401(client, mock_service):
    r = client.get("/health", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_ip_not_allowed_403(mock_service):
    app = create_app(
        _settings(allow_ips=["10.0.0.1"]),
        service=mock_service,
    )
    c = TestClient(app)
    # TestClient uses 127.0.0.1 / testclient
    r = c.get("/health", headers={"X-API-Key": "secret"})
    assert r.status_code == 403
    assert r.json()["error_code"] == "IP_NOT_ALLOWED"


def test_health_ok(authed_client, mock_service):
    mock_service.health.return_value = {
        "success": True,
        "kakaotalk_running": True,
        "pid": 1,
    }
    r = authed_client.get("/health")
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert r.json()["pid"] == 1


def test_rooms(authed_client, mock_service):
    mock_service.list_rooms.return_value = {
        "success": True,
        "rooms": [{"title": "A", "hwnd": 1}],
    }
    r = authed_client.get("/rooms")
    assert r.status_code == 200
    assert r.json()["rooms"][0]["title"] == "A"


def test_send_message(authed_client, mock_service):
    mock_service.send_message.return_value = {
        "success": True,
        "room_name": "R",
        "automation_success": True,
        "verification": "UI_ACTION_COMPLETED",
    }
    r = authed_client.post(
        "/send/message",
        json={"room_name": "R", "message": "hi"},
    )
    assert r.status_code == 200
    assert r.json()["automation_success"] is True
    assert "delivered" not in r.json()
    mock_service.send_message.assert_called_once_with("R", "hi")


def test_open_room(authed_client, mock_service):
    mock_service.open_room.return_value = {"success": True, "hwnd": 9}
    r = authed_client.post("/rooms/open", json={"room_name": "R"})
    assert r.status_code == 200
    mock_service.open_room.assert_called_once_with("R")
