"""Hugging Face GGUF URL helpers for the installer."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

HF_HOST = "huggingface.co"


@dataclass(frozen=True)
class HFUrl:
    owner: str
    repo: str
    revision: str = "main"
    path: str = ""
    mode: str = "repo"  # repo, tree, blob, resolve

    @property
    def repo_id(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_hf_url(raw_url: str) -> HFUrl:
    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != HF_HOST:
        raise ValueError("URL must be a https://huggingface.co/... address")

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Hugging Face URL must include owner and repository")

    owner, repo = parts[0], parts[1]
    if len(parts) == 2:
        return HFUrl(owner=owner, repo=repo)

    mode = parts[2]
    if mode not in {"blob", "resolve", "tree"}:
        # Model pages sometimes carry extra UI paths, but those are not useful
        # for deterministic installer downloads.
        raise ValueError("Hugging Face URL must be a repo URL, /tree/ URL, /blob/ file URL, or /resolve/ file URL")

    if len(parts) < 4:
        raise ValueError(f"Hugging Face /{mode}/ URL must include a revision")

    revision = parts[3]
    path = "/".join(parts[4:])
    return HFUrl(owner=owner, repo=repo, revision=revision, path=path, mode=mode)


def is_gguf_path(path: str) -> bool:
    return path.lower().endswith(".gguf")


def resolve_file_url(info: HFUrl, path: str | None = None) -> str:
    file_path = path if path is not None else info.path
    if not file_path or not is_gguf_path(file_path):
        raise ValueError("Selected Hugging Face file must end with .gguf")
    repo = f"{quote(info.owner)}/{quote(info.repo)}"
    encoded_path = "/".join(quote(part) for part in file_path.split("/"))
    return f"https://{HF_HOST}/{repo}/resolve/{quote(info.revision)}/{encoded_path}"


def list_gguf_files(info: HFUrl, *, timeout_seconds: float = 30.0) -> list[str]:
    repo = f"{quote(info.owner)}/{quote(info.repo)}"
    revision = quote(info.revision)
    api_url = f"https://{HF_HOST}/api/models/{repo}/tree/{revision}?recursive=1"
    request = Request(api_url, headers={"User-Agent": "honcho-codex-gateway-installer"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed HF host after validation
        payload = json.loads(response.read().decode("utf-8"))

    files: list[str] = []
    prefix = info.path.rstrip("/") + "/" if info.mode == "tree" and info.path else ""
    for entry in payload:
        if entry.get("type") not in {"file", "regular"}:
            continue
        path = str(entry.get("path") or "")
        if prefix and not path.startswith(prefix):
            continue
        if is_gguf_path(path):
            files.append(path)
    return sorted(files)


def _choose_file(files: Iterable[str]) -> str:
    files = list(files)
    if not files:
        raise ValueError("No .gguf files found in that Hugging Face repo/tree URL")
    if len(files) == 1:
        print(f"Found one GGUF file: {files[0]}", file=sys.stderr)
        return files[0]

    print("Found GGUF files:", file=sys.stderr)
    for index, path in enumerate(files, start=1):
        print(f"  {index}) {path}", file=sys.stderr)
    while True:
        print("Choose GGUF file [1]: ", end="", file=sys.stderr, flush=True)
        answer = sys.stdin.readline().strip()
        if not answer:
            answer = "1"
        try:
            selected = int(answer)
        except ValueError:
            print("Please enter a number.", file=sys.stderr)
            continue
        if 1 <= selected <= len(files):
            return files[selected - 1]
        print(f"Please enter a number between 1 and {len(files)}.", file=sys.stderr)


def select_hf_gguf_url(raw_url: str) -> str:
    info = parse_hf_url(raw_url)
    if info.mode in {"blob", "resolve"}:
        return resolve_file_url(info)
    selected = _choose_file(list_gguf_files(info))
    return resolve_file_url(info, selected)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python -m honcho_codex_gateway.hf_gguf <huggingface-url>", file=sys.stderr)
        return 2
    try:
        print(select_hf_gguf_url(argv[0]))
    except Exception as exc:  # deliberate user-facing CLI boundary
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
