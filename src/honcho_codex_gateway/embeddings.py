"""OpenAI-compatible embedding proxy routes."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import GatewayConfig


class EmbeddingRequest(BaseModel):
    """Permissive OpenAI-compatible embeddings request."""

    input: str | list[str] | list[int] | list[list[int]]
    model: str | None = None
    encoding_format: str | None = None
    dimensions: int | None = Field(default=None, ge=1)
    user: str | None = None

    model_config = ConfigDict(extra="allow")


class EmbeddingBackendError(RuntimeError):
    """Controlled embedding backend failure."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _openai_embedding_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/embeddings"):
        return base
    return f"{base}/embeddings"


async def proxy_embeddings(request: EmbeddingRequest, *, config: GatewayConfig) -> dict[str, Any]:
    """Forward an embeddings request to an OpenAI-compatible backend.

    The supported backend is llama.cpp server started with ``--embedding``.
    """

    if config.embedding_backend == "disabled":
        raise EmbeddingBackendError("Embeddings are disabled for this gateway.", status_code=501)
    payload = request.model_dump(exclude_none=True)
    payload["model"] = request.model or config.embedding_model
    url = _openai_embedding_url(config.embedding_base_url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.request_timeout_seconds)) as client:
            response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
    except httpx.TimeoutException as exc:
        raise EmbeddingBackendError("Embedding backend timed out.", status_code=504) from exc
    except httpx.HTTPError as exc:
        raise EmbeddingBackendError("Embedding backend request failed.", status_code=502) from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise EmbeddingBackendError(
            f"Embedding backend returned HTTP {response.status_code}: {detail}",
            status_code=response.status_code if response.status_code < 500 else 502,
        )
    data = response.json()
    if isinstance(data, dict):
        data.setdefault("model", payload["model"])
        return data
    raise EmbeddingBackendError("Embedding backend returned a non-object JSON response.", status_code=502)
