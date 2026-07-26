from __future__ import annotations

import os

import httpx
import pytest


API_BASE_URL = os.getenv("SERVER_API_INTEGRATION_URL")


@pytest.mark.skipif(not API_BASE_URL, reason="set SERVER_API_INTEGRATION_URL to run against Compose")
def test_compose_api_uses_postgres_and_redis_readiness():
    response = httpx.get(f"{API_BASE_URL}/health/ready", timeout=5)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.skipif(not API_BASE_URL, reason="set SERVER_API_INTEGRATION_URL to run against Compose")
def test_compose_api_persists_activation_session_and_draws():
    admin = {"X-Admin-Token": os.environ["SERVER_API_ADMIN_TOKEN"]}
    suffix = os.urandom(6).hex()
    created = httpx.post(
        f"{API_BASE_URL}/v1/admin/activation-codes",
        headers=admin,
        json={"activation_code": f"INTEGRATION-{suffix}", "expires_in_seconds": 60},
        timeout=5,
    )
    assert created.status_code == 201

    session = httpx.post(
        f"{API_BASE_URL}/v1/auth/session",
        json={"machine_code": f"machine-{suffix}", "activation_code": f"INTEGRATION-{suffix}"},
        timeout=5,
    )
    assert session.status_code == 200
    user = {"Authorization": f"Bearer {session.json()['access_token']}"}

    written = httpx.put(
        f"{API_BASE_URL}/v1/admin/draws",
        headers=admin,
        json={"site": "pc28", "period": suffix, "result": "大双", "total": 14},
        timeout=5,
    )
    assert written.status_code == 200
    history = httpx.get(f"{API_BASE_URL}/v1/draws/pc28/history?limit=500", headers=user, timeout=5)
    assert history.status_code == 200
    assert any(item["period"] == suffix for item in history.json()["items"])


@pytest.mark.skipif(not API_BASE_URL, reason="set SERVER_API_INTEGRATION_URL to run against Compose")
def test_compose_api_revokes_a_logged_out_token_in_redis():
    admin = {"X-Admin-Token": os.environ["SERVER_API_ADMIN_TOKEN"]}
    suffix = os.urandom(6).hex()
    httpx.post(
        f"{API_BASE_URL}/v1/admin/activation-codes",
        headers=admin,
        json={"activation_code": f"REDIS-{suffix}", "expires_in_seconds": 60},
        timeout=5,
    ).raise_for_status()
    session = httpx.post(
        f"{API_BASE_URL}/v1/auth/session",
        json={"machine_code": f"machine-{suffix}", "activation_code": f"REDIS-{suffix}"},
        timeout=5,
    )
    session.raise_for_status()
    headers = {"Authorization": f"Bearer {session.json()['access_token']}"}

    assert httpx.delete(f"{API_BASE_URL}/v1/auth/session", headers=headers, timeout=5).status_code == 204
    assert httpx.get(f"{API_BASE_URL}/v1/audit-events", headers=headers, timeout=5).status_code == 401
