"""Standalone Codex OAuth credential resolver for the Honcho Codex Gateway.

Portions of this module are adapted from the MIT-licensed Hermes Agent
``hermes_cli/auth.py`` Codex auth-store and refresh flow by Nous Research.
This module intentionally does not import Hermes Agent at runtime. It reads a
Hermes-compatible ``auth.json`` shape produced during OAuth bootstrap and
refreshes the Codex OAuth token pair in-place with a file lock + atomic write.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import httpx

DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_OAUTH_DEVICE_URL = f"{CODEX_OAUTH_ISSUER}/codex/device"
CODEX_OAUTH_DEVICE_USERCODE_URL = f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/usercode"
CODEX_OAUTH_DEVICE_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/token"
CODEX_OAUTH_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/oauth/token"
DEFAULT_REFRESH_SKEW_SECONDS = 120
AUTH_LOCK_TIMEOUT_SECONDS = 15.0


class CodexAuthStoreError(RuntimeError):
    """Controlled auth-store failure that is safe to show to users."""

    def __init__(self, message: str, *, code: str = "codex_auth_error", relogin_required: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.relogin_required = relogin_required


def _default_adapter_auth_home() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "honcho-codex-gateway":
            return parent / ".auth"
    return Path.home() / ".honcho-codex-gateway" / "auth"


def _auth_home() -> Path:
    raw = os.getenv("CODEX_AUTH_DIR")
    return Path(raw).expanduser().resolve() if raw else _default_adapter_auth_home().resolve()


def _auth_path() -> Path:
    return _auth_home() / "auth.json"


def _lock_path() -> Path:
    return _auth_home() / "auth.lock"


@contextlib.contextmanager
def _locked_auth_store(timeout_seconds: float = AUTH_LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    _auth_home().mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = _lock_path()
    lock_path.touch(mode=0o600, exist_ok=True)
    with lock_path.open("r+") as lock_file:
        try:
            import fcntl
        except Exception:  # pragma: no cover - Linux runtime has fcntl
            yield
            return
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CodexAuthStoreError("Timed out waiting for Codex auth store lock.")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_store() -> dict[str, Any]:
    path = _auth_path()
    if not path.exists():
        raise CodexAuthStoreError(
            "No Codex auth store found. Re-run adapter OAuth bootstrap.",
            code="codex_auth_missing",
            relogin_required=True,
        )
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise CodexAuthStoreError(
            "Codex auth store is not valid JSON.",
            code="codex_auth_invalid_json",
            relogin_required=True,
        ) from exc
    if not isinstance(data, dict):
        raise CodexAuthStoreError("Codex auth store has an invalid shape.", relogin_required=True)
    return data


def _save_store(data: Mapping[str, Any]) -> None:
    path = _auth_path()
    _auth_home().mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "credential_pool": {}, "active_provider": "openai-codex"}


def _load_store_or_empty() -> dict[str, Any]:
    try:
        return _load_store()
    except CodexAuthStoreError as exc:
        if exc.code == "codex_auth_missing":
            return _empty_store()
        raise


def _save_codex_credential(
    tokens: Mapping[str, Any],
    *,
    label: str = "honcho-codex-gateway",
    base_url: str = DEFAULT_CODEX_BASE_URL,
) -> dict[str, Any]:
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not access_token:
        raise CodexAuthStoreError("Codex OAuth response did not include access_token.", relogin_required=True)
    if not refresh_token:
        raise CodexAuthStoreError("Codex OAuth response did not include refresh_token.", relogin_required=True)
    entry = {
        "id": secrets.token_hex(8),
        "label": label.strip() or "honcho-codex-gateway",
        "auth_type": "oauth",
        "priority": 0,
        "source": "manual:device_code",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": str(tokens.get("token_type") or "Bearer"),
        "base_url": base_url.strip().rstrip("/") or DEFAULT_CODEX_BASE_URL,
        "last_refresh": _now_iso(),
        "last_status": None,
        "last_status_at": None,
        "last_error_code": None,
        "last_error_reason": None,
        "last_error_message": None,
    }
    with _locked_auth_store():
        store = _load_store_or_empty()
        pool = store.setdefault("credential_pool", {})
        if not isinstance(pool, dict):
            pool = {}
            store["credential_pool"] = pool
        entries = pool.setdefault("openai-codex", [])
        if not isinstance(entries, list):
            entries = []
            pool["openai-codex"] = entries
        entries[:] = [item for item in entries if not (isinstance(item, dict) and item.get("label") == entry["label"])]
        entries.append(entry)
        store["active_provider"] = "openai-codex"
        store["updated_at"] = _now_iso()
        _save_store(store)
    return entry


def _request_device_code(*, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Request an OpenAI Codex device-auth user code.

    OpenAI Codex does not use the generic RFC device-code endpoint here. The
    visible URL is ``/codex/device``, but the CLI bootstrap must call the JSON
    account endpoint that returns ``device_auth_id`` + ``user_code``.
    """
    with httpx.Client(timeout=httpx.Timeout(timeout_seconds), headers={"Accept": "application/json"}) as client:
        response = client.post(
            CODEX_OAUTH_DEVICE_USERCODE_URL,
            headers={"Content-Type": "application/json"},
            json={"client_id": CODEX_OAUTH_CLIENT_ID},
        )
    if response.status_code != 200:
        raise CodexAuthStoreError(f"Codex device-code request failed with HTTP {response.status_code}.")
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("device_auth_id"), str) or not isinstance(payload.get("user_code"), str):
        raise CodexAuthStoreError("Codex device-code response had an invalid shape.")
    payload.setdefault("verification_uri", CODEX_OAUTH_DEVICE_URL)
    return payload


