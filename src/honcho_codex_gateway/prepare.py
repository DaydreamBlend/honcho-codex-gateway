#!/usr/bin/env python3
"""Prepare a gateway-first fresh Honcho install.

This script intentionally does not edit the Honcho checkout. It prepares this
standalone gateway project and prints the Honcho environment block that should
be applied before running Honcho migrations/startup.
"""

from __future__ import annotations

import argparse
import shutil
import secrets
from datetime import datetime
from pathlib import Path

from .gguf_metadata import GGUFMetadataError, detect_embedding_dimensions

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
AUTH_DIR = ROOT / ".auth"
MODELS_DIR = ROOT / "models"

HONCHO_ENV_TEMPLATE = """# Honcho -> honcho-codex-gateway provider boundary (.env form)
LLM_OPENAI_API_KEY={gateway_api_key}

DIALECTIC_LEVELS__minimal__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL={chat_model}
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
DIALECTIC_LEVELS__low__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__low__MODEL_CONFIG__MODEL={chat_model}
DIALECTIC_LEVELS__low__MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
DIALECTIC_LEVELS__medium__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__medium__MODEL_CONFIG__MODEL={chat_model}
DIALECTIC_LEVELS__medium__MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
DIALECTIC_LEVELS__high__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__high__MODEL_CONFIG__MODEL={chat_model}
DIALECTIC_LEVELS__high__MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
DIALECTIC_LEVELS__max__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__max__MODEL_CONFIG__MODEL={chat_model}
DIALECTIC_LEVELS__max__MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}

SUMMARY_MODEL_CONFIG__TRANSPORT=openai
SUMMARY_MODEL_CONFIG__MODEL={chat_model}
SUMMARY_MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
DERIVER_MODEL_CONFIG__TRANSPORT=openai
DERIVER_MODEL_CONFIG__MODEL={chat_model}
DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
DREAM_DEDUCTION_MODEL_CONFIG__TRANSPORT=openai
DREAM_DEDUCTION_MODEL_CONFIG__MODEL={chat_model}
DREAM_DEDUCTION_MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
DREAM_INDUCTION_MODEL_CONFIG__TRANSPORT=openai
DREAM_INDUCTION_MODEL_CONFIG__MODEL={chat_model}
DREAM_INDUCTION_MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}

EMBEDDING_MODEL_CONFIG__TRANSPORT=openai
EMBEDDING_MODEL_CONFIG__MODEL={embedding_model}
EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL={gateway_base_url}
EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY_ENV=LLM_OPENAI_API_KEY
EMBEDDING_VECTOR_DIMENSIONS={embedding_dimensions}
EMBEDDING_MODEL_CONFIG__DIMENSIONS_MODE=never
"""

def _load_env_template() -> str:
    if ENV_PATH.exists():
        return ENV_PATH.read_text()
    return ENV_EXAMPLE.read_text()


