"""Small OpenAI Chat Completions compatibility layer for the MVP adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionMessage(BaseModel):
    """Permissive chat message model.

    Honcho currently sends OpenAI-style message dictionaries. The MVP keeps this
    model intentionally permissive so tool messages and provider metadata can be
    forwarded to local conversion without dropping fields.
    """

    role: str
    content: Any = None

    model_config = ConfigDict(extra="allow")


class ChatCompletionRequest(BaseModel):
    """Subset of OpenAI Chat Completions request fields used by Honcho."""

    model: str
    messages: list[ChatCompletionMessage]
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    response_format: Any | None = None
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False

    model_config = ConfigDict(extra="allow")

    def to_chat_messages(self) -> list[dict[str, Any]]:
        """Return plain OpenAI-style message dictionaries for local conversion."""

        return [message.model_dump(exclude_none=True) for message in self.messages]


    @property
    def effective_max_tokens(self) -> int | None:
        """Prefer OpenAI's newer `max_completion_tokens` over `max_tokens`."""

        return self.max_completion_tokens or self.max_tokens


def _json_arguments(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _get_mapping_or_attr(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def format_tool_calls(tool_calls: Iterable[Any] | None) -> list[dict[str, Any]] | None:
    """Format normalized tool calls as OpenAI Chat Completions tool calls."""

    if not tool_calls:
        return None

    formatted: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        function = _get_mapping_or_attr(tool_call, "function", None)
        name = _get_mapping_or_attr(tool_call, "name", None)
        arguments = _get_mapping_or_attr(tool_call, "arguments", None)

        if function is not None:
            name = name or _get_mapping_or_attr(function, "name", None)
            arguments = arguments if arguments is not None else _get_mapping_or_attr(function, "arguments", None)

        if not name:
            continue

        call_id = (
            _get_mapping_or_attr(tool_call, "id", None)
            or _get_mapping_or_attr(tool_call, "call_id", None)
            or f"call_{index}"
        )
        formatted.append(
            {
                "id": str(call_id),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": _json_arguments(arguments),
                },
            }
        )

    return formatted or None


def normalize_usage(usage: Any | None = None) -> dict[str, int]:
    """Return an OpenAI-compatible usage dictionary.

    Codex Responses usage uses ``input_tokens``/``output_tokens`` while Chat
    Completions consumers expect ``prompt_tokens``/``completion_tokens``.
    Accept both shapes so Honcho telemetry does not see all-zero token counts.
    """

    prompt_tokens = int(
        _get_mapping_or_attr(
            usage,
            "prompt_tokens",
            _get_mapping_or_attr(usage, "input_tokens", 0),
        )
        or 0
    )
    completion_tokens = int(
        _get_mapping_or_attr(
            usage,
            "completion_tokens",
            _get_mapping_or_attr(usage, "output_tokens", 0),
        )
        or 0
    )
    total_tokens = int(
        _get_mapping_or_attr(
            usage,
            "total_tokens",
            prompt_tokens + completion_tokens,
        )
        or 0
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def chat_completion_response(
    *,
    model: str,
    content: str | None = "",
    tool_calls: Iterable[Any] | None = None,
    finish_reason: str | None = None,
    usage: Any | None = None,
    response_id: str | None = None,
    created: int | None = None,
) -> dict[str, Any]:
    """Build a minimal OpenAI-compatible Chat Completions response."""

    formatted_tool_calls = format_tool_calls(tool_calls)
    resolved_finish_reason = finish_reason or ("tool_calls" if formatted_tool_calls else "stop")
    message: dict[str, Any] = {
        "role": "assistant",
        "content": None if formatted_tool_calls else (content or ""),
    }
    if formatted_tool_calls:
        message["tool_calls"] = formatted_tool_calls

    return {
        "id": response_id or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(created if created is not None else time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": resolved_finish_reason,
            }
        ],
        "usage": normalize_usage(usage),
    }
