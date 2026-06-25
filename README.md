# Honcho Codex Gateway

**Language:** English | [한국어](README.ko.md)

**Notice (2026-06-25): Since yesterday, the installer had a model path bug that could write `EMBEDDING_GGUF_PATH=models/bge-m3-FP16.gguf` instead of `EMBEDDING_GGUF_PATH=./models/bge-m3-FP16.gguf` when using the base embedding model. This has been fixed and verified by deleting both the `honcho/` checkout and this gateway checkout, cloning them fresh, and installing with the base embedding model successfully.**

**Notice (2026-06-25): The first public networking flow used `host.docker.internal:8787` from Honcho containers while the gateway was published only on host-local `127.0.0.1:8787`, which could make Honcho chat and embedding requests time out from inside Docker. This has been fixed by routing the two separate Compose stacks over a shared Docker network named `honcho-codex-gateway`; Honcho now uses `http://codex-gateway:8787/v1`. The fix was verified from inside the Honcho `api` container with `http://codex-gateway:8787/health`.**

Honcho Codex Gateway is a local-only helper for bootstrapping self-hosted Honcho with Codex-backed chat completions and local GGUF/llama.cpp embeddings.

It is intended for local, single-user experimentation with your own credentials, especially when setting up Honcho for Hermes-style personal agent memory. It is not a hosted API service, public proxy, credential-sharing tool, or production replacement for the official OpenAI API.

- Chat Completions: `/v1/chat/completions` uses a user-owned Codex OAuth credential and the Responses conversion pattern used by Hermes Agent, adapted for this gateway.
- Embeddings: `/v1/embeddings` proxies to a llama.cpp server using a GGUF embedding model. The current supported embedding backend is GGUF via llama.cpp only.
- Safety posture: separate Docker stack, localhost-only published port by default, local `GATEWAY_API_KEY`, no credential pooling, no hosted/public proxy intent.

This is not an official OpenAI, Honcho, Hermes Agent, Nous Research, or Plastic Labs project. Use only with your own account/credentials and comply with applicable terms.

## What this project is

- A local bootstrap/helper layer for Honcho Docker quick-install style setups.
- A convenience gateway for single-user development and experimentation.
- A way to pair Honcho's OpenAI-compatible chat provider configuration with local GGUF/llama.cpp embeddings.
- A narrow helper for personal memory-stack experiments, not a general OpenAI-compatible platform.

## What this project is not

This project is not:

- a hosted API service;
- a credential pooling service;
- a multi-user proxy;
- a resale layer;
- a rate-limit bypass mechanism;
- a scraping, bulk extraction, or data-harvesting tool;
- a production replacement for the official OpenAI API;
- a general-purpose OpenAI-compatible gateway for arbitrary applications.

## Safety and acceptable use

This project is intended for local, single-user experimentation with the user's own credentials. It does not attempt to bypass rate limits, share credentials, pool accounts, resell access, or provide a hosted API service.

Do not expose this gateway publicly. Do not share, pool, rotate, or resell credentials. Do not use it for automated scraping, bulk output extraction, or data harvesting. For production, commercial, multi-user, CI/CD, or hosted usage, use officially supported APIs and authentication flows where applicable. Users are responsible for complying with the terms of the services they connect.

## Compatibility status

| Component | Status |
| --- | --- |
| Honcho Docker quick install | Primary target |
| Fresh Honcho database | Recommended |
| Existing Honcho database | Risk of embedding dimension mismatch |
| Linux | Tested / primary target |
| macOS | Untested / experimental |
| Windows / WSL2 | Untested / experimental |
| Public hosted deployment | Not supported |
| Multi-user deployment | Not supported |
| Production API replacement | Not supported |

## Why this exists

Most Codex OAuth gateway projects focus on exposing Codex or ChatGPT OAuth-backed chat as an OpenAI-compatible API. Honcho needs a little more than that for a clean Docker quick install: it needs a chat provider and an embeddings provider with compatible vector dimensions from the first startup.