def _poll_device_token(device_auth_id: str, *, user_code: str, interval: float, expires_in: float, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, expires_in)
    poll_interval = max(3.0, interval)
    with httpx.Client(timeout=httpx.Timeout(timeout_seconds), headers={"Accept": "application/json"}) as client:
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            response = client.post(
                CODEX_OAUTH_DEVICE_TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={"device_auth_id": device_auth_id, "user_code": user_code},
            )
            if response.status_code == 200:
                code_payload = response.json()
                if not isinstance(code_payload, dict):
                    raise CodexAuthStoreError("Codex device-auth polling response had an invalid shape.")
                authorization_code = str(code_payload.get("authorization_code") or "").strip()
                code_verifier = str(code_payload.get("code_verifier") or "").strip()
                if not authorization_code or not code_verifier:
                    raise CodexAuthStoreError("Codex device-auth response missed authorization_code or code_verifier.")
                token_response = client.post(
                    CODEX_OAUTH_TOKEN_URL,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "authorization_code",
                        "code": authorization_code,
                        "redirect_uri": f"{CODEX_OAUTH_ISSUER}/deviceauth/callback",
                        "client_id": CODEX_OAUTH_CLIENT_ID,
                        "code_verifier": code_verifier,
                    },
                )
                if token_response.status_code != 200:
                    raise CodexAuthStoreError(f"Codex token exchange failed with HTTP {token_response.status_code}.", relogin_required=True)
                token_payload = token_response.json()
                if not isinstance(token_payload, dict):
                    raise CodexAuthStoreError("Codex token response had an invalid shape.")
                return token_payload
            if response.status_code in {403, 404}:
                continue
            raise CodexAuthStoreError(f"Codex device-auth polling failed with HTTP {response.status_code}.")
    raise CodexAuthStoreError("Codex OAuth device code expired before sign-in completed.", relogin_required=True)


def login_device_flow(*, label: str = "honcho-codex-gateway", no_browser: bool = False, timeout_seconds: float = 20.0) -> dict[str, Any]:
    payload = _request_device_code(timeout_seconds=timeout_seconds)
    verification_uri = str(payload.get("verification_uri") or payload.get("verification_url") or "https://auth.openai.com/codex/device")
    user_code = str(payload.get("user_code") or "").strip()
    interval = float(payload.get("interval") or 5)
    expires_in = float(payload.get("expires_in") or 900)
    print("To continue, follow these steps:\n")
    print("  1. Open this URL in your browser:")
    print(f"     {verification_uri}\n")
    if user_code:
        print("  2. Enter this code:")
        print(f"     {user_code}\n")
    if not no_browser:
        try:
            import webbrowser
            webbrowser.open(verification_uri)
        except Exception:
            pass
    print("Waiting for sign-in... (press Ctrl+C to cancel)")
    tokens = _poll_device_token(
        str(payload["device_auth_id"]),
        user_code=user_code,
        interval=interval,
        expires_in=expires_in,
        timeout_seconds=timeout_seconds,
    )
    entry = _save_codex_credential(tokens, label=label)
    print(f"Added Codex OAuth credential: {entry['label']}")
    return entry


def _openai_codex_entries(store: Mapping[str, Any]) -> list[dict[str, Any]]:
    pool = store.get("credential_pool")
    if isinstance(pool, Mapping):
        entries = pool.get("openai-codex")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _select_entry(store: Mapping[str, Any]) -> dict[str, Any]:
    entries = _openai_codex_entries(store)
    if not entries:
        raise CodexAuthStoreError(
            "No openai-codex credential in adapter auth store. Re-run adapter OAuth bootstrap.",
            code="codex_auth_missing",
            relogin_required=True,
        )
    usable = [entry for entry in entries if str(entry.get("access_token") or "").strip()]
    if not usable:
        raise CodexAuthStoreError(
            "Codex credential is missing an access token. Re-run adapter OAuth bootstrap.",
            code="codex_auth_missing_access_token",
            relogin_required=True,
        )
    usable.sort(key=lambda e: int(e.get("priority") or 0), reverse=True)
    return usable[0]


