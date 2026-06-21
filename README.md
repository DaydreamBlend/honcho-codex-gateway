# Honcho Codex Gateway

**This repository was created with AI assistance. This README is also a temporary AI-generated README, and I plan to rewrite it manually later.**

**Language:** English | [한국어](README.ko.md)

Local, single-user, OpenAI-compatible gateway for Honcho Docker quick installs.

- Chat Completions: `/v1/chat/completions` uses a user-owned Codex OAuth credential and the Responses conversion pattern used by Hermes Agent, adapted for this gateway.
- Embeddings: `/v1/embeddings` proxies to a llama.cpp server using a GGUF embedding model. The current supported embedding backend is GGUF via llama.cpp only.
- Safety posture: separate Docker stack, localhost-only published port by default, local `GATEWAY_API_KEY`, no credential pooling, no hosted/public proxy intent.

This is not an official OpenAI, Honcho, or Hermes Agent project. It is not an OpenAI API replacement. Use only with your own account/credentials and comply with applicable terms.

## License and provenance

This repository is licensed under **AGPL-3.0-or-later**. The license is chosen to stay compatible with Honcho's AGPL-3.0 codebase while also allowing MIT-licensed Hermes-derived OAuth/auth patterns to be redistributed as part of the combined work.

Substantial portions of the code and documentation were generated, adapted, or organized with AI assistance in a local Hermes Agent session under DaydreamBlend's direction. See `NOTICE.md` for attribution and provenance details.

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
   - can create/update Honcho `.env` with `--write-honcho-env --honcho-dir ../honcho`
   - writes verbose installer output to `logs/install-*.log`
3. In Honcho, copy docker-compose.yml.example to docker-compose.yml.
4. Ensure the Linux `host.docker.internal:host-gateway` override is present for Honcho `api` and `deriver`.
5. Run docker compose up in Honcho.
6. After Honcho is healthy, run Hermes Honcho setup.
```

Do **not** start Honcho API/deriver once with the default OpenAI embedding config and then switch to BGE-M3 later. Fresh Honcho defaults are OpenAI `text-embedding-3-small` / `1536`; this gateway's default local embedding model is BGE-M3 / `1024`. Starting Honcho before applying the gateway embedding configuration can lead to vector dimension mismatch and migration/re-embedding work later.

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

If you already have the file locally, you can still place or symlink it before running the installer. To disable automatic model download:

```bash
./install.sh --skip-model-download
```

Then run:

```bash
cd <parent-directory>/honcho-codex-gateway
./install.sh --write-honcho-env --honcho-dir ../honcho
```

For installer options:

```bash
./install.sh --help
```

`--write-honcho-env` creates Honcho `.env` from `.env.template` when needed, or updates an existing `.env` after writing a timestamped `.env.bak.honcho-codex-gateway-*` backup. It only manages the generated gateway-related keys; review the result before starting Honcho.

The installer keeps noisy setup/build output in `logs/install-*.log` and keeps the final console summary focused on the Honcho `.env` location and Codex OAuth status. If the current user cannot access `/var/run/docker.sock`, it prompts with `sudo -v` and runs Docker Compose through `sudo docker compose`.

The installer starts a **separate** Docker Compose project for the gateway and llama.cpp GGUF embedding server:

```bash
docker compose -p honcho-codex-gateway up -d --build
```

It publishes only the gateway on localhost:

```text
http://127.0.0.1:8787
```

From Honcho containers, use this OpenAI-compatible base URL:

```text
http://host.docker.internal:8787/v1
```

On Linux, add this provider-networking override to Honcho `api` and `deriver` services in `docker-compose.yml` or a compose override. Linux Docker does not provide `host.docker.internal` consistently unless `host-gateway` is configured. This repository has been developed/tested on Linux; macOS and Windows Docker Desktop have not been tested here:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

That is not grafting gateway services into the Honcho stack; it only lets Honcho containers reach the host-local provider URL. Treat this Linux override as required for the documented setup unless your Docker environment already resolves `host.docker.internal` correctly.

### 3. Convert Honcho `.env.template` to `.env` with gateway settings

Now prepare Honcho, but **do not run `docker compose up` until after this edit**. If you used `--write-honcho-env --honcho-dir <parent-directory>/honcho`, the gateway block has already been applied and a backup was written for any pre-existing `.env`.

```bash
cd <parent-directory>/honcho
cp docker-compose.yml.example docker-compose.yml
# Only needed if you did not use --write-honcho-env:
cp .env.template .env
```

`./install.sh` saves the generated `.env` block to `logs/honcho-env.latest.txt`. Apply that block to Honcho `.env` while you would normally fill `LLM_OPENAI_API_KEY` / `LLM_ANTHROPIC_API_KEY` / `LLM_GEMINI_API_KEY`, unless you let the installer write Honcho `.env` directly.

Minimum shape:

```env
LLM_OPENAI_API_KEY=<gateway-api-key-from-honcho-codex-gateway-.env>

DIALECTIC_LEVELS__minimal__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL=gpt-5.4-mini
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__OVERRIDES__BASE_URL=http://host.docker.internal:8787/v1
# repeat same transport/model/base_url pattern for dialectic low/medium/high/max,
# summary, deriver, dream deduction, and dream induction

EMBEDDING_MODEL_CONFIG__TRANSPORT=openai
EMBEDDING_MODEL_CONFIG__MODEL=text-embedding-bge-m3
EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL=http://host.docker.internal:8787/v1
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
- Honcho containers reach the gateway through `http://host.docker.internal:8787/v1` with the Linux `host-gateway` override shown above.

macOS and Windows Docker Desktop may handle `host.docker.internal` differently and have not been tested for this repository yet.

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