This project packages that boundary for Honcho specifically: Codex OAuth-backed chat completions on one side, and a local llama.cpp/GGUF embeddings proxy on the other, both behind the same local OpenAI-compatible `/v1` surface.

Unlike general Codex OAuth gateways, this project also provides a local `/v1/embeddings` route backed by llama.cpp/GGUF, because Codex OAuth gateways generally cover chat/responses rather than embeddings.

## Security and limitations

See [`SECURITY.md`](SECURITY.md) for secret-handling and local-exposure guidance. See [`LIMITATIONS.md`](LIMITATIONS.md) for experimental status, compatibility limits, and embedding-dimension caveats.

## License and provenance

This repository is licensed under **AGPL-3.0-or-later**. The license is chosen to stay compatible with Honcho's AGPL-3.0 codebase while also allowing MIT-licensed Hermes-derived OAuth/auth patterns to be redistributed as part of the combined work.

**AI assistance notice:** Parts of this repository, including documentation drafts, were generated or edited with AI assistance under maintainer review. The maintainer plans to revise the README manually over time.

See `NOTICE.md` for attribution and provenance details.

## Install: Honcho Docker quick install, gateway first

This project is designed to fit Honcho's Docker quick install:

```bash
git clone https://github.com/plastic-labs/honcho.git
cd honcho
cp docker-compose.yml.example docker-compose.yml
cp .env.template .env       # normally fill in LLM_* keys here
docker compose up
```

The only change is the order: **clone both repos, start and authenticate the gateway first, then edit Honcho `.env`, and finally run `docker compose up` in the Honcho repo.**

Recommended sibling layout:

```text
<parent-directory>/
  honcho/
  honcho-codex-gateway/
```

Correct fresh order:

```text
1. Clone Honcho and honcho-codex-gateway as sibling directories.
2. Run honcho-codex-gateway/install.sh first.
   - prepares gateway .env/.auth/models
   - installs gateway Python entrypoints
   - runs Codex OAuth login unless skipped
   - starts the separate gateway + llama.cpp GGUF embedding Docker stack
   - creates Honcho `.env` from `.env.template` when needed
   - creates Honcho `docker-compose.yml` from `docker-compose.yml.example` when needed
   - attaches Honcho `api` and `deriver` to the shared `honcho-codex-gateway` Docker network
   - writes verbose installer output to `logs/install-*.log`
3. Review Honcho `.env` / `docker-compose.yml`, then run docker compose up in Honcho.
4. After Honcho is healthy, run Hermes Honcho setup.
```

### Important: embedding dimensions must match from first startup

Do **not** start Honcho API/deriver once with the default OpenAI embedding config and then switch to BGE-M3 later. Honcho may initialize its database/vector index based on the first embedding provider/model dimensions. OpenAI `text-embedding-3-small` commonly uses `1536` dimensions, while this gateway's default local BGE-M3 embedding model uses `1024`.

If the database has already been initialized with one dimension, switching later may fail or require a database reset, migration, or re-embedding work. Configure the desired embedding provider before the first Honcho startup whenever possible.

### 1. Clone both repos

```bash
mkdir -p ./honcho-local
cd ./honcho-local
git clone https://github.com/plastic-labs/honcho.git
git clone https://github.com/DaydreamBlend/honcho-codex-gateway.git
```

If `honcho-codex-gateway` is already a local working copy, just keep it next to `honcho`.

### 2. Prepare the gateway Docker stack first

The installer downloads the default GGUF automatically if it is missing:

```text
model: gpustack/bge-m3-GGUF / bge-m3-FP16.gguf
license: MIT, inherited from BAAI/bge-m3 and the GGUF model card
path: <parent-directory>/honcho-codex-gateway/models/bge-m3-FP16.gguf
```

When run in a terminal, `install.sh` asks which embedding GGUF to use: download the bundled BGE-M3 default, copy an existing local GGUF into `./models/`, or paste a Hugging Face URL. A direct Hugging Face `.gguf` file URL is downloaded immediately; a Hugging Face repo/tree URL lists available `.gguf` files and asks which one to use. Non-Hugging Face URLs are rejected. The selected file is written to `EMBEDDING_GGUF_PATH` so Docker Compose mounts it into the llama.cpp server.

