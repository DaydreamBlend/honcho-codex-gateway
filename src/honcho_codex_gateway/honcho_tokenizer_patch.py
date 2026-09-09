"""Apply a reversible Honcho embedding-tokenizer patch.

The patch keeps Honcho mostly upstream while making its embedding chunker ask this
local gateway for backend/GGUF token counts. This avoids tiktoken under-counting
BGE-M3 GGUF inputs without averaging embeddings in the gateway.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

PATCH_MARKER = "HONCHO_CODEX_GATEWAY_TOKENIZER_PATCH_V2"
PATCH_MARKERS = (PATCH_MARKER, "HONCHO_CODEX_GATEWAY_TOKENIZER_PATCH_V1")

IMPORT_PATCHES = (
    (
        "from __future__ import annotations\n",
        "from __future__ import annotations\nimport json\nimport os\nimport urllib.error\nimport urllib.request\n",
    ),
    (
        "from typing import Any, Literal, NamedTuple, TypeVar\n",
        "from typing import Any, Literal, NamedTuple, TypeVar\nimport json\nimport os\nimport urllib.error\nimport urllib.request\n",
    ),
)

HELPER_SENTINEL = "class BatchItem(NamedTuple):\n"
HELPER_BLOCK = r'''
# HONCHO_CODEX_GATEWAY_TOKENIZER_PATCH_V2: begin

def _gateway_tokenizer_enabled() -> bool:
    return os.environ.get("EMBEDDING_TOKENIZER_PROVIDER", "").lower() in {"gateway", "llama_cpp", "llamacpp"}


def _gateway_tokenizer_base_url() -> str:
    base = os.environ.get("EMBEDDING_TOKENIZER_BASE_URL") or os.environ.get("EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL", "")
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


def _gateway_api_key() -> str:
    key_env = os.environ.get("EMBEDDING_TOKENIZER_API_KEY_ENV", "LLM_OPENAI_API_KEY")
    return os.environ.get(key_env, "")


def _gateway_token_count(text: str, model: str) -> int:
    base = _gateway_tokenizer_base_url()
    if not base:
        raise RuntimeError("EMBEDDING_TOKENIZER_BASE_URL is unset")
    payload = json.dumps({"model": model, "input": text}).encode()
    headers = {"content-type": "application/json"}
    api_key = _gateway_api_key()
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base}/internal/token-count", data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=float(os.environ.get("EMBEDDING_TOKENIZER_TIMEOUT_SECONDS", "30"))) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"gateway tokenizer returned HTTP {exc.code}: {detail}") from exc
    count = data.get("count") if isinstance(data, dict) else None
    if not isinstance(count, int):
        raise RuntimeError(f"gateway tokenizer returned invalid payload: {data!r}")
    return count


def _embedding_token_count(client: "_EmbeddingClient", text: str) -> int:
    if _gateway_tokenizer_enabled():
        return _gateway_token_count(text, client.model)
    return len(client.encoding.encode(text))


def _split_text_by_gateway_tokens(client: "_EmbeddingClient", text: str, max_tokens: int) -> list[tuple[str, int]]:
    count = _embedding_token_count(client, text)
    if count <= max_tokens:
        return [(text, count)]

    chunks: list[tuple[str, int]] = []
    remaining = text
    # Keep overlap smaller than Honcho's token overlap because this splitter is
    # character-boundary based and calls the backend tokenizer repeatedly.
    overlap_chars = int(os.environ.get("EMBEDDING_TOKENIZER_OVERLAP_CHARS", "512"))

    while remaining:
        if _embedding_token_count(client, remaining) <= max_tokens:
            chunks.append((remaining, _embedding_token_count(client, remaining)))
            break

        lo, hi = 1, len(remaining)
        best = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = remaining[:mid]
            if _embedding_token_count(client, candidate) <= max_tokens:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1

        # Prefer a natural boundary near the maximal prefix.
        boundary_floor = max(1, int(best * 0.85))
        boundary = best
        for sep in ("\n\n", "\n", ". ", "。", " "):
            pos = remaining.rfind(sep, boundary_floor, best)
            if pos > 0:
                boundary = pos + len(sep)
                break

        chunk = remaining[:boundary].rstrip()
        if not chunk:
            chunk = remaining[:best]
            boundary = best
        chunk_tokens = _embedding_token_count(client, chunk)
        chunks.append((chunk, chunk_tokens))

        if boundary >= len(remaining):
            break
        start = max(boundary - overlap_chars, 0)
        if start == 0:
            start = boundary
        remaining = remaining[start:].lstrip()

    return chunks
# HONCHO_CODEX_GATEWAY_TOKENIZER_PATCH_V2: end

'''

OLD_EMBED_TOKEN = "token_count = len(self.encoding.encode(query))"
NEW_EMBED_TOKEN = "token_count = _embedding_token_count(self, query)"
OLD_SIMPLE_TOKEN = "tokens = len(self.encoding.encode(text))"
NEW_SIMPLE_TOKEN = "tokens = _embedding_token_count(self, text)"
OLD_SIMPLE_3_1_START = '''        for idx, text in enumerate(texts):
            token_ids = self.encoding.encode(text)
            if len(token_ids) > self.max_embedding_tokens:
'''
NEW_SIMPLE_3_1_START = '''        for idx, text in enumerate(texts):
            tokens = _embedding_token_count(self, text)
            if tokens > self.max_embedding_tokens:
'''
OLD_TRUNCATE_3_1 = '''        token_ids = self.encoding.encode(text)
        keep = self.max_embedding_tokens
'''
NEW_TRUNCATE_3_1 = '''        if _gateway_tokenizer_enabled():
            return _split_text_by_gateway_tokens(
                self, text, self.max_embedding_tokens
            )[0]

        token_ids = self.encoding.encode(text)
        keep = self.max_embedding_tokens
'''
OLD_PREPARE = '''        out: dict[str, list[tuple[str, int]]] = {}
        for text_id, text in id_resource_dict.items():
            tokens = self.encoding.encode(text)
            if len(tokens) > self.max_embedding_tokens:
                out[text_id] = _chunk_text_with_tokens(
                    text, tokens, self.max_embedding_tokens, self.encoding
                )
            else:
                out[text_id] = [(text, len(tokens))]
        return out
'''
NEW_PREPARE = '''        out: dict[str, list[tuple[str, int]]] = {}
        for text_id, text in id_resource_dict.items():
            if _gateway_tokenizer_enabled():
                out[text_id] = _split_text_by_gateway_tokens(self, text, self.max_embedding_tokens)
                continue
            tokens = self.encoding.encode(text)
            if len(tokens) > self.max_embedding_tokens:
                out[text_id] = _chunk_text_with_tokens(
                    text, tokens, self.max_embedding_tokens, self.encoding
                )
            else:
                out[text_id] = [(text, len(tokens))]
        return out
'''


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak.honcho-codex-gateway-{stamp}")
    shutil.copy2(path, backup)
    return backup


def patch_embedding_client(honcho_dir: Path) -> tuple[bool, Path | None]:
    target = honcho_dir / "src" / "embedding_client.py"
    if not target.exists():
        raise FileNotFoundError(f"Honcho embedding_client.py not found: {target}")
    text = target.read_text()
    if any(marker in text for marker in PATCH_MARKERS):
        return False, None

    backup = _backup(target)
    patched = text
    for old, new in IMPORT_PATCHES:
        if old in patched:
            patched = patched.replace(old, new, 1)
            break
    else:
        raise RuntimeError("Could not find import sentinel in embedding_client.py")
    if HELPER_SENTINEL not in patched:
        raise RuntimeError("Could not find helper insertion point in embedding_client.py")
    patched = patched.replace(HELPER_SENTINEL, HELPER_BLOCK + HELPER_SENTINEL, 1)

    replacements = [(OLD_EMBED_TOKEN, NEW_EMBED_TOKEN), (OLD_PREPARE, NEW_PREPARE)]
    if OLD_SIMPLE_3_1_START in patched:
        replacements.extend(
            (
                (OLD_SIMPLE_3_1_START, NEW_SIMPLE_3_1_START),
                ("original_count = len(token_ids)", "original_count = tokens"),
                ("{len(token_ids)} tokens)", "{tokens} tokens)"),
                (
                    "            else:\n                tokens = len(token_ids)\n            prepared_texts.append(text)",
                    "            prepared_texts.append(text)",
                ),
                (OLD_TRUNCATE_3_1, NEW_TRUNCATE_3_1),
            )
        )
    elif OLD_SIMPLE_TOKEN in patched:
        replacements.append((OLD_SIMPLE_TOKEN, NEW_SIMPLE_TOKEN))
    else:
        raise RuntimeError("Could not find simple_batch_embed token-count target")

    for old, new in replacements:
        if old not in patched:
            raise RuntimeError(f"Could not find patch target: {old[:80]!r}")
        patched = patched.replace(old, new, 1)
    target.write_text(patched)
    return True, backup


def ensure_env_values(honcho_dir: Path, *, base_url: str = "http://codex-gateway:8787", max_input_tokens: int = 8192) -> Path:
    env_path = honcho_dir / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"Honcho .env not found: {env_path}")
    text = env_path.read_text()
    updates = {
        "EMBEDDING_TOKENIZER_PROVIDER": "gateway",
        "EMBEDDING_TOKENIZER_BASE_URL": base_url.rstrip("/"),
        "EMBEDDING_TOKENIZER_API_KEY_ENV": "LLM_OPENAI_API_KEY",
        "EMBEDDING_MAX_INPUT_TOKENS": str(max_input_tokens),
    }
    lines = text.splitlines()
    for key, value in updates.items():
        prefix = f"{key}="
        for idx, line in enumerate(lines):
            if line.startswith(prefix):
                lines[idx] = f"{key}={value}"
                break
        else:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")
    return env_path


def apply_honcho_tokenizer_patch(honcho_dir: str | Path, *, base_url: str = "http://codex-gateway:8787", max_input_tokens: int = 8192) -> dict[str, str | bool | None]:
    root = Path(honcho_dir).expanduser().resolve()
    changed, backup = patch_embedding_client(root)
    env_path = ensure_env_values(root, base_url=base_url, max_input_tokens=max_input_tokens)
    return {
        "patched": changed,
        "backup": str(backup) if backup else None,
        "env": str(env_path),
    }


if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Apply Honcho GGUF tokenizer chunking patch")
    parser.add_argument("honcho_dir")
    parser.add_argument("--base-url", default="http://codex-gateway:8787")
    parser.add_argument("--max-input-tokens", type=int, default=8192)
    args = parser.parse_args()
    print(_json.dumps(apply_honcho_tokenizer_patch(args.honcho_dir, base_url=args.base_url, max_input_tokens=args.max_input_tokens), indent=2))
