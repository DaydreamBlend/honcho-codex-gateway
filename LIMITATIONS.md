# Limitations

Honcho Codex Gateway is experimental and primarily designed for local, single-user Honcho Docker quick-install style setups.

## Intended environment

- Linux is the primary tested environment.
- macOS is untested / experimental.
- Windows and WSL2 are untested / experimental.
- Public hosted deployment is not supported.
- Multi-user deployment is not supported.
- Production API replacement usage is not supported.

## Embedding dimensions

Fresh Honcho installs are safer than retrofitting an existing database.

Honcho may initialize its database/vector index based on the first embedding provider/model dimensions. OpenAI `text-embedding-3-small` commonly uses `1536` dimensions. Local models such as BGE-M3 commonly use different dimensions, for example `1024`.

If a database has already been initialized with one dimension, switching to a model with another dimension later may fail or require a database reset, migration, or re-embedding process. Configure the desired embedding provider before first Honcho startup whenever possible.

## Compatibility risks

Compatibility may break if any of the following change:

- Honcho Docker quick-install configuration or embedding setup behavior.
- Codex CLI/session/OAuth behavior.
- llama.cpp server image flags, defaults, or OpenAI-compatible embedding behavior.
- OpenAI-compatible request/response formats expected by clients.

## API surface

This project focuses on the narrow surface needed for Honcho experiments:

- `/v1/chat/completions` backed by the user's own Codex login/session.
- `/v1/embeddings` backed by a local llama.cpp/GGUF embedding server.
- `/v1/models` for basic compatibility.

It is not a general-purpose OpenAI-compatible gateway for arbitrary applications.