def _jwt_exp(access_token: str) -> int | None:
    parts = access_token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode())
        data = json.loads(decoded)
        exp = data.get("exp")
        return int(exp) if isinstance(exp, (int, float)) else None
    except Exception:
        return None


def _token_is_expiring(access_token: str, skew_seconds: int) -> bool:
    exp = _jwt_exp(access_token)
    if exp is None:
        return False
    return exp <= int(time.time()) + max(0, int(skew_seconds))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _refresh_tokens(access_token: str, refresh_token: str, *, timeout_seconds: float = 20.0) -> dict[str, str]:
    del access_token
    if not refresh_token.strip():
        raise CodexAuthStoreError(
            "Codex credential is missing a refresh token. Re-run adapter OAuth bootstrap.",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )
    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    with httpx.Client(timeout=timeout, headers={"Accept": "application/json"}) as client:
        response = client.post(
            CODEX_OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_OAUTH_CLIENT_ID,
            },
        )
    if response.status_code == 429:
        raise CodexAuthStoreError(
            "Codex token endpoint is rate limited; retry later.",
            code="codex_auth_rate_limited",
            relogin_required=False,
        )
    if response.status_code != 200:
        relogin = response.status_code in {400, 401, 403}
        raise CodexAuthStoreError(
            f"Codex token refresh failed with HTTP {response.status_code}.",
            code="codex_refresh_failed",
            relogin_required=relogin,
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise CodexAuthStoreError("Codex token refresh returned invalid JSON.", relogin_required=True) from exc
    refreshed_access = payload.get("access_token")
    if not isinstance(refreshed_access, str) or not refreshed_access.strip():
        raise CodexAuthStoreError("Codex token refresh response omitted access_token.", relogin_required=True)
    next_refresh = payload.get("refresh_token")
    return {
        "access_token": refreshed_access.strip(),
        "refresh_token": (next_refresh.strip() if isinstance(next_refresh, str) and next_refresh.strip() else refresh_token.strip()),
        "last_refresh": _now_iso(),
    }


def resolve_codex_runtime_credentials(
    *,
    force_refresh: bool = False,
    refresh_if_expiring: bool = True,
    refresh_skew_seconds: int = DEFAULT_REFRESH_SKEW_SECONDS,
) -> dict[str, Any]:
    """Return an OpenAI SDK credential dict without importing Hermes Agent."""

    refresh_timeout = float(os.getenv("CODEX_REFRESH_TIMEOUT_SECONDS") or os.getenv("HERMES_CODEX_REFRESH_TIMEOUT_SECONDS") or "20")
    with _locked_auth_store(timeout_seconds=max(AUTH_LOCK_TIMEOUT_SECONDS, refresh_timeout + 5.0)):
        store = _load_store()
        entry = _select_entry(store)
        access_token = str(entry.get("access_token") or "").strip()
        refresh_token = str(entry.get("refresh_token") or "").strip()
        should_refresh = bool(force_refresh) or (
            bool(refresh_if_expiring) and _token_is_expiring(access_token, refresh_skew_seconds)
        )
        if should_refresh:
            refreshed = _refresh_tokens(access_token, refresh_token, timeout_seconds=refresh_timeout)
            entry["access_token"] = refreshed["access_token"]
            entry["refresh_token"] = refreshed["refresh_token"]
            entry["last_refresh"] = refreshed["last_refresh"]
            entry["last_status"] = None
            entry["last_status_at"] = None
            entry["last_error_code"] = None
            entry["last_error_reason"] = None
            entry["last_error_message"] = None
            store["updated_at"] = _now_iso()
            _save_store(store)
            access_token = refreshed["access_token"]
        base_url = str(entry.get("base_url") or os.getenv("CODEX_BASE_URL") or DEFAULT_CODEX_BASE_URL).strip().rstrip("/")
    return {
        "provider": "openai-codex",
        "base_url": base_url,
        "api_key": access_token,
        "source": "codex-adapter-auth-store",
        "last_refresh": entry.get("last_refresh"),
        "auth_mode": "chatgpt",
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="honcho-codex-auth", description="Honcho Codex Gateway OAuth utility")
    subparsers = parser.add_subparsers(dest="command")
    login = subparsers.add_parser("login", help="Run OpenAI Codex OAuth device login")
    login.add_argument("--label", default="honcho-codex-gateway", help="Credential label stored in auth.json")
    login.add_argument("--auth-dir", help="Adapter auth directory. Defaults to CODEX_AUTH_DIR or the adapter repo's .auth directory")
    login.add_argument("--no-browser", action="store_true", help="Print URL/code without trying to open a browser")
    login.add_argument("--timeout", type=float, default=20.0, help="Network timeout in seconds")
    args = parser.parse_args(argv)
    if args.command != "login":
        parser.print_help()
        return
    if args.auth_dir:
        os.environ["CODEX_AUTH_DIR"] = args.auth_dir
    login_device_flow(label=args.label, no_browser=args.no_browser, timeout_seconds=args.timeout)


if __name__ == "__main__":
    main()