To use flags instead of the interactive menu, pass the model options explicitly. For example:

```bash
./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions auto
# or, if metadata detection is not available for that file:
./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions 768
```

When using a custom `--model-url`, also pass `--model-sha256 SHA256`; use `--model-sha256 ''` only when you intentionally accept downloading without checksum verification.

By default, the installer uses the bundled `bge-m3-fp16` embedding preset and sets `EMBEDDING_VECTOR_DIMENSIONS` from GGUF metadata when possible, falling back to the preset's `1024` dimension.

When `--write-honcho-env` updates an existing Honcho `.env`, the installer refuses to overwrite a different existing `EMBEDDING_VECTOR_DIMENSIONS` value unless `--force-embedding-dimension-change` is provided. Treat that flag as a migration/re-embedding escape hatch, not a normal install option.

Then run:

```bash
cd <parent-directory>/honcho-codex-gateway
sudo ./install.sh
```

For installer options:

```bash
./install.sh --help
```

`install.sh` auto-detects a sibling Honcho checkout such as `../honcho`. It creates Honcho `.env` from `.env.template` when needed, or updates an existing `.env` after writing a timestamped `.env.bak.honcho-codex-gateway-*` backup. It also creates Honcho `docker-compose.yml` from `docker-compose.yml.example` when needed, then attaches `api` and `deriver` to the shared external `honcho-codex-gateway` Docker network; existing compose files are backed up before patching. If Honcho is not next to this repository, pass `--honcho-dir /path/to/honcho`; use `--no-write-honcho-env` to opt out. Review both files before starting Honcho.

The installer keeps noisy setup/build output in `logs/install-*.log` and keeps the final console summary focused on the Honcho `.env` location and Codex OAuth status. If the current user cannot access `/var/run/docker.sock`, it prompts with `sudo -v` and runs Docker Compose through `sudo docker compose`.

The installer starts a **separate** Docker Compose project for the gateway and llama.cpp GGUF embedding server:

```bash
docker compose -p honcho-codex-gateway up -d --build
```

It publishes only the gateway on localhost:

```text
http://127.0.0.1:8787
```

The bundled llama.cpp embedding server is started with an 8192-token context window for BGE-M3 embeddings and a larger physical batch size so borderline chunks that tokenize slightly above 8192 do not fail reconciliation:

```text
--ctx-size 8192
--batch-size 16384
--ubatch-size 16384
```

This is intentional: Honcho's generated embedding config uses `MAX_INPUT_TOKENS=8192`, so the embedding server context window must not remain at a smaller default such as 4096. The physical batch size is higher than the nominal context window because llama.cpp may count some reconciler chunks slightly above 8192 tokens.

From Honcho containers, use this OpenAI-compatible base URL:

```text
http://codex-gateway:8787/v1
```

The gateway stack creates a shared Docker network named `honcho-codex-gateway`. When Honcho integration is enabled, the installer creates Honcho `docker-compose.yml` from `docker-compose.yml.example` when needed, then attaches Honcho `api` and `deriver` to that external network while preserving their default Honcho network:

```yaml
services:
  api:
    networks:
      - default
      - honcho-codex-gateway
  deriver:
    networks:
      - default
      - honcho-codex-gateway

networks:
  honcho-codex-gateway:
    external: true
```

That is not grafting gateway services into the Honcho stack; it only lets the two separate Compose stacks communicate by Docker service DNS name. The gateway remains published to the host on `127.0.0.1:8787` for local smoke tests, but Honcho containers should use `http://codex-gateway:8787/v1` over the shared network instead of `host.docker.internal`.

### 3. Review generated Honcho files

Do **not** run Honcho `docker compose up` before the gateway installer has prepared Honcho config. With the recommended command above, the installer already:

