"""Bridge from Chat Completions-shaped requests to Hermes Codex Responses conversion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from types import SimpleNamespace
from typing import Any

from .chat_compat import ChatCompletionRequest, chat_completion_response
from .config import AdapterConfig, load_config


class LiveClientNotConfiguredError(RuntimeError):
    """Raised when code tries to use live Codex without an injected client."""


class StreamingNotSupportedError(ValueError):
    """Raised for `stream=true`, which is outside the MVP boundary."""


class StaticFakeResponsesClient:
    """Deterministic in-process fake for the OpenAI Responses client shape.

    The object intentionally mimics `client.responses.create(**kwargs)` and
    records calls so tests can prove no live network/OAuth code was used.
    """

    def __init__(self, text: str | Callable[[dict[str, Any]], str] | None = None) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    @property
    def responses(self) -> "StaticFakeResponsesClient":
        return self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        text = self._resolve_text(kwargs)
        return make_text_response(text)

    def _resolve_text(self, kwargs: dict[str, Any]) -> str:
        if callable(self.text):
            return str(self.text(kwargs))
        if isinstance(self.text, str):
            return self.text
        user_text = _last_user_text(kwargs.get("input"))
        if user_text:
            return f"Fake Codex response to: {user_text}"
        return "Fake Codex response."


def make_text_response(text: str, *, status: str = "completed") -> SimpleNamespace:
    """Build a tiny Responses API-like object for Hermes normalization."""

    return SimpleNamespace(
        status=status,
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        ],
    )


def _last_user_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    for item in reversed(items):
        if not isinstance(item, Mapping) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, Mapping):
                    value = part.get("text") or part.get("content")
                    if isinstance(value, str):
                        parts.append(value)
                elif isinstance(part, str):
                    parts.append(part)
            return "\n".join(parts).strip()
    return ""


def _structured_output_instruction(response_format: Any) -> str | None:
    """Translate Chat Completions structured-output hints into prompt text.

    Codex's Responses backend used by this adapter does not reliably honor the
    Chat Completions ``response_format`` field directly. Honcho's deriver relies
    on structured JSON output, so preserve that contract by making the JSON-only
    requirement explicit in the instructions sent to Codex.
    """

    if response_format is None:
        return None
    schema: Any | None = None
    if isinstance(response_format, Mapping):
        if response_format.get("type") == "json_object":
            return (
                "Return only a single valid JSON object. Do not include Markdown, "
                "code fences, explanations, or any text before or after the JSON."
            )
        json_schema = response_format.get("json_schema")
        if isinstance(json_schema, Mapping):
            schema = json_schema.get("schema") or json_schema
        elif response_format.get("schema") is not None:
            schema = response_format.get("schema")
    if schema is None:
        schema = response_format
    try:
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        schema_text = str(schema)
    return (
        "Return only a single valid JSON object matching this JSON schema. "
        "Do not include Markdown, code fences, explanations, or any text before "
        f"or after the JSON. JSON schema: {schema_text}"
    )


def _messages_with_structured_output_instruction(
    messages: list[dict[str, Any]],
    response_format: Any,
) -> list[dict[str, Any]]:
    instruction = _structured_output_instruction(response_format)
    if not instruction:
        return messages
    updated = [dict(message) for message in messages]
    if updated and str(updated[0].get("role") or "") == "system":
        content = str(updated[0].get("content") or "").rstrip()
        updated[0]["content"] = f"{content}\n\n{instruction}" if content else instruction
        return updated
    return [{"role": "system", "content": instruction}, *updated]


def _load_responses_transport(config: AdapterConfig) -> Any:
    """Load the adapter-local Responses transport (no Hermes runtime import)."""

    del config
    from .responses_adapter import LocalCodexResponsesTransport

    return LocalCodexResponsesTransport()


class CodexChatBridge:
    """Convert Chat Completions requests into local Codex Responses calls."""

    def __init__(
        self,
        *,
        config: AdapterConfig | None = None,
        client: Any | None = None,
        transport: Any | None = None,
    ) -> None:
        self.config = config or load_config()
        self.transport = transport or _load_responses_transport(self.config)
        self.client = client
        self.last_transport_params: dict[str, Any] | None = None
        self.last_api_kwargs: dict[str, Any] | None = None

    def build_kwargs(self, request: ChatCompletionRequest | Mapping[str, Any]) -> dict[str, Any]:
        """Build Responses SDK kwargs via the local transport."""

        chat_request = self._as_request(request)
        transport_params: dict[str, Any] = {
            "base_url": self.config.codex_base_url,
            "is_codex_backend": True,
            "reasoning_config": {"enabled": True, "effort": self.config.reasoning_effort},
        }
        if chat_request.effective_max_tokens is not None:
            transport_params["max_tokens"] = chat_request.effective_max_tokens

        self.last_transport_params = dict(transport_params)
        messages = _messages_with_structured_output_instruction(
            chat_request.to_chat_messages(),
            chat_request.response_format,
        )
        api_kwargs = self.transport.build_kwargs(
            model=chat_request.model,
            messages=messages,
            tools=chat_request.tools,
            **transport_params,
        )
        self.last_api_kwargs = dict(api_kwargs)
        return api_kwargs

    def complete(self, request: ChatCompletionRequest | Mapping[str, Any]) -> dict[str, Any]:
        """Run a fake/injected Responses call and return Chat Completions JSON."""

        chat_request = self._as_request(request)
        if chat_request.stream:
            raise StreamingNotSupportedError("stream=true is not supported by the MVP adapter")

        api_kwargs = self.build_kwargs(chat_request)
        raw_response = self._invoke_client(api_kwargs)
        normalized = self.transport.normalize_response(raw_response)
        return chat_completion_response(
            model=chat_request.model,
            content=normalized.content,
            tool_calls=normalized.tool_calls,
            finish_reason=normalized.finish_reason,
            usage=normalized.usage,
        )

    def _invoke_client(self, api_kwargs: dict[str, Any]) -> Any:
        if self.client is None:
            raise LiveClientNotConfiguredError(
                "Live Codex/OAuth client wiring is not implemented; inject a fake client for the MVP."
            )

        responses = getattr(self.client, "responses", None)
        if responses is not None and hasattr(responses, "create"):
            return responses.create(**api_kwargs)
        if hasattr(self.client, "create"):
            return self.client.create(**api_kwargs)
        if callable(self.client):
            return self.client(**api_kwargs)
        raise TypeError("Injected client must be callable or expose responses.create/create")

    @staticmethod
    def _as_request(request: ChatCompletionRequest | Mapping[str, Any]) -> ChatCompletionRequest:
        if isinstance(request, ChatCompletionRequest):
            return request
        return ChatCompletionRequest.model_validate(dict(request))

