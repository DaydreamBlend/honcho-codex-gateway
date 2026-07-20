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
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL=gpt-5.6-terra
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

The `DIALECTIC_LEVELS__minimal__...` lines assign a model to the `minimal` tier;
they do not make `minimal` the active default. Honcho chooses a tier for each chat,
and its upstream default is `low`.

## Chat model pass-through

For `/v1/chat/completions`, the gateway forwards Honcho's `model` value unchanged to the authenticated Codex Responses backend. It does not keep a chat-model allowlist, alias map, or silent fallback. Model availability is decided by the current Codex account/catalog.

Because that upstream catalog can change independently, `/v1/models` only lists the local embedding model. The installer's default Honcho chat model is `gpt-5.6-terra`; select another upstream model explicitly with `--chat-model`.

```bash
sudo ./install.sh --chat-model gpt-5.6-terra
```

### Why Terra is the default

As verified on 2026-07-20, the authenticated Codex catalog still returned
`gpt-5.4-mini`, but marked it `visibility=hide`, `supported_in_api=true`, and
`use_responses_lite=false`. Its `upgrade` metadata points to `gpt-5.6-luna` and
the migration copy says that Mini is no longer available. This explains why Mini
is absent from the normal Codex OAuth model picker even though an explicit legacy
request can still succeed. In live controls, the gateway sent
`model=gpt-5.4-mini` unchanged and the response still reported
`model=gpt-5.4-mini`; the gateway did not fall back to Luna or Terra.

