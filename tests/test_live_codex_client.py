from types import SimpleNamespace

import pytest

from honcho_codex_gateway.config import GatewayConfig, load_config
from honcho_codex_gateway.live_codex_client import CodexLiveClient


class FakeModelsPage:
    def __init__(self, models):
        self._models = models

    def model_dump(self, **_kwargs):
        return {"models": self._models}


class RecordingModels:
    def __init__(self, models):
        self.models = models
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(dict(kwargs))
        return FakeModelsPage(self.models)


class FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(())

    def get_final_response(self):
        return SimpleNamespace(
            id="resp_test",
            status="completed",
            output=[
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[SimpleNamespace(type="output_text", text="ok")],
                )
            ],
            usage=None,
        )


class RecordingResponses:
    def __init__(self):
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(dict(kwargs))
        return FakeStream()


class RecordingOpenAIClient:
    def __init__(self, models):
        self.models = RecordingModels(models)
        self.responses = RecordingResponses()


def auth_resolver(**_kwargs):
    return {
        "api_key": "test-token",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "source": "test",
    }


def make_live_client(*, models, config=None):
    upstream = RecordingOpenAIClient(models)

    def factory(**_kwargs):
        return upstream

    client = CodexLiveClient(
        config=config or GatewayConfig(mode="live", embedding_backend="disabled"),
        auth_resolver=auth_resolver,
        client_factory=factory,
    )
    return client, upstream


def base_kwargs(model):
    return {
        "model": model,
        "instructions": "System instruction",
        "input": [{"role": "user", "content": "ping"}],
        "store": False,
        "reasoning": {"effort": "none"},
        "tools": [
            {
                "type": "function",
                "name": "lookup",
                "description": "Look up a value",
                "strict": False,
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
    }


def test_auto_profile_uses_authenticated_catalog_for_lite_model():
    client, upstream = make_live_client(
        models=[{"slug": "future-lite-model", "use_responses_lite": True}]
    )

    client.create(**base_kwargs("future-lite-model"))

    assert upstream.models.calls == [
        {"extra_query": {"client_version": client.config.codex_client_version}}
    ]
    request = upstream.responses.calls[0]
    assert request["model"] == "future-lite-model"
    assert "instructions" not in request
    assert request["input"][0] == {
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": "System instruction"}],
    }
    assert request["reasoning"] == {"effort": "none", "context": "all_turns"}
    assert request["parallel_tool_calls"] is False
    assert request["extra_headers"] == {
        "originator": "honcho_codex_gateway",
        "version": client.config.codex_client_version,
        "x-openai-internal-codex-responses-lite": "true",
    }
    assert client.last_responses_profile == "lite"


def test_auto_profile_preserves_full_responses_for_non_lite_model():
    client, upstream = make_live_client(
        models=[{"slug": "future-full-model", "use_responses_lite": False}]
    )
    original = base_kwargs("future-full-model")

    client.create(**original)

    request = upstream.responses.calls[0]
    assert request["model"] == "future-full-model"
    assert request["instructions"] == "System instruction"
    assert request["input"] == [{"role": "user", "content": "ping"}]
    assert request["reasoning"] == {"effort": "none"}
    assert request["parallel_tool_calls"] is True
    assert request["extra_headers"] == {
        "originator": "honcho_codex_gateway",
        "version": client.config.codex_client_version,
    }
    assert client.last_responses_profile == "full"


def test_auto_profile_caches_catalog_without_hardcoding_model_names():
    client, upstream = make_live_client(
        models=[
            {"slug": "future-lite-model", "use_responses_lite": True},
            {"slug": "future-full-model", "use_responses_lite": False},
        ]
    )

    client.create(**base_kwargs("future-lite-model"))
    client.create(**base_kwargs("future-full-model"))

    assert len(upstream.models.calls) == 1
    assert [call["model"] for call in upstream.responses.calls] == [
        "future-lite-model",
        "future-full-model",
    ]


def test_explicit_lite_profile_skips_catalog_lookup():
    config = GatewayConfig(
        mode="live",
        embedding_backend="disabled",
        responses_profile="lite",
    )
    client, upstream = make_live_client(models=[], config=config)

    client.create(**base_kwargs("model-not-in-catalog"))

    assert upstream.models.calls == []
    assert upstream.responses.calls[0]["model"] == "model-not-in-catalog"
    assert upstream.responses.calls[0]["reasoning"]["context"] == "all_turns"


def test_responses_profile_config_is_validated():
    config = load_config(
        {
            "CODEX_GATEWAY_RESPONSES_PROFILE": "lite",
            "CODEX_GATEWAY_ORIGINATOR": "custom_gateway",
            "CODEX_GATEWAY_CLIENT_VERSION": "0.150.0",
        }
    )
    assert config.responses_profile == "lite"
    assert config.codex_originator == "custom_gateway"
    assert config.codex_client_version == "0.150.0"
    with pytest.raises(ValueError, match="CODEX_GATEWAY_RESPONSES_PROFILE"):
        load_config({"CODEX_GATEWAY_RESPONSES_PROFILE": "surprise"})
