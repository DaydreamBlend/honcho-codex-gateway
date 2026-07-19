from fastapi.testclient import TestClient

from honcho_codex_gateway.app import create_app
from honcho_codex_gateway.chat_bridge import CodexChatBridge, StaticFakeResponsesClient
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
        json={"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "ping"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert "ping" in data["choices"][0]["message"]["content"]


def test_chat_model_is_forwarded_without_an_allowlist():
    config = GatewayConfig(mode="fake", embedding_backend="disabled")
    upstream = StaticFakeResponsesClient()
    bridge = CodexChatBridge(config=config, client=upstream)
    client = TestClient(create_app(bridge=bridge, config=config))
    requested_model = "future-codex-model-not-known-to-gateway"

    response = client.post(
        "/v1/chat/completions",
        json={"model": requested_model, "messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 200
    assert upstream.calls[0]["model"] == requested_model
    assert response.json()["model"] == requested_model


def test_chat_reasoning_effort_is_forwarded_without_rewriting():
    config = GatewayConfig(
        mode="fake",
        reasoning_effort="medium",
        embedding_backend="disabled",
    )
    upstream = StaticFakeResponsesClient()
    bridge = CodexChatBridge(config=config, client=upstream)
    client = TestClient(create_app(bridge=bridge, config=config))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "ping"}],
            "reasoning_effort": "minimal",
        },
    )

    assert response.status_code == 200
    assert upstream.calls[0]["reasoning"] == {
        "effort": "minimal",
        "summary": "auto",
    }
    assert upstream.calls[0]["include"] == ["reasoning.encrypted_content"]


def test_chat_uses_none_without_reasoning_artifacts_when_honcho_omits_effort():
    config = GatewayConfig(mode="fake", embedding_backend="disabled")
    upstream = StaticFakeResponsesClient()
    bridge = CodexChatBridge(config=config, client=upstream)
    client = TestClient(create_app(bridge=bridge, config=config))

    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 200
    assert upstream.calls[0]["reasoning"] == {"effort": "none"}
    assert "include" not in upstream.calls[0]


def test_chat_uses_low_for_omitted_effort_when_tools_are_present():
    config = GatewayConfig(mode="fake", embedding_backend="disabled")
    upstream = StaticFakeResponsesClient()
    bridge = CodexChatBridge(config=config, client=upstream)
    client = TestClient(create_app(bridge=bridge, config=config))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "look this up"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    assert upstream.calls[0]["reasoning"] == {
        "effort": "low",
        "summary": "auto",
    }
    assert upstream.calls[0]["include"] == ["reasoning.encrypted_content"]


def test_chat_preserves_explicit_none_when_tools_are_present():
    config = GatewayConfig(mode="fake", embedding_backend="disabled")
    upstream = StaticFakeResponsesClient()
    bridge = CodexChatBridge(config=config, client=upstream)
    client = TestClient(create_app(bridge=bridge, config=config))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "look this up"}],
            "reasoning_effort": "none",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    assert upstream.calls[0]["reasoning"] == {"effort": "none"}
    assert "include" not in upstream.calls[0]


def test_models_does_not_advertise_a_hardcoded_chat_catalog():
    app = create_app(config=GatewayConfig(mode="fake", embedding_backend="proxy"))
    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    assert [model["id"] for model in response.json()["data"]] == ["text-embedding-bge-m3"]


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


def test_internal_token_count_disabled_returns_501():
    app = create_app(config=GatewayConfig(mode="fake", embedding_backend="disabled"))
    client = TestClient(app)
    response = client.post("/internal/token-count", json={"model": "text-embedding-bge-m3", "input": "ping"})
    assert response.status_code == 501
