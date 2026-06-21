"""CLI entrypoint for running the gateway."""

from __future__ import annotations

import argparse

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local Honcho Codex Gateway")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host; defaults to localhost for safety")
    parser.add_argument("--port", default=8787, type=int, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload for development")
    args = parser.parse_args(argv)
    uvicorn.run("honcho_codex_gateway.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
