"""Local Chat Completions ↔ Responses helpers for Codex adapter.

This is the Phase 2 replacement for importing Hermes Agent's Responses
transport.  It keeps only the narrow conversion and normalization behavior the
adapter needs for Honcho's OpenAI-compatible calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Mapping

DEFAULT_AGENT_IDENTITY = "You are a helpful assistant."


def _as_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content)


def _chat_content_to_responses_parts(content: Any, *, role: str) -> list[dict[str, Any]]:
    text = _as_text_content(content)
    if role == "assistant":
        return [{"type": "output_text", "text": text}]
    return [{"type": "input_text", "text": text}]


def chat_messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            # System messages become the Responses `instructions` field.
            continue
        if role == "tool":
            content = _as_text_content(message.get("content"))
            call_id = message.get("tool_call_id") or message.get("call_id") or "call_0"
            items.append({"type": "function_call_output", "call_id": str(call_id), "output": content})
            continue
        if role == "assistant" and message.get("tool_calls"):
            for call in message.get("tool_calls") or []:
                if not isinstance(call, Mapping):
                    continue
                raw_function = call.get("function")
                function = raw_function if isinstance(raw_function, Mapping) else {}
                name = function.get("name") or call.get("name")
                arguments = function.get("arguments") or call.get("arguments") or "{}"
                if not name:
                    continue
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
                items.append(
                    {
                        "type": "function_call",
                        "call_id": str(call.get("id") or call.get("call_id") or name),
                        "name": str(name),
                        "arguments": arguments,
                    }
                )
            content = _as_text_content(message.get("content"))
            if not content:
                continue
        target_role = "assistant" if role == "assistant" else "user"
        items.append({"role": target_role, "content": _as_text_content(message.get("content"))})
    return items


def responses_tools(tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), Mapping):
            fn = tool["function"]
            name = fn.get("name")
            if not name:
                continue
            converted.append(
                {
                    "type": "function",
                    "name": str(name),
                    "description": str(fn.get("description") or ""),
                    "strict": False,
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        elif tool.get("name"):
            converted.append(dict(tool))
    return converted or None


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _iter_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for part in content:
            part_type = _get(part, "type", "")
            text = _get(part, "text", None)
            if isinstance(text, str) and (not part_type or "text" in str(part_type)):
                parts.append(text)
    return "".join(parts)


def normalize_response(response: Any) -> SimpleNamespace:
    output = _get(response, "output", None) or []
    text_parts: list[str] = []
    tool_calls: list[SimpleNamespace] = []
    if isinstance(output, list):
        for item in output:
            item_type = str(_get(item, "type", ""))
            if item_type == "message" or _get(item, "role", None) == "assistant":
                text = _iter_content_text(_get(item, "content", []))
                if text:
                    text_parts.append(text)
            elif item_type == "function_call":
                tool_calls.append(
                    SimpleNamespace(
                        id=_get(item, "call_id", None) or _get(item, "id", None),
                        name=str(_get(item, "name", "")),
                        arguments=_get(item, "arguments", "{}"),
                    )
                )
    if not text_parts:
        output_text = _get(response, "output_text", None)
        if isinstance(output_text, str):
            text_parts.append(output_text)
    status = str(_get(response, "status", "completed") or "completed")
    finish_reason = "length" if status == "incomplete" else ("tool_calls" if tool_calls else "stop")
    return SimpleNamespace(
        content="".join(text_parts),
        tool_calls=tool_calls or None,
        finish_reason=finish_reason,
        usage=_get(response, "usage", None),
    )


class LocalCodexResponsesTransport:
    """Minimal transport implementing the bridge methods used by the adapter."""

    def build_kwargs(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        instructions = str(params.get("instructions") or "").strip()
        payload_messages = messages
        if not instructions and messages and messages[0].get("role") == "system":
            instructions = _as_text_content(messages[0].get("content")).strip()
            payload_messages = messages[1:]
        if not instructions:
            instructions = DEFAULT_AGENT_IDENTITY
        reasoning_effort = "medium"
        reasoning_config = params.get("reasoning_config")
        if isinstance(reasoning_config, Mapping):
            effort = reasoning_config.get("effort")
            if effort:
                reasoning_effort = str(effort)
        if reasoning_effort == "minimal":
            reasoning_effort = "low"
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": chat_messages_to_responses_input(payload_messages),
            "store": False,
        }
        converted_tools = responses_tools(tools)
        if converted_tools:
            kwargs["tools"] = converted_tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = True
        rc = params.get("reasoning_config")
        reasoning_enabled = not (isinstance(rc, Mapping) and rc.get("enabled") is False)
        if reasoning_enabled:
            kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
            kwargs["include"] = ["reasoning.encrypted_content"]
        else:
            kwargs["include"] = []
        timeout = params.get("timeout")
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
            kwargs["timeout"] = float(timeout)
        return kwargs

    def normalize_response(self, response: Any) -> SimpleNamespace:
        return normalize_response(response)
