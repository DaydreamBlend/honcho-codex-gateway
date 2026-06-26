# Honcho Codex Gateway

**Language:** English | [한국어](README.ko.md)

A local gateway for running self-hosted Honcho with Codex-backed chat completions and local GGUF embeddings.

The project is aimed at a narrow setup: Honcho Docker quick install, a user-owned Codex OAuth login for chat, and a local llama.cpp embedding server for BGE-M3 or another GGUF embedding model. It is not a hosted API service or a general OpenAI-compatible proxy.

## What it does

- Exposes `/v1/chat/completions` for Honcho, backed by a local Codex OAuth credential.
- Exposes `/v1/embeddings`, backed by a local llama.cpp GGUF embedding server.
- Writes Honcho `.env` settings for chat, summary, deriver, dream, and embedding providers.
- Patches Honcho `docker-compose.yml` so Honcho containers can reach the gateway over a shared Docker network.
- Applies a small reversible Honcho tokenizer patch for GGUF embeddings, so Honcho chunks messages using llama.cpp/GGUF token counts instead of relying only on `tiktoken` estimates.

## What it is not

This project is not:

- a hosted API service;
- a credential pooling or account sharing tool;
- a rate-limit bypass;
- a scraping or data harvesting tool;
- a production replacement for official APIs;
- a general proxy for arbitrary multi-user applications.

Use it locally, with your own credentials, and do not expose it to the public internet.

## Current status

| Area | Status |
| --- | --- |
| Linux + Docker Compose | Tested |
| Honcho Docker quick install | Primary target |
| Fresh Honcho database | Recommended |
| Existing Honcho database | Possible, but embedding dimension changes require care |
| Default embedding model | BGE-M3 FP16 GGUF, 1024 dimensions |
| macOS / Windows / WSL2 | Not tested yet |
| Public hosted deployment | Not supported |

The default install has been smoke-tested with:

- Honcho API health on `127.0.0.1:8000`
- gateway health on `127.0.0.1:8787`
- Codex-backed Honcho chat
- BGE-M3 embeddings returning 1024-dimensional vectors
- gateway `/internal/token-count` returning llama.cpp/GGUF token counts
- Honcho queue drain to zero pending work units

## Quick install

Clone Honcho and this gateway as sibling directories:

```bash
git clone https://github.com/plastic-labs/honcho.git
git clone https://github.com/DaydreamBlend/honcho-codex-gateway.git
cd honcho-codex-gateway
sudo ./install.sh
```

During `sudo ./install.sh`, the installer will:

1. ask which embedding GGUF model to use;
2. run Codex OAuth login unless you pass `--skip-auth`;
3. prepare gateway `.env`, `.auth/`, `models/`, and a local Python environment;
4. create or update Honcho `.env`;
5. create or patch Honcho `docker-compose.yml` for the shared Docker network;
6. apply the reversible Honcho tokenizer patch;
7. print the Docker Compose commands to run next.

Then start the two stacks in this order:

```bash
cd <parent-directory>/honcho-codex-gateway
sudo docker compose up -d --build

cd <parent-directory>/honcho
sudo docker compose up -d --build
```

The order matters. The gateway stack creates the shared Docker network and the `codex-gateway` service that Honcho uses.

## Why the tokenizer patch exists

Honcho's upstream embedding chunker estimates token counts with `tiktoken`. That is fine for OpenAI embeddings, but the default embedding backend here is BGE-M3 through llama.cpp/GGUF. For log-heavy or mixed text, `tiktoken` can under-count compared with the GGUF tokenizer. The result can be a chunk that Honcho thinks is safe but llama.cpp rejects as too large.

This gateway avoids splitting and averaging embeddings inside the proxy, because that would change retrieval semantics. Instead, the installer applies a small Honcho patch:

```text
Honcho chunker
  -> gateway /internal/token-count
  -> llama.cpp /tokenize
  -> GGUF token count
```

Honcho still creates separate embedding chunks itself. The gateway only provides the backend token count.

The patch is marked and idempotent. If a Honcho update replaces the patched file, rerun:

```bash
cd <parent-directory>/honcho-codex-gateway
sudo ./install.sh
```

The installer will reapply the patch if needed.

## Embedding dimensions: configure before first Honcho startup

Do not start Honcho once with the default OpenAI embedding settings and then switch to BGE-M3 later. Honcho may initialize its database/vector schema using the first configured embedding dimensions.

The bundled BGE-M3 GGUF model returns 1024-dimensional vectors. Some OpenAI embedding models use 1536 dimensions. Switching dimensions after data has been written can require a reset, migration, or re-embedding pass.

For the smooth path, run the gateway installer before the first Honcho startup.

## Custom GGUF models

By default, the installer downloads:

