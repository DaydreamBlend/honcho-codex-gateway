"""Runtime configuration for honcho-codex-gateway."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal, Mapping

CODEX_BACKEND_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_GATEWAY_MODE: Literal["fake", "live"] = "fake"
DEFAULT_EMBEDDING_BASE_URL = "http://embedding-server:8080/v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-bge-m3"


@dataclass(frozen=True)
class GatewayConfig:
    """Runtime configuration for the local single-user gateway."""

    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    codex_base_url: str = CODEX_BACKEND_BASE_URL
    mode: Literal["fake", "live"] = DEFAULT_GATEWAY_MODE
    gateway_api_key: str | None = None
    require_gateway_auth: bool = False
    embedding_backend: Literal["proxy", "disabled"] = "proxy"
    embedding_base_url: str = DEFAULT_EMBEDDING_BASE_URL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    request_timeout_seconds: float = 120.0

    # Compatibility aliases for copied adapter modules.
    @property
    def codex_adapter_mode(self) -> Literal["fake", "live"]:
        return self.mode


# Backwards-compatible name for modules copied from honcho-codex-adapter.
AdapterConfig = GatewayConfig


def _mode_from_env(value: str | None) -> Literal["fake", "live"]:
    raw = (value or os.getenv("CODEX_ADAPTER_MODE") or DEFAULT_GATEWAY_MODE).strip().lower()
    if raw in {"fake", "mock", "test"}:
        return "fake"
    if raw in {"live", "codex", "real"}:
        return "live"
    raise ValueError("CODEX_GATEWAY_MODE must be one of: fake, live")


def _embedding_backend_from_env(value: str | None) -> Literal["proxy", "disabled"]:
    raw = (value or "proxy").strip().lower().replace("-", "_")
    if raw in {"proxy", "llama", "llama_cpp", "llamacpp"}:
        return "proxy"
    if raw in {"off", "none", "disabled"}:
        return "disabled"
    raise ValueError("EMBEDDING_BACKEND must be one of: proxy, disabled")


def _bool_from_env(value: str | None, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_from_env(value: str | None, *, default: float) -> float:
    try:
        return float(value) if value else default
    except ValueError:
        return default


def load_config(environ: Mapping[str, str] | None = None) -> GatewayConfig:
    """Load gateway configuration from environment-like values."""

    env = os.environ if environ is None else environ
    effort = (env.get("CODEX_GATEWAY_REASONING_EFFORT") or env.get("CODEX_ADAPTER_REASONING_EFFORT") or DEFAULT_REASONING_EFFORT).strip()
    api_key = (env.get("GATEWAY_API_KEY") or "").strip() or None
    return GatewayConfig(
        reasoning_effort=effort or DEFAULT_REASONING_EFFORT,
        codex_base_url=(env.get("CODEX_BACKEND_BASE_URL") or CODEX_BACKEND_BASE_URL).strip().rstrip("/"),
        mode=_mode_from_env(env.get("CODEX_GATEWAY_MODE")),
        gateway_api_key=api_key,
        require_gateway_auth=_bool_from_env(env.get("REQUIRE_GATEWAY_AUTH"), default=bool(api_key)),
        embedding_backend=_embedding_backend_from_env(env.get("EMBEDDING_BACKEND")),
        embedding_base_url=(env.get("EMBEDDING_BASE_URL") or DEFAULT_EMBEDDING_BASE_URL).strip().rstrip("/"),
        embedding_model=(env.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip(),
        request_timeout_seconds=_float_from_env(env.get("REQUEST_TIMEOUT_SECONDS"), default=120.0),
    )
