from fastapi.testclient import TestClient

from honcho_codex_gateway.app import create_app
from honcho_codex_gateway.config import GatewayConfig


def test_health_fake_mode():
    app = create_app(config=GatewayConfig(mode="fake", embedding_backend="disabled"))
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_completions_fake_mode():
    app = create_app(config=GatewayConfig(mode="fake", embedding_backend="disabled"))
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.4-mini", "messages": [{"role": "user", "content": "ping"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert "ping" in data["choices"][0]["message"]["content"]


def test_gateway_auth_required():
    app = create_app(config=GatewayConfig(mode="fake", gateway_api_key="secret", require_gateway_auth=True, embedding_backend="disabled"))
    client = TestClient(app)
    response = client.get("/v1/models")
    assert response.status_code == 401
    response = client.get("/v1/models", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200


def test_embeddings_disabled_returns_501():
    app = create_app(config=GatewayConfig(mode="fake", embedding_backend="disabled"))
    client = TestClient(app)
    response = client.post("/v1/embeddings", json={"model": "text-embedding-bge-m3", "input": "ping"})
    assert response.status_code == 501
