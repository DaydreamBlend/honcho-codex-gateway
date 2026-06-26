# Honcho Codex Gateway

**언어:** [English](README.md) | 한국어

Honcho Codex Gateway는 self-hosted Honcho를 Codex-backed chat completions와 local GGUF embeddings로 실행하기 위한 local gateway입니다.

목표 범위는 좁습니다. Honcho Docker quick install, 사용자 본인의 Codex OAuth login을 쓰는 chat route, 그리고 BGE-M3 또는 다른 GGUF embedding model을 돌리는 local llama.cpp embedding server입니다. Hosted API service나 범용 OpenAI-compatible proxy가 아닙니다.

## 하는 일

- Honcho가 호출할 `/v1/chat/completions` endpoint를 제공합니다. Chat backend는 local Codex OAuth credential입니다.
- `/v1/embeddings` endpoint를 제공합니다. Embedding backend는 local llama.cpp GGUF embedding server입니다.
- Honcho `.env`에 chat, summary, deriver, dream, embedding provider 설정을 씁니다.
- Honcho container가 gateway에 접근할 수 있도록 Honcho `docker-compose.yml`에 shared Docker network 설정을 patch합니다.
- GGUF embedding에서 Honcho가 `tiktoken` 추정값만 믿지 않도록, 작은 reversible tokenizer patch를 적용합니다.

## 하지 않는 일

이 프로젝트는 다음이 아닙니다.

- hosted API service
- credential pooling 또는 account sharing tool
- rate-limit bypass
- scraping 또는 data harvesting tool
- official API의 production replacement
- arbitrary multi-user application을 위한 general proxy

본인 credential로 local에서 사용하세요. Public internet에 노출하지 마세요.

## 현재 상태

| 항목 | 상태 |
| --- | --- |
| Linux + Docker Compose | 테스트됨 |
| Honcho Docker quick install | 주요 대상 |
| Fresh Honcho database | 권장 |
| Existing Honcho database | 가능하지만 embedding dimension 변경은 주의 필요 |
| Default embedding model | BGE-M3 FP16 GGUF, 1024 dimensions |
| macOS / Windows / WSL2 | 아직 미검증 |
| Public hosted deployment | 지원하지 않음 |

Default install은 다음 경로로 smoke-tested 되었습니다.

- Honcho API health: `127.0.0.1:8000`
- Gateway health: `127.0.0.1:8787`
- Codex-backed Honcho chat
- 1024-dimensional BGE-M3 embeddings
- llama.cpp/GGUF token count를 반환하는 gateway `/internal/token-count`
- Honcho queue drain to zero pending work units

## 빠른 설치

Honcho와 이 gateway를 sibling directory로 clone합니다.

```bash
git clone https://github.com/plastic-labs/honcho.git
git clone https://github.com/DaydreamBlend/honcho-codex-gateway.git
cd honcho-codex-gateway
sudo ./install.sh
```

`sudo ./install.sh`는 다음을 처리합니다.

1. 사용할 embedding GGUF model을 묻습니다.
2. `--skip-auth`를 쓰지 않았다면 Codex OAuth login을 실행합니다.
3. Gateway `.env`, `.auth/`, `models/`, local Python environment를 준비합니다.
4. Honcho `.env`를 생성하거나 업데이트합니다.
5. Shared Docker network를 위해 Honcho `docker-compose.yml`을 생성하거나 patch합니다.
6. Reversible Honcho tokenizer patch를 적용합니다.
7. 다음에 실행할 Docker Compose 명령을 출력합니다.

그 다음 두 stack을 이 순서대로 시작합니다.

```bash
cd <parent-directory>/honcho-codex-gateway
sudo docker compose up -d --build

cd <parent-directory>/honcho
sudo docker compose up -d --build
```

순서가 중요합니다. Gateway stack이 shared Docker network와 Honcho가 접근할 `codex-gateway` service를 만듭니다.

## tokenizer patch가 필요한 이유

Upstream Honcho의 embedding chunker는 token count를 `tiktoken`으로 추정합니다. OpenAI embeddings에서는 괜찮지만, 이 gateway의 default embedding backend는 llama.cpp/GGUF 기반 BGE-M3입니다. Log-heavy text나 mixed text에서는 `tiktoken`이 GGUF tokenizer보다 적게 세는 경우가 있습니다. 그러면 Honcho는 안전하다고 생각한 chunk를 만들지만, llama.cpp는 너무 길다고 거부할 수 있습니다.

이 gateway는 proxy 안에서 긴 input을 쪼갠 뒤 embedding을 평균내지 않습니다. Retrieval semantics가 달라질 수 있기 때문입니다. 대신 installer가 Honcho에 작은 patch를 적용합니다.

```text
Honcho chunker
  -> gateway /internal/token-count
  -> llama.cpp /tokenize
  -> GGUF token count
```

Honcho는 여전히 직접 여러 embedding chunk를 만듭니다. Gateway는 backend token count만 알려줍니다.

Patch는 marker가 있고 idempotent합니다. Honcho update로 patch가 사라졌다면 다시 실행하세요.

