"""FastAPI app exposing a local Hermes-style Codex gateway."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from .chat_compat import ChatCompletionRequest
from .chat_bridge import (
    CodexChatBridge,
    LiveClientNotConfiguredError,
    StaticFakeResponsesClient,
    StreamingNotSupportedError,
)
from .config import GatewayConfig, load_config
from .embeddings import EmbeddingBackendError, EmbeddingRequest, TokenCountRequest, proxy_embeddings, proxy_token_count
from .live_codex_client import CodexAdapterLiveError, CodexLiveClient


def _default_bridge(config: GatewayConfig) -> CodexChatBridge:
    if config.mode == "live":
        return CodexChatBridge(config=config, client=CodexLiveClient(config=config))
    return CodexChatBridge(config=config, client=StaticFakeResponsesClient())


def _check_gateway_auth(config: GatewayConfig, authorization: str | None) -> None:
    if not config.require_gateway_auth:
        return
    expected = config.gateway_api_key
    if not expected:
        raise HTTPException(status_code=500, detail="Gateway auth is required but GATEWAY_API_KEY is unset")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix) or authorization[len(prefix) :] != expected:
        raise HTTPException(status_code=401, detail="Invalid gateway API key")


def create_app(*, bridge: CodexChatBridge | None = None, config: GatewayConfig | None = None) -> FastAPI:
    """Create the gateway app.

    Defaults to fake Codex mode so tests and imports never spend Codex quota.
    Set ``CODEX_GATEWAY_MODE=live`` to use local Codex OAuth credentials.
    """

    resolved_config = config or load_config()
    app = FastAPI(title="Honcho Codex Gateway", version="0.1.0")
    app.state.config = resolved_config
    app.state.bridge = bridge or _default_bridge(resolved_config)

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        _check_gateway_auth(resolved_config, authorization)

    @app.get("/health")
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": resolved_config.mode,
            "embedding_backend": resolved_config.embedding_backend,
            "embedding_base_url": resolved_config.embedding_base_url,
            "auth_required": resolved_config.require_gateway_auth,
        }

    @app.get("/v1/models", dependencies=[Depends(require_auth)])
    def models() -> dict[str, Any]:
        ids = [
            "gpt-5.4-mini",
            "gpt-5.5",
            resolved_config.embedding_model,
        ]
        return {"object": "list", "data": [{"id": model, "object": "model", "owned_by": "local"} for model in ids]}

    @app.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
    def chat_completions(request: ChatCompletionRequest) -> dict[str, Any]:
        if request.stream:
            raise HTTPException(status_code=400, detail="stream=true is not supported yet")
        try:
            return app.state.bridge.complete(request)
        except StreamingNotSupportedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LiveClientNotConfiguredError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except CodexAdapterLiveError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/v1/responses", dependencies=[Depends(require_auth)])
    def responses_not_implemented() -> None:
        raise HTTPException(
            status_code=501,
            detail="Direct /v1/responses facade is reserved; use /v1/chat/completions for now.",
        )

    @app.post("/internal/token-count", dependencies=[Depends(require_auth)])
    async def token_count(request: TokenCountRequest) -> dict[str, Any]:
        try:
            return await proxy_token_count(request, config=resolved_config)
        except EmbeddingBackendError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/v1/embeddings", dependencies=[Depends(require_auth)])
    async def embeddings(request: EmbeddingRequest) -> dict[str, Any]:
        try:
            return await proxy_embeddings(request, config=resolved_config)
        except EmbeddingBackendError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return app


app = create_app()