That response label does not prove which internal OpenAI deployment or weights
served the request. The backend may retain a compatibility route or alias that
is not externally observable, so this project does not treat hidden Mini as a
supported production default. In the official Codex client source,
[`visibility` controls whether a model appears in the picker](https://github.com/openai/codex/blob/3e2f79727a4e8ddfc8e3acb838d496b121094b9e/codex-rs/protocol/src/openai_models.rs#L622-L633),
while `upgrade` drives an explicit client-side migration prompt; the
[configured model changes when that migration is accepted](https://github.com/openai/codex/blob/3e2f79727a4e8ddfc8e3acb838d496b121094b9e/codex-rs/tui/src/app/startup_prompts.rs#L182-L203).
Those code paths do not establish a transparent server-side alias.

Luna is the catalog's advertised Mini successor, but truthful
`originator=honcho_codex_gateway` controls reproduced intermittent upstream
`response.failed(server_error)` events after about 31 seconds. Terra is visible,
`supported_in_api=true`, and completed the corresponding plain and two-round
tool-loop controls without that failure pattern. The installer therefore uses
Terra explicitly instead of relying on hidden Mini, silently substituting a
model, or impersonating the official Codex client.

## Updating Honcho and switching an existing install to Terra

The tokenizer patch intentionally modifies `src/embedding_client.py`, so restore that generated patch before pulling Honcho. Stop if `git status` shows unrelated tracked changes.

```bash
# 1. Update the Honcho checkout.
cd /path/to/honcho
git status --short
git restore src/embedding_client.py
rm -f src/embedding_client.py.bak.honcho-codex-gateway-*
git pull --ff-only

# 2. Update the gateway, rewrite all nine Honcho chat routes to Terra,
#    and reapply the tokenizer/Compose integration patches.
cd ../honcho-codex-gateway
git pull --ff-only
sudo ./install.sh \
  --honcho-dir ../honcho \
  --chat-model gpt-5.6-terra \
  --skip-auth \
  --non-interactive

# 3. Rebuild the gateway first, then Honcho.
sudo docker compose up -d --build
cd ../honcho
sudo docker compose up -d --build
```

`--skip-auth` preserves the existing Codex OAuth login. Omit it only when re-authentication is needed. The installer backs up Honcho `.env`, updates Dialectic minimal/low/medium/high/max, Summary, Deriver, and both Dream routes, then reapplies the GGUF tokenizer patch.

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

Direct Terra chat through the gateway:

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer ***" \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-5.6-terra","messages":[{"role":"user","content":"Reply exactly: terra ok"}]}'
```

The gateway preserves the requested model name and selects the upstream Responses
protocol profile from the authenticated Codex model catalog. The default
`CODEX_GATEWAY_RESPONSES_PROFILE=auto` queries `/models` once per process using
`CODEX_GATEWAY_CLIENT_VERSION` and reads each model's `use_responses_lite` flag.
The same protocol version is sent with the gateway's own
`CODEX_GATEWAY_ORIGINATOR=honcho_codex_gateway` identity; the gateway does not
impersonate the official Codex CLI. It does not maintain a chat-model allowlist
or alias table. An unlisted future model is still passed through and uses the
standard Full Responses profile.

For a catalog model marked `use_responses_lite=true`, the live client adds the
Responses Lite header, moves top-level instructions into a developer input item,
sets `reasoning.context=all_turns`, and forces `parallel_tool_calls=false`. Models
marked `false` keep the Full Responses request shape. Operators can use
`CODEX_GATEWAY_RESPONSES_PROFILE=full` or `lite` only as an explicit recovery
override when catalog discovery is unavailable.

### Honcho Dialectic level vs model reasoning effort

These are independent controls even when both happen to use words such as `low`:

| Control | Layer | Values | Default or policy |
| --- | --- | --- | --- |
| Honcho `reasoning_level` | Dialectic orchestration: context retrieval, tools, and iteration limits | `minimal`, `low`, `medium`, `high`, `max` | Upstream Honcho defaults to `low` |
| Model `thinking_effort` / `reasoning_effort` | Provider-side model compute | Backend-specific; Codex currently uses values such as `none`, `low`, `medium`, `high`, `xhigh` | Explicit values pass through; this gateway chooses a policy only when Honcho omits the field |

In the upstream Honcho revision used by the original 5.4 Mini setup (`60a15e6`),
both the [API schema](https://github.com/plastic-labs/honcho/blob/60a15e6/src/schemas/api.py#L564-L566)
and the [Dialectic agent](https://github.com/plastic-labs/honcho/blob/60a15e6/src/dialectic/core.py#L62-L70)
defaulted to `low`. `minimal` was a separate explicit tier. All five tiers pointed
to `gpt-5.4-mini`, so selecting that model did not select `minimal`; the
[tier configuration](https://github.com/plastic-labs/honcho/blob/60a15e6/src/config.py#L946-L982)
gave `minimal` one tool iteration and a 250-token output cap, while `low` allowed
up to five tool iterations. A caller can still override the tier per request;
that choice remains independent from the model mapped to the tier.

Honcho serializes `ModelConfig.thinking_effort` as the Chat Completions
`reasoning_effort` field. The original 5.4 Mini model config left it unset, and
Honcho's [OpenAI backend](https://github.com/plastic-labs/honcho/blob/60a15e6/src/llm/backends/openai.py#L336-L337)
omitted the wire field; that is not the same contract as explicit
`reasoning_effort="none"`. For omitted fields, this gateway currently uses
`CODEX_GATEWAY_REASONING_EFFORT` (default `none`) for tool-less requests and
`CODEX_GATEWAY_TOOL_REASONING_EFFORT` (default `low`) when tool definitions or
tool-call history are present. Explicit effort values are forwarded unchanged.

The adapter sends only the selected effort and omits `reasoning.summary` plus
`reasoning.encrypted_content` for every effort. This Chat Completions facade cannot
carry those Responses artifacts into the next round, and requesting them caused
reproducible late streaming failures.

This omitted-effort policy keeps both selection and final synthesis on the lowest
currently proven tool-capable effort. Correct Responses Lite formatting
removes the old Full/Lite mismatch, but the Codex OAuth backend can still return
intermittent late `server_error` events independently of the selected effort.
For the compatibility and reliability reasons above, the installer defaults to
`gpt-5.6-terra`. Luna remains available as an explicit
`--chat-model gpt-5.6-luna` selection; the gateway never substitutes models
silently.

The current Codex backend for `gpt-5.6-luna` rejects the literal model field
`reasoning_effort="minimal"`; its HTTP error reports `none`, `low`, `medium`,
`high`, and `xhigh` as supported Responses API efforts. This does not invalidate
Honcho's agent-level `reasoning_level="minimal"`. The gateway deliberately does
not rewrite any explicitly requested model effort; only omitted effort uses the
gateway policy above.

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

Honcho chat smoke, after Honcho is up. This command explicitly selects `minimal`
to exercise that tier; it is not a test of Honcho's default `low` path. Omit
`reasoning_level` or set it to `low` to test the upstream default.

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