def _upsert_line(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            return "\n".join(lines) + "\n"
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _compose_mount_path(path: Path) -> str:
    """Return a Docker Compose .env path that is explicitly project-relative."""

    raw = str(path)
    if path.is_absolute() or raw.startswith("./") or raw.startswith("../"):
        return raw
    return f"./{raw}"


def _parse_env_value(text: str, key: str) -> str | None:
    prefix = f"{key}="
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _resolve_embedding_dimensions(value: str, gguf_path: Path | None, *, preset_fallback: int | None = None) -> int:
    if value != "auto":
        try:
            dimensions = int(value)
        except ValueError as exc:
            raise SystemExit(f"--embedding-dimensions must be an integer or 'auto', got: {value}") from exc
        if dimensions <= 0:
            raise SystemExit("--embedding-dimensions must be a positive integer")
        return dimensions

    if gguf_path and gguf_path.exists() and gguf_path.is_file():
        try:
            detected = detect_embedding_dimensions(gguf_path)
        except GGUFMetadataError as exc:
            raise SystemExit(f"Could not read GGUF metadata from {gguf_path}: {exc}") from exc
        if detected:
            print(f"Detected embedding dimensions from GGUF metadata: {detected} ({gguf_path})")
            return detected

    if preset_fallback:
        print(f"WARNING: Could not auto-detect GGUF dimensions; using preset fallback: {preset_fallback}")
        return preset_fallback

    raise SystemExit(
        "Could not auto-detect embedding dimensions. Provide --embedding-dimensions N "
        "or ensure --embedding-gguf points to a readable GGUF file."
    )


def _apply_honcho_env(honcho_dir: Path, env_block: str, *, embedding_dimensions: int, force_dimension_change: bool = False) -> Path:
    """Create/update Honcho .env with the generated gateway block."""

    env_path = honcho_dir / ".env"
    template_path = honcho_dir / ".env.template"
    if env_path.exists():
        text = env_path.read_text()
        existing_dimensions = _parse_env_value(text, "EMBEDDING_VECTOR_DIMENSIONS")
        if existing_dimensions and existing_dimensions != str(embedding_dimensions) and not force_dimension_change:
            raise SystemExit(
                "Existing Honcho .env has EMBEDDING_VECTOR_DIMENSIONS="
                f"{existing_dimensions}, but the selected embedding model uses {embedding_dimensions}.\n"
                "Refusing to rewrite embedding dimensions because an existing Honcho database may already "
                "be initialized with the old vector size. Use a fresh Honcho database, migrate/re-embed "
                "intentionally, or pass --force-embedding-dimension-change if you understand the risk."
            )
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = honcho_dir / f".env.bak.honcho-codex-gateway-{stamp}"
        shutil.copy2(env_path, backup_path)
        print(f"Backed up existing Honcho .env to {backup_path}")
    elif template_path.exists():
        text = template_path.read_text()
        print(f"Creating Honcho .env from {template_path}")
    else:
        raise SystemExit(
            f"Honcho .env does not exist and template is missing: {template_path}. "
            "This installer will not create a partial Honcho .env from gateway settings only."
        )

    for raw_line in env_block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        text = _upsert_line(text, key, value)

    env_path.write_text(text)
    env_path.chmod(0o600)
    return env_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare honcho-codex-gateway before fresh Honcho startup")
    parser.add_argument("--gateway-base-url", default="http://codex-gateway:8787/v1")
    parser.add_argument("--chat-model", default="gpt-5.4-mini")
    parser.add_argument("--embedding-model", default="text-embedding-bge-m3")
    parser.add_argument("--embedding-dimensions", default="auto", help="Embedding vector dimensions, or 'auto' to read GGUF metadata")
    parser.add_argument("--embedding-gguf", type=Path, default=ROOT / "models" / "bge-m3-FP16.gguf", help="GGUF file used for --embedding-dimensions auto")
    parser.add_argument("--embedding-dimensions-fallback", default=1024, type=int, help="Fallback dimension for the bundled default preset when auto-detection cannot run")
    parser.add_argument("--force-embedding-dimension-change", action="store_true", help="Allow rewriting an existing Honcho .env with a different EMBEDDING_VECTOR_DIMENSIONS value")
    parser.add_argument("--mode", default="live", choices=["fake", "live"])
    parser.add_argument("--print-only", action="store_true", help="Do not write .env/directories; only print Honcho env")
    parser.add_argument("--honcho-dir", type=Path, help="Honcho checkout to update when --write-honcho-env is set")
    parser.add_argument("--write-honcho-env", action="store_true", help="Create/update Honcho .env with the generated gateway settings")
    args = parser.parse_args()

    gateway_api_key = "<gateway-api-key-from-honcho-codex-gateway-.env>" if args.print_only else secrets.token_urlsafe(32)
    if not args.print_only and ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("GATEWAY_API_KEY="):
                existing = line.split("=", 1)[1].strip()
                if existing and existing != "change-me-random-local-secret":
                    gateway_api_key = existing
                    break

    resolved_embedding_dimensions = _resolve_embedding_dimensions(
        args.embedding_dimensions,
        args.embedding_gguf.expanduser().resolve() if args.embedding_gguf else None,
        preset_fallback=args.embedding_dimensions_fallback,
    )

    values = dict(
        gateway_api_key=gateway_api_key,
        gateway_base_url=args.gateway_base_url.rstrip("/"),
        chat_model=args.chat_model,
        embedding_model=args.embedding_model,
        embedding_dimensions=resolved_embedding_dimensions,
    )
    honcho_env_block = HONCHO_ENV_TEMPLATE.format(**values)
    if args.write_honcho_env:
        if args.print_only:
            raise SystemExit("--write-honcho-env cannot be combined with --print-only")
        if not args.honcho_dir:
            raise SystemExit("--write-honcho-env requires --honcho-dir /path/to/honcho")
        honcho_dir = args.honcho_dir.expanduser().resolve()
        if not honcho_dir.exists():
            raise SystemExit(f"Honcho directory does not exist: {honcho_dir}")
        written = _apply_honcho_env(
            honcho_dir,
            honcho_env_block,
            embedding_dimensions=resolved_embedding_dimensions,
            force_dimension_change=args.force_embedding_dimension_change,
        )
        print(f"Applied generated gateway settings to {written}")

    if not args.print_only:
        AUTH_DIR.mkdir(mode=0o700, exist_ok=True)
        MODELS_DIR.mkdir(exist_ok=True)
        env_text = _load_env_template()
        env_text = _upsert_line(env_text, "CODEX_GATEWAY_MODE", args.mode)
        env_text = _upsert_line(env_text, "GATEWAY_API_KEY", gateway_api_key)
        env_text = _upsert_line(env_text, "EMBEDDING_MODEL", args.embedding_model)
        env_text = _upsert_line(env_text, "EMBEDDING_GGUF_PATH", _compose_mount_path(args.embedding_gguf))
        env_text = _upsert_line(env_text, "CODEX_AUTH_DIR", "/data/codex-auth")
        ENV_PATH.write_text(env_text)
        ENV_PATH.chmod(0o600)
        print(f"Prepared {ENV_PATH}")
        print(f"Prepared {AUTH_DIR}")
        print(f"Prepared {MODELS_DIR}")

    print("\nHoncho .env block:\n")
    print(honcho_env_block)


if __name__ == "__main__":
    main()