- creates Honcho `.env` from `.env.template` when missing;
- creates Honcho `docker-compose.yml` from `docker-compose.yml.example` when missing;
- backs up existing `.env` / compose files before modifying them;
- writes the generated provider block to `logs/honcho-env.latest.txt` for review.

If you intentionally did not use `--write-honcho-env`, apply the saved block manually while you would normally fill `LLM_OPENAI_API_KEY` / `LLM_ANTHROPIC_API_KEY` / `LLM_GEMINI_API_KEY`.

Minimum shape:

```env
LLM_OPENAI_API_KEY=<gateway-api-key-from-honcho-codex-gateway-.env>

DIALECTIC_LEVELS__minimal__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL=gpt-5.4-mini
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__OVERRIDES__BASE_URL=http://codex-gateway:8787/v1
# repeat same transport/model/base_url pattern for dialectic low/medium/high/max,
# summary, deriver, dream deduction, and dream induction

EMBEDDING_MODEL_CONFIG__TRANSPORT=openai
EMBEDDING_MODEL_CONFIG__MODEL=text-embedding-bge-m3
EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL=http://codex-gateway:8787/v1
EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY_ENV=LLM_OPENAI_API_KEY
EMBEDDING_VECTOR_DIMENSIONS=1024
EMBEDDING_MODEL_CONFIG__DIMENSIONS_MODE=never
```

### 4. Start Honcho Docker quick install

After `.env` points LLM + embeddings at the gateway. Honcho's upstream Docker compose exposes the API on `127.0.0.1:8000`, so the self-hosted API URL is normally `http://localhost:8000`.

```bash
cd <parent-directory>/honcho
docker compose up
```

For detached mode:

```bash
docker compose up -d
```

If Honcho's Docker quick install does not run `scripts/configure_embeddings.py` automatically for non-1536 embeddings, run the equivalent command inside the Honcho API image/container before API/deriver write embeddings. The invariant is:

```text
Honcho .env gateway settings first → Honcho startup/migrations → empty embedding columns configured to 1024 → API/deriver writes data
```

For an already-running Honcho with populated embeddings, do **not** treat this as an in-place migration. Stand up a fresh deployment, replay/re-embed data, and cut over.

### 5. Run Hermes + Honcho setup

After Honcho is healthy, follow the Hermes integration guide:

```bash
hermes honcho setup
hermes honcho status
```

Point Hermes at the Honcho API URL you started, for example:

```text
http://localhost:8000
```

Exact URL/JWT/workspace/session choices depend on your Honcho deployment and Hermes profile. Run this only after Honcho `/health` is OK; otherwise you will be debugging two independent bootstraps at the same time.

## Tested environment

This repository has been developed and smoke-tested on Linux only:

- Host OS: Linux
- Runtime hardware: GB10-based MSI EdgeXpert 1TB model
- Honcho upstream Docker compose API port: `127.0.0.1:8000:8000`
- Gateway Docker compose published port: `127.0.0.1:8787:8787`
- Honcho containers reach the gateway through `http://codex-gateway:8787/v1` on the shared `honcho-codex-gateway` Docker network.

macOS and Windows Docker Desktop have not been smoke-tested for this repository yet; the documented cross-stack path is Docker network DNS, not `host.docker.internal`.

## Smoke tests

Gateway only:

```bash
curl -sS http://127.0.0.1:8787/health
# For /v1/* routes, include an HTTP Authorization Bearer header using GATEWAY_API_KEY from gateway .env.
curl -sS http://127.0.0.1:8787/v1/models \
  -H "<gateway authorization header>"
curl -sS -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H "<gateway authorization header>" \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-5.4-mini","messages":[{"role":"user","content":"Reply exactly: smoke ok"}]}'
```

Embedding via gateway requires the embedding server/model to be running:

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/embeddings \
  -H "<gateway authorization header>" \
  -H 'content-type: application/json' \
  -d '{"model":"text-embedding-bge-m3","input":"smoke"}'
```

Honcho after startup:

```bash
curl -sS http://localhost:8000/health
```

Then use the Honcho API or Hermes Honcho setup/status to verify memory operations.