```bash
cd <parent-directory>/honcho-codex-gateway
sudo ./install.sh
```

필요하면 installer가 patch를 다시 적용합니다.

## embedding dimensions는 첫 Honcho startup 전에 맞추세요

기본 OpenAI embedding 설정으로 Honcho를 한 번 시작한 뒤 나중에 BGE-M3로 바꾸지 마세요. Honcho는 처음 설정된 embedding dimension을 기준으로 database/vector schema를 초기화할 수 있습니다.

Bundled BGE-M3 GGUF model은 1024-dimensional vector를 반환합니다. 일부 OpenAI embedding model은 1536 dimensions를 사용합니다. Data가 이미 쓰인 뒤 dimension을 바꾸려면 reset, migration, re-embedding이 필요할 수 있습니다.

가장 안전한 흐름은 첫 Honcho startup 전에 gateway installer를 실행하는 것입니다.

## custom GGUF model

Default installer는 다음 model을 다운로드합니다.

```text
model: gpustack/bge-m3-GGUF / bge-m3-FP16.gguf
license: MIT, BAAI/bge-m3와 GGUF model card에서 이어짐
path: ./models/bge-m3-FP16.gguf
```

Local GGUF를 `./models/` 아래로 복사하거나, Hugging Face GGUF URL을 줄 수도 있습니다. Direct `.gguf` URL은 바로 받습니다. Repo/tree URL을 넣으면 사용 가능한 `.gguf` file 목록을 보여주고 선택하게 합니다.

Scripted install 예시:

```bash
sudo ./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions auto
```

Dimension detection을 사용할 수 없으면 dimension을 직접 지정하세요.

```bash
sudo ./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions 768
```

Custom download에는 checksum을 같이 넘기세요.

```bash
sudo ./install.sh --model-url <hugging-face-gguf-url> --model-sha256 <sha256>
```

Checksum 없이 받겠다고 의도적으로 결정한 경우에만 `--model-sha256 ''`를 사용하세요.

## runtime topology

Gateway는 별도 Compose stack으로 실행됩니다. Honcho는 upstream에 가깝게 유지하고, external Docker network로 gateway stack에 붙습니다.

```text
Honcho api / deriver
  -> http://codex-gateway:8787/v1
  -> honcho-codex-gateway stack
       - codex-gateway
       - embedding-server
```

Gateway는 local smoke test를 위해 host에도 publish됩니다.

```text
http://127.0.0.1:8787
```

Honcho container는 shared network의 Docker DNS를 사용해야 합니다.

```text
http://codex-gateway:8787/v1
```

Linux setup에서는 Honcho container를 `host.docker.internal`로 보내지 마세요. Gateway host port는 local-only exposure를 위해 `127.0.0.1`에 bind됩니다.

## Honcho config shape

Installer가 full block을 쓰지만, 핵심은 다음 형태입니다.

```env
LLM_OPENAI_API_KEY=<gateway-api-key-from-honcho-codex-gateway-.env>

DIALECTIC_LEVELS__minimal__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL=gpt-5.4-mini
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__OVERRIDES__BASE_URL=http://codex-gateway:8787/v1
# dialectic low/medium/high/max, summary, deriver, dream deduction,
# dream induction에도 같은 transport/model/base_url pattern을 씁니다.

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

## smoke tests

Gateway health:

```bash
curl -sS http://127.0.0.1:8787/health
```

Honcho health:

```bash
curl -sS http://127.0.0.1:8000/health
```

`/v1/*` gateway endpoint는 gateway `.env`의 `GATEWAY_API_KEY`를 사용한 Authorization header가 필요합니다.

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

Honcho chat smoke:

```bash
curl -sS -X POST http://127.0.0.1:8000/v3/workspaces/hermes/peers/honcho-codex-smoke/chat \
  -H 'content-type: application/json' \
  -d '{"query":"Reply exactly: smoke ok","stream":false,"reasoning_level":"minimal"}'
```

## notes and limitations

- Default install은 local-only, single-user use를 전제로 합니다.
- Gateway는 기본적으로 `127.0.0.1`에 bind됩니다.
- Existing Honcho database에 이미 다른 vector dimension의 embedding schema가 채워져 있다면 추가 작업이 필요합니다.
- macOS와 Windows Docker Desktop은 아직 테스트하지 않았습니다.
- 이 프로젝트는 사용자 본인의 OAuth credential에 의존합니다. Credential을 공유, pooling, rotation, resale하지 마세요.

## license and provenance

이 저장소는 AGPL-3.0-or-later로 라이선스됩니다. Honcho의 AGPL-3.0 codebase와 호환성을 유지하면서 MIT-licensed Hermes-derived OAuth/auth pattern을 combined work의 일부로 재배포할 수 있도록 이 라이선스를 사용합니다.

이 프로젝트는 OpenAI, Honcho, Hermes Agent, Nous Research, Plastic Labs의 공식 프로젝트가 아닙니다.

이 저장소의 일부 코드와 문서 초안은 maintainer 검토하에 AI 도움을 받아 작성 또는 수정되었습니다. Attribution과 provenance detail은 `NOTICE.md`를 참고하세요.
