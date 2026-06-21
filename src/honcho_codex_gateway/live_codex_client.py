"""Live Codex client for the Honcho Codex Gateway.

The public shape intentionally mirrors :class:`StaticFakeResponsesClient`:
`client.responses.create(**kwargs)`.  This lets the bridge stay unaware of
whether it is calling the deterministic fake or the live Codex backend.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from types import SimpleNamespace

from .config import AdapterConfig, load_config

AuthResolver = Callable[..., Mapping[str, Any]]
ClientFactory = Callable[..., Any]


class CodexAdapterLiveError(RuntimeError):
    """Base class for controlled live-adapter failures."""

    status_code = 502


class CodexAdapterAuthError(CodexAdapterLiveError):
    """Raised when Codex credentials are missing or invalid."""

    status_code = 503


class CodexAdapterRateLimitError(CodexAdapterLiveError):
    """Raised when Codex reports quota/rate limiting."""

    status_code = 429


class CodexAdapterDependencyError(CodexAdapterLiveError):
    """Raised when an optional live-mode dependency is unavailable."""

    status_code = 501


def _load_auth_resolver(config: AdapterConfig) -> AuthResolver:
    """Load the adapter-local Codex OAuth credential resolver lazily."""

    del config
    from .codex_auth import CodexAuthStoreError, resolve_codex_runtime_credentials

    def resolver(**kwargs: Any) -> Mapping[str, Any]:
        try:
            return resolve_codex_runtime_credentials(**kwargs)
        except CodexAuthStoreError as exc:  # pragma: no cover - exercised via injected resolvers
            message = _safe_auth_message(exc)
            raise CodexAdapterAuthError(message) from exc

    return resolver


def _safe_auth_message(exc: BaseException) -> str:
    """Return a controlled auth message without leaking token-shaped details."""

    code = getattr(exc, "code", None)
    relogin = getattr(exc, "relogin_required", None)
    if code:
        suffix = f" ({code})"
    else:
        suffix = ""
    if relogin:
        return (
            "Codex credentials are missing or need re-authentication"
            f"{suffix}. Run `honcho-codex-auth login --no-browser` or `python -m honcho_codex_gateway.codex_auth login --no-browser`."
        )
    return f"Codex credentials are unavailable{suffix}."


def _default_openai_client_factory(*, api_key: str, base_url: str) -> Any:
    """Create a synchronous OpenAI SDK client for Responses API calls."""

    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depends on environment packaging
        raise CodexAdapterDependencyError(
            "Live mode requires the `openai` Python package. Install codex_adapter with live dependencies."
        ) from exc

    return OpenAI(api_key=api_key, base_url=base_url)


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    return None


def _safe_upstream_message(exc: BaseException) -> str:
    status = _status_code(exc)
    if status == 401:
        return "Codex upstream returned 401 after credential refresh; re-authentication is required."
    if status == 429:
        return "Codex upstream quota/rate limit reached."
    if status:
        return f"Codex upstream request failed with HTTP {status}."
    return f"Codex upstream request failed: {exc.__class__.__name__}."


class CodexLiveClient:
    """Live client that uses adapter-local Codex OAuth credentials."""

    def __init__(
        self,
        *,
        config: AdapterConfig | None = None,
        auth_resolver: AuthResolver | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.config = config or load_config()
        self._auth_resolver = auth_resolver
        self._client_factory = client_factory or _default_openai_client_factory
        self.last_credentials_source: str | None = None
        self.last_base_url: str | None = None

    @property
    def responses(self) -> "CodexLiveClient":
        return self

    def create(self, **kwargs: Any) -> Any:
        """Call Codex Responses, retrying once on 401 with a forced refresh."""

        try:
            return self._create_once(kwargs, force_refresh=False)
        except CodexAdapterLiveError:
            raise
        except Exception as exc:
            if _status_code(exc) == 401:
                try:
                    return self._create_once(kwargs, force_refresh=True)
                except Exception as retry_exc:
                    raise CodexAdapterAuthError(_safe_upstream_message(retry_exc)) from retry_exc
            if _status_code(exc) == 429:
                raise CodexAdapterRateLimitError(_safe_upstream_message(exc)) from exc
            raise CodexAdapterLiveError(_safe_upstream_message(exc)) from exc

    def _create_once(self, kwargs: Mapping[str, Any], *, force_refresh: bool) -> Any:
        resolver = self._auth_resolver or _load_auth_resolver(self.config)
        try:
            credentials = resolver(
                force_refresh=force_refresh,
                refresh_if_expiring=True,
            )
        except CodexAdapterLiveError:
            raise
        except Exception as exc:
            raise CodexAdapterAuthError(_safe_auth_message(exc)) from exc

        api_key = str(credentials.get("api_key") or "").strip()
        if not api_key:
            raise CodexAdapterAuthError(
                "Codex credentials did not include an access token. Run `honcho-codex-auth login --no-browser`."
            )
        base_url = str(credentials.get("base_url") or self.config.codex_base_url).strip().rstrip("/")
        self.last_credentials_source = str(credentials.get("source") or "unknown")
        self.last_base_url = base_url

        client = self._client_factory(api_key=api_key, base_url=base_url)
        return self._send_responses_request(client, dict(kwargs), base_url=base_url)

    @staticmethod
    def _send_responses_request(client: Any, kwargs: dict[str, Any], *, base_url: str) -> Any:
        responses = getattr(client, "responses", None)
        if responses is None:
            raise TypeError("Live Codex client factory must return an object exposing responses.create")

        # chatgpt.com/backend-api/codex currently requires the Responses streaming
        # endpoint even when the caller wants a non-streaming facade.  The OpenAI
        # SDK's stream context manager assembles a final Response object that the
        # existing Hermes normalizer can consume, so the adapter still returns a
        # normal Chat Completions JSON response to Honcho.
        if "/backend-api/codex" in base_url and hasattr(responses, "stream"):
            output_items: list[Any] = []
            text_done: str | None = None
            with responses.stream(**kwargs) as stream:
                for event in stream:
                    event_type = getattr(event, "type", "")
                    if event_type == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if item is not None:
                            output_items.append(item)
                    elif event_type == "response.output_text.done":
                        text = getattr(event, "text", None)
                        if isinstance(text, str):
                            text_done = text
                final_response = stream.get_final_response()

            if getattr(final_response, "output", None):
                return final_response
            if output_items:
                return SimpleNamespace(
                    id=getattr(final_response, "id", None),
                    status=getattr(final_response, "status", "completed"),
                    output=output_items,
                    usage=getattr(final_response, "usage", None),
                )
            if text_done:
                return SimpleNamespace(
                    id=getattr(final_response, "id", None),
                    status=getattr(final_response, "status", "completed"),
                    output=[
                        SimpleNamespace(
                            type="message",
                            role="assistant",
                            status="completed",
                            content=[SimpleNamespace(type="output_text", text=text_done)],
                        )
                    ],
                    usage=getattr(final_response, "usage", None),
                )
            return final_response

        if not hasattr(responses, "create"):
            raise TypeError("Live Codex client factory must return an object exposing responses.create")
        return responses.create(**kwargs)