```text
model: gpustack/bge-m3-GGUF / bge-m3-FP16.gguf
license: MIT, inherited from BAAI/bge-m3 and the GGUF model card
path: ./models/bge-m3-FP16.gguf
```

You can also copy a local GGUF into `./models/` or provide a Hugging Face GGUF URL. Direct `.gguf` URLs are accepted; repo/tree URLs show a list of available `.gguf` files.

For scripted installs:

```bash
sudo ./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions auto
```

If dimension detection is not available for the file, pass the dimension explicitly:

```bash
sudo ./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions 768
```

For custom downloads, pass a checksum:

```bash
sudo ./install.sh --model-url <hugging-face-gguf-url> --model-sha256 <sha256>
```

Use `--model-sha256 ''` only if you intentionally accept downloading without checksum verification.

## Runtime topology

The gateway runs as its own Compose stack. Honcho remains close to upstream and joins the gateway through an external Docker network.

```text
Honcho api / deriver
  -> http://codex-gateway:8787/v1
  -> honcho-codex-gateway stack
       - codex-gateway
       - embedding-server
```

The gateway is also published on the host for local smoke tests:

```text
http://127.0.0.1:8787
```

Honcho containers should use Docker DNS over the shared network:

```text
http://codex-gateway:8787/v1
```

Do not point Honcho containers at `host.docker.internal` for the documented Linux setup. The gateway host port is bound to `127.0.0.1` for local-only exposure.

## Honcho configuration shape

The installer writes the full block, but the important part looks like this:

```env
LLM_OPENAI_API_KEY=<gateway-api-key-from-honcho-codex-gateway-.env>

DIALECTIC_LEVELS__minimal__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL=gpt-5.4-mini
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__OVERRIDES__BASE_URL=http://codex-gateway:8787/v1
# Same transport/model/base_url pattern for dialectic low/medium/high/max,
# summary, deriver, dream deduction, and dream induction.

EMBEDDING_MODEL_CONFIG__TRANSPORT=openai
EMBEDDING_MODEL_CONFIG__MODEL=text-embedding-bge-m3
EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL=http://codex-gateway:8787/v1
EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY_ENV=LLM_OPENAI_API_KEY
EMBEDDING_VECTOR_DIMENSIONS=1024
EMBEDDING_MAX_INPUT_TOKENS=8192
EMBEDDING_TOKENIZER_PROVIDER=gateway
EMBEDDING_TOKENIZER_BASE_URL=http://codex-gateway:8787
EMBEDDING_TOKENIZER_API_KEY_ENV=LLM_OPENAI_API_KEY
EMBEDDING_MODEL_CONFIG__DIMENSIONS_MODE=never
```

## Smoke tests

Gateway health:

```bash
curl -sS http://127.0.0.1:8787/health
```

Honcho health:

```bash
curl -sS http://127.0.0.1:8000/health
```

Gateway endpoints under `/v1/*` require an Authorization header using `GATEWAY_API_KEY` from the gateway `.env`.

Embedding smoke:

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/embeddings \
  -H "Authorization: Bearer <gateway-api-key>" \
  -H 'content-type: application/json' \
  -d '{"model":"text-embedding-bge-m3","input":"smoke"}'
```

Tokenizer-count smoke:

```bash
curl -sS -X POST http://127.0.0.1:8787/internal/token-count \
  -H "Authorization: Bearer <gateway-api-key>" \
  -H 'content-type: application/json' \
  -d '{"model":"text-embedding-bge-m3","input":"smoke"}'
```

Honcho chat smoke, after Honcho is up:

```bash
curl -sS -X POST http://127.0.0.1:8000/v3/workspaces/hermes/peers/honcho-codex-smoke/chat \
  -H 'content-type: application/json' \
  -d '{"query":"Reply exactly: smoke ok","stream":false,"reasoning_level":"minimal"}'
```

## Notes and limitations

- The default install is local-only and single-user oriented.
- The gateway binds to `127.0.0.1` by default.
- Existing Honcho databases need extra care if their embedding schema is already populated with a different vector dimension.
- macOS and Windows Docker Desktop may work, but this README only claims Linux testing.
- This project depends on user-owned OAuth credentials. Do not share, pool, rotate, or resell credentials.

## License and provenance

This repository is licensed under AGPL-3.0-or-later. The license is chosen to stay compatible with Honcho's AGPL-3.0 codebase while allowing MIT-licensed Hermes-derived OAuth/auth patterns to be redistributed as part of the combined work.

The Codex OAuth/auth handling in this project references and adapts patterns from Hermes Agent's OpenAI Codex OAuth code. Hermes Agent is an MIT-licensed project by Nous Research.

This is not an official OpenAI, Honcho, Hermes Agent, Nous Research, or Plastic Labs project.

Parts of this repository, including documentation drafts, were generated or edited with AI assistance under maintainer review. See `NOTICE.md` for attribution and provenance details.
