import io
import struct
from pathlib import Path

import pytest

from honcho_codex_gateway import hf_gguf
from honcho_codex_gateway.honcho_compose import ensure_honcho_compose, patch_honcho_compose
from honcho_codex_gateway.gguf_metadata import detect_embedding_dimensions
from honcho_codex_gateway.prepare import _apply_honcho_env, _compose_mount_path, _resolve_embedding_dimensions


def _write_fake_gguf(path: Path, *, key: str = "bert.embedding_length", value: int = 1024) -> None:
    data = bytearray()
    data += b"GGUF"
    data += struct.pack("<I", 3)  # version
    data += struct.pack("<Q", 0)  # tensor count
    data += struct.pack("<Q", 1)  # metadata count
    key_bytes = key.encode()
    data += struct.pack("<Q", len(key_bytes))
    data += key_bytes
    data += struct.pack("<I", 4)  # GGUFValueType.UINT32
    data += struct.pack("<I", value)
    path.write_bytes(data)


def test_ensure_honcho_compose_copies_template_when_missing(tmp_path):
    honcho = tmp_path / "honcho"
    honcho.mkdir()
    (honcho / "docker-compose.yml.example").write_text(
        "services:\n"
        "  api:\n"
        "    image: honcho-api\n"
        "  deriver:\n"
        "    image: honcho-deriver\n"
    )

    compose, created = ensure_honcho_compose(honcho)

    assert created is True
    assert compose == honcho / "docker-compose.yml"
    assert compose.exists()
    assert (honcho / "docker-compose.yml.example").exists()


def test_patch_honcho_compose_adds_linux_host_gateway(tmp_path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  api:\n"
        "    image: honcho-api\n"
        "  deriver:\n"
        "    image: honcho-deriver\n"
        "  database:\n"
        "    image: postgres\n"
    )

    assert patch_honcho_compose(compose) is True
    text = compose.read_text()
    assert text.count('"host.docker.internal:host-gateway"') == 2
    assert "  api:\n    extra_hosts:\n      - \"host.docker.internal:host-gateway\"\n    image: honcho-api" in text
    assert "  deriver:\n    extra_hosts:\n      - \"host.docker.internal:host-gateway\"\n    image: honcho-deriver" in text
    assert list(tmp_path.glob("docker-compose.yml.bak.honcho-codex-gateway-*"))
    assert patch_honcho_compose(compose) is False
    assert compose.read_text().count('"host.docker.internal:host-gateway"') == 2


def test_patch_honcho_compose_extends_existing_extra_hosts(tmp_path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  api:\n"
        "    extra_hosts:\n"
        "      - \"other.local:host-gateway\"\n"
        "    image: honcho-api\n"
        "  deriver:\n"
        "    extra_hosts:\n"
        "      - \"host.docker.internal:host-gateway\"\n"
        "    image: honcho-deriver\n"
    )

    assert patch_honcho_compose(compose) is True
    text = compose.read_text()
    assert text.count('"host.docker.internal:host-gateway"') == 2
    assert '"other.local:host-gateway"' in text


def test_hf_direct_blob_url_converts_to_resolve_url():
    url = "https://huggingface.co/org/repo/blob/main/subdir/model-Q4_K_M.gguf"

    assert hf_gguf.select_hf_gguf_url(url) == "https://huggingface.co/org/repo/resolve/main/subdir/model-Q4_K_M.gguf"


def test_hf_non_huggingface_url_is_rejected():
    with pytest.raises(ValueError, match="huggingface.co"):
        hf_gguf.parse_hf_url("https://example.com/org/repo/resolve/main/model.gguf")


def test_hf_repo_url_lists_gguf_files_and_prompts(monkeypatch):
    monkeypatch.setattr(hf_gguf, "list_gguf_files", lambda info: ["a-Q4.gguf", "b-Q8.gguf"])
    monkeypatch.setattr(hf_gguf.sys, "stdin", io.StringIO("2\n"))

    assert hf_gguf.select_hf_gguf_url("https://huggingface.co/org/repo") == "https://huggingface.co/org/repo/resolve/main/b-Q8.gguf"


def test_detect_embedding_dimensions_from_gguf_metadata(tmp_path):
    gguf = tmp_path / "model.gguf"
    _write_fake_gguf(gguf, value=768)

    assert detect_embedding_dimensions(gguf) == 768
    assert _resolve_embedding_dimensions("auto", gguf) == 768


def test_resolve_embedding_dimensions_uses_fallback_when_model_missing(tmp_path):
    assert _resolve_embedding_dimensions("auto", tmp_path / "missing.gguf", preset_fallback=1024) == 1024


def test_compose_mount_path_keeps_model_path_project_relative():
    assert _compose_mount_path(Path("models/bge-m3-FP16.gguf")) == "./models/bge-m3-FP16.gguf"
    assert _compose_mount_path(Path("./models/bge-m3-FP16.gguf")) == "./models/bge-m3-FP16.gguf"
    assert _compose_mount_path(Path("../models/custom.gguf")) == "../models/custom.gguf"


def test_apply_honcho_env_refuses_partial_env_without_template(tmp_path):
    honcho = tmp_path / "honcho"
    honcho.mkdir()

    with pytest.raises(SystemExit, match="template is missing"):
        _apply_honcho_env(honcho, "EMBEDDING_VECTOR_DIMENSIONS=1024\n", embedding_dimensions=1024)

    assert not (honcho / ".env").exists()


def test_apply_honcho_env_refuses_dimension_mismatch(tmp_path):
    honcho = tmp_path / "honcho"
    honcho.mkdir()
    (honcho / ".env").write_text("EMBEDDING_VECTOR_DIMENSIONS=1536\n")
    env_block = "EMBEDDING_VECTOR_DIMENSIONS=1024\n"

    with pytest.raises(SystemExit) as excinfo:
        _apply_honcho_env(honcho, env_block, embedding_dimensions=1024)

    assert "EMBEDDING_VECTOR_DIMENSIONS=1536" in str(excinfo.value)
    assert (honcho / ".env").read_text() == "EMBEDDING_VECTOR_DIMENSIONS=1536\n"


def test_apply_honcho_env_allows_same_dimension(tmp_path):
    honcho = tmp_path / "honcho"
    honcho.mkdir()
    (honcho / ".env").write_text("EMBEDDING_VECTOR_DIMENSIONS=1024\n")
    env_block = "EMBEDDING_VECTOR_DIMENSIONS=1024\nEMBEDDING_MODEL_CONFIG__MODEL=text-embedding-bge-m3\n"

    written = _apply_honcho_env(honcho, env_block, embedding_dimensions=1024)

    text = written.read_text()
    assert "EMBEDDING_VECTOR_DIMENSIONS=1024" in text
    assert "EMBEDDING_MODEL_CONFIG__MODEL=text-embedding-bge-m3" in text
    assert list(honcho.glob(".env.bak.honcho-codex-gateway-*"))
