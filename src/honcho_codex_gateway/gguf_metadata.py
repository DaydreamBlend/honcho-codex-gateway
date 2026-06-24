"""Small GGUF metadata helpers for installer-time dimension checks.

This intentionally reads only the GGUF header/key-value metadata needed for
embedding dimension detection. It does not parse tensor data.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO, Any


class GGUFMetadataError(ValueError):
    """Raised when a GGUF file cannot be parsed."""


# llama.cpp gguf-py GGUFValueType enum values.
_UINT8 = 0
_INT8 = 1
_UINT16 = 2
_INT16 = 3
_UINT32 = 4
_INT32 = 5
_FLOAT32 = 6
_BOOL = 7
_STRING = 8
_ARRAY = 9
_UINT64 = 10
_INT64 = 11
_FLOAT64 = 12

_TYPE_FORMATS = {
    _UINT8: "<B",
    _INT8: "<b",
    _UINT16: "<H",
    _INT16: "<h",
    _UINT32: "<I",
    _INT32: "<i",
    _FLOAT32: "<f",
    _BOOL: "<?",
    _UINT64: "<Q",
    _INT64: "<q",
    _FLOAT64: "<d",
}

_DIMENSION_KEY_SUFFIXES = (
    ".embedding_length",
    ".n_embd",
    ".hidden_size",
)
_DIMENSION_KEYS = (
    "embedding_length",
    "n_embd",
    "hidden_size",
)


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise GGUFMetadataError("unexpected end of GGUF metadata")
    return data


def _read_u32(handle: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(handle, 4))[0]


def _read_u64(handle: BinaryIO) -> int:
    return struct.unpack("<Q", _read_exact(handle, 8))[0]


def _read_string(handle: BinaryIO) -> str:
    length = _read_u64(handle)
    return _read_exact(handle, length).decode("utf-8", errors="replace")


def _read_scalar(handle: BinaryIO, value_type: int) -> Any:
    if value_type == _STRING:
        return _read_string(handle)
    fmt = _TYPE_FORMATS.get(value_type)
    if fmt is None:
        raise GGUFMetadataError(f"unsupported GGUF scalar metadata type: {value_type}")
    return struct.unpack(fmt, _read_exact(handle, struct.calcsize(fmt)))[0]


def _read_value(handle: BinaryIO, value_type: int) -> Any:
    if value_type == _ARRAY:
        item_type = _read_u32(handle)
        length = _read_u64(handle)
        # We only need small metadata values. Skip arrays without retaining them.
        if item_type == _STRING:
            return [_read_string(handle) for _ in range(length)]
        fmt = _TYPE_FORMATS.get(item_type)
        if fmt is None:
            raise GGUFMetadataError(f"unsupported GGUF array metadata type: {item_type}")
        item_size = struct.calcsize(fmt)
        _read_exact(handle, item_size * length)
        return None
    return _read_scalar(handle, value_type)


def read_gguf_metadata(path: str | Path, *, max_items: int | None = None) -> dict[str, Any]:
    """Read GGUF key-value metadata from *path*.

    Tensor metadata/data is not read. The returned dictionary contains parsed
    scalar values and small string arrays where encountered.
    """

    gguf_path = Path(path)
    with gguf_path.open("rb") as handle:
        magic = _read_exact(handle, 4)
        if magic != b"GGUF":
            raise GGUFMetadataError(f"not a GGUF file: {gguf_path}")
        version = _read_u32(handle)
        if version not in {2, 3}:
            raise GGUFMetadataError(f"unsupported GGUF version {version}: {gguf_path}")
        _tensor_count = _read_u64(handle)
        metadata_count = _read_u64(handle)
        if max_items is not None:
            metadata_count = min(metadata_count, max_items)

        metadata: dict[str, Any] = {}
        for _ in range(metadata_count):
            key = _read_string(handle)
            value_type = _read_u32(handle)
            metadata[key] = _read_value(handle, value_type)
        return metadata


def detect_embedding_dimensions(path: str | Path) -> int | None:
    """Return an embedding/vector dimension inferred from GGUF metadata.

    Known embedding GGUFs commonly expose keys such as
    ``bert.embedding_length``. The function deliberately returns ``None`` when
    it cannot find a plausible positive integer dimension.
    """

    metadata = read_gguf_metadata(path)
    candidates: list[tuple[str, Any]] = []
    for key, value in metadata.items():
        if key in _DIMENSION_KEYS or any(key.endswith(suffix) for suffix in _DIMENSION_KEY_SUFFIXES):
            candidates.append((key, value))

    # Prefer explicit embedding_length over generic hidden-size/n_embd-like keys.
    candidates.sort(key=lambda item: ("embedding_length" not in item[0], item[0]))
    for _key, value in candidates:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
    return None
