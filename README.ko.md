# Honcho Codex Gateway

**언어:** [English](README.md) | 한국어

**공지 (2026-06-25): 어제부터 base embedding model 사용 시 installer가 `EMBEDDING_GGUF_PATH=./models/bge-m3-FP16.gguf` 대신 `EMBEDDING_GGUF_PATH=models/bge-m3-FP16.gguf`처럼 model path의 `./`를 빠뜨릴 수 있는 문제가 있었습니다. 이 문제는 수정되었고, 현재는 `honcho/` checkout과 이 gateway checkout을 모두 삭제한 뒤 새로 clone해서 base embedding model로 설치했을 때 문제 없음을 확인했습니다.**

Honcho Codex Gateway는 Codex-backed chat completions와 local GGUF/llama.cpp embeddings를 사용해 self-hosted Honcho를 bootstrap하기 위한 local-only helper입니다.

이 프로젝트는 특히 Hermes-style personal agent memory를 위해 Honcho를 설정할 때, 본인 credential을 사용하는 local single-user experimentation을 의도합니다. Hosted API service, public proxy, credential-sharing tool, 공식 OpenAI API의 production replacement가 아닙니다.

- Chat Completions: `/v1/chat/completions`는 사용자 소유의 Codex OAuth credential과 Hermes Agent에서 사용한 Responses 변환 패턴을 이 gateway에 맞게 조정해 사용합니다.
- Embeddings: `/v1/embeddings`는 GGUF embedding model을 사용하는 llama.cpp server로 proxy합니다. 현재 지원되는 embedding backend는 llama.cpp 기반 GGUF뿐입니다.
- Safety posture: 별도 Docker stack, 기본 localhost-only published port, local `GATEWAY_API_KEY`, credential pooling 없음, hosted/public proxy 의도 없음.

이 프로젝트는 OpenAI, Honcho, Hermes Agent, Nous Research, Plastic Labs의 공식 프로젝트가 아닙니다. 본인 계정/credential로만 사용하고 적용 가능한 약관을 준수하세요.

## What this project is

- Honcho Docker quick-install style setup을 위한 local bootstrap/helper layer입니다.
- Single-user development와 experimentation을 위한 convenience gateway입니다.
- Honcho의 OpenAI-compatible chat provider 설정과 local GGUF/llama.cpp embeddings를 함께 맞추는 도구입니다.
- 범용 OpenAI-compatible platform이 아니라 personal memory-stack experiment를 위한 좁은 helper입니다.

## What this project is not

이 프로젝트는 다음이 아닙니다.

- hosted API service;
- credential pooling service;
- multi-user proxy;
- resale layer;
- rate-limit bypass mechanism;
- scraping, bulk extraction, data-harvesting tool;
- official OpenAI API의 production replacement;
- arbitrary application을 위한 general-purpose OpenAI-compatible gateway.

## Safety and acceptable use

이 프로젝트는 사용자 본인 credential을 사용하는 local single-user experimentation을 의도합니다. Rate limit 우회, credential 공유, account pooling, access resale, hosted API service 제공을 시도하지 않습니다.

이 gateway를 public으로 노출하지 마세요. Credential을 공유, pooling, rotation, resale하지 마세요. Automated scraping, bulk output extraction, data harvesting 용도로 사용하지 마세요. Production, commercial, multi-user, CI/CD, hosted usage에는 가능한 경우 officially supported API와 authentication flow를 사용하세요. 연결하는 service의 약관 준수 책임은 사용자에게 있습니다.

## Compatibility status

| Component | Status |
| --- | --- |
| Honcho Docker quick install | Primary target |
| Fresh Honcho database | Recommended |
| Existing Honcho database | Embedding dimension mismatch risk |
| Linux | Tested / primary target |
| macOS | Untested / experimental |
| Windows / WSL2 | Untested / experimental |
| Public hosted deployment | Not supported |
| Multi-user deployment | Not supported |
| Production API replacement | Not supported |

## Why this exists

대부분의 Codex OAuth gateway 프로젝트는 Codex 또는 ChatGPT OAuth 기반 chat을 OpenAI-compatible API로 노출하는 데 집중합니다. 하지만 Honcho를 Docker quick install로 깔끔하게 붙이려면 첫 시작부터 vector dimension이 맞는 chat provider와 embeddings provider가 모두 필요합니다.

이 프로젝트는 그 provider boundary를 Honcho에 맞게 포장합니다. 한쪽에는 Codex OAuth 기반 chat completions를 두고, 다른 한쪽에는 local llama.cpp/GGUF embeddings proxy를 두어, 둘 다 같은 local OpenAI-compatible `/v1` surface 뒤에 둡니다.

일반적인 Codex OAuth gateway와 달리, 이 프로젝트는 llama.cpp/GGUF 기반 local `/v1/embeddings` route도 함께 제공합니다. Codex OAuth gateway는 보통 chat/responses 경로를 다루고, embeddings는 별도 backend가 필요하기 때문입니다.

## Security and limitations

Secret handling과 local exposure guidance는 [`SECURITY.md`](SECURITY.md)를 참고하세요. Experimental status, compatibility limits, embedding-dimension caveats는 [`LIMITATIONS.md`](LIMITATIONS.md)를 참고하세요.

## License and provenance

이 저장소는 **AGPL-3.0-or-later**로 라이선스됩니다. 이 라이선스는 Honcho의 AGPL-3.0 codebase와 호환성을 유지하면서, MIT-licensed Hermes-derived OAuth/auth pattern을 combined work의 일부로 재배포할 수 있도록 선택했습니다.

**AI assistance notice:** 이 저장소의 일부 코드와 문서 초안은 maintainer 검토하에 AI 도움을 받아 작성 또는 수정되었습니다. README는 추후 maintainer가 직접 계속 다듬을 예정입니다.

Attribution과 provenance detail은 `NOTICE.md`를 참고하세요.

## Install: Honcho Docker quick install, gateway first

이 프로젝트는 Honcho의 Docker quick install 흐름에 맞게 설계되었습니다.

```bash
git clone https://github.com/plastic-labs/honcho.git
cd honcho
cp docker-compose.yml.example docker-compose.yml
cp .env.template .env       # normally fill in LLM_* keys here
docker compose up
```

유일한 차이는 순서입니다. **두 repo를 clone하고, gateway를 먼저 시작/인증한 다음 Honcho `.env`를 수정하고, 마지막으로 Honcho repo에서 `docker compose up`을 실행합니다.**

권장 sibling layout:

```text
<parent-directory>/
  honcho/
  honcho-codex-gateway/
```

올바른 fresh order:

```text
1. Honcho와 honcho-codex-gateway를 sibling directory로 clone합니다.
2. honcho-codex-gateway/install.sh를 먼저 실행합니다.
   - gateway .env/.auth/models를 준비합니다.
   - gateway Python entrypoint를 설치합니다.
   - skip하지 않으면 Codex OAuth login을 실행합니다.
   - 별도 gateway + llama.cpp GGUF embedding Docker stack을 시작합니다.
   - 필요하면 Honcho `.env`를 `.env.template`에서 생성합니다.
   - 필요하면 Honcho `docker-compose.yml`을 `docker-compose.yml.example`에서 생성합니다.
   - Linux에서는 Honcho `api`와 `deriver`에 `host.docker.internal:host-gateway`를 patch합니다.
   - verbose installer output은 `logs/install-*.log`에 기록합니다.
3. Honcho `.env` / `docker-compose.yml`을 검토한 뒤 Honcho에서 docker compose up을 실행합니다.
4. Honcho가 healthy가 된 뒤 Hermes Honcho setup을 실행합니다.
```

### Important: embedding dimensions must match from first startup

기본 OpenAI embedding config로 Honcho API/deriver를 한 번 시작한 뒤 BGE-M3로 나중에 바꾸지 마세요. Honcho는 첫 embedding provider/model dimension을 기준으로 database/vector index를 초기화할 수 있습니다. OpenAI `text-embedding-3-small`은 보통 `1536` dimensions를 사용하고, 이 gateway의 기본 local BGE-M3 embedding model은 `1024` dimensions를 사용합니다.

Database가 이미 한 dimension으로 초기화되었다면 나중에 바꾸는 과정에서 실패하거나 database reset, migration, re-embedding 작업이 필요할 수 있습니다. 가능하면 첫 Honcho startup 전에 원하는 embedding provider를 설정하세요.

### 1. Clone both repos

```bash
mkdir -p ./honcho-local
cd ./honcho-local
git clone https://github.com/plastic-labs/honcho.git
git clone https://github.com/DaydreamBlend/honcho-codex-gateway.git
```

`honcho-codex-gateway`가 이미 local working copy라면 `honcho` 옆에 두면 됩니다.

### 2. Prepare the gateway Docker stack first

Installer는 default GGUF가 없으면 자동으로 다운로드합니다.

```text
model: gpustack/bge-m3-GGUF / bge-m3-FP16.gguf
license: MIT, BAAI/bge-m3와 GGUF model card에서 이어짐
path: <parent-directory>/honcho-codex-gateway/models/bge-m3-FP16.gguf
```

Terminal에서 `install.sh`를 실행하면 사용할 embedding GGUF를 물어봅니다. Bundled BGE-M3 default를 다운로드하거나, 기존 local GGUF를 `./models/` 아래로 복사하거나, Hugging Face URL을 붙여넣을 수 있습니다. Hugging Face의 direct `.gguf` file URL이면 바로 다운로드하고, Hugging Face repo/tree URL이면 사용 가능한 `.gguf` file 목록을 보여준 뒤 선택하게 합니다. Hugging Face가 아닌 URL은 거부합니다. 선택된 file은 `EMBEDDING_GGUF_PATH`에 기록되어 Docker Compose가 llama.cpp server에 mount합니다.

Interactive menu 대신 flag를 사용하려면 model option을 명시하세요. 예:

```bash
./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions auto
# metadata detection을 사용할 수 없는 file이라면:
./install.sh --model-file /path/to/embedding-model.gguf --embedding-dimensions 768
```

Custom `--model-url`을 사용할 때는 `--model-sha256 SHA256`도 같이 지정하세요. Checksum verification 없이 받겠다고 의도적으로 결정한 경우에만 `--model-sha256 ''`를 사용하세요.

기본적으로 installer는 bundled `bge-m3-fp16` embedding preset을 사용하고, 가능하면 GGUF metadata에서 `EMBEDDING_VECTOR_DIMENSIONS`를 자동으로 설정합니다. Metadata detection을 할 수 없으면 preset의 `1024` dimension으로 fallback합니다.

`--write-honcho-env`가 기존 Honcho `.env`를 업데이트할 때, 기존 `EMBEDDING_VECTOR_DIMENSIONS` 값이 선택된 model dimension과 다르면 installer는 기본적으로 중단합니다. `--force-embedding-dimension-change`는 일반 설치 option이 아니라 migration/re-embedding을 의도할 때만 쓰는 escape hatch로 취급하세요.

그 다음 실행:

```bash
cd <parent-directory>/honcho-codex-gateway
sudo ./install.sh
```

Installer option을 확인하려면:

```bash
./install.sh --help
```

`install.sh`는 `../honcho` 같은 sibling Honcho checkout을 자동으로 감지합니다. 필요할 때 Honcho `.env`를 `.env.template`에서 생성하거나, 기존 `.env`를 timestamped `.env.bak.honcho-codex-gateway-*` backup으로 저장한 뒤 업데이트합니다. Linux에서는 필요할 때 Honcho `docker-compose.yml`도 `docker-compose.yml.example`에서 생성하고, `api`와 `deriver`에 `host.docker.internal:host-gateway`를 patch합니다. 기존 compose file은 patch 전에 backup합니다. Honcho가 이 repo 옆에 없다면 `--honcho-dir /path/to/honcho`를 사용하고, 자동 Honcho 수정을 끄려면 `--no-write-honcho-env`를 사용하세요. Honcho를 시작하기 전에 두 파일을 모두 검토하세요.

Installer는 noisy setup/build output을 `logs/install-*.log`에 보관하고, 마지막 console summary는 Honcho `.env` 위치와 Codex OAuth status 중심으로 짧게 유지합니다. 현재 사용자가 `/var/run/docker.sock`에 접근할 수 없으면 `sudo -v`를 요청하고 `sudo docker compose`로 Docker Compose를 실행합니다.

Installer는 gateway와 llama.cpp GGUF embedding server를 위한 **별도** Docker Compose project를 시작합니다.

```bash
docker compose -p honcho-codex-gateway up -d --build
```

Host에는 gateway만 localhost로 publish합니다.

```text
http://127.0.0.1:8787
```

Bundled llama.cpp embedding server는 BGE-M3 embedding을 위해 8192-token context window로 시작합니다.

```text
--ctx-size 8192
--batch-size 8192
--ubatch-size 8192
```

이 설정은 의도된 것입니다. Honcho에 생성되는 embedding config가 `MAX_INPUT_TOKENS=8192`를 사용하므로, embedding server context window가 4096 같은 더 작은 default로 남아 있으면 안 됩니다.

Honcho container에서는 이 OpenAI-compatible base URL을 사용합니다.

```text
http://host.docker.internal:8787/v1
```

Linux에서는 Honcho integration이 활성화되어 있으면 installer가 필요할 때 Honcho `docker-compose.yml`을 `docker-compose.yml.example`에서 생성하고, Honcho `api`와 `deriver` service에 아래 provider-networking override를 자동으로 추가합니다.

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Linux Docker는 `host-gateway`가 설정되어 있지 않으면 `host.docker.internal`을 일관되게 제공하지 않습니다. 이 저장소는 Linux에서 개발/테스트되었습니다. macOS와 Windows Docker Desktop은 여기서 테스트하지 않았습니다. Non-Linux host에서는 installer가 Honcho compose를 자동 patch하지 않습니다.

이것은 gateway service를 Honcho stack에 grafting하는 것이 아닙니다. Honcho container가 host-local provider URL에 접근할 수 있게 해주는 설정일 뿐입니다. Docker 환경이 이미 `host.docker.internal`을 올바르게 resolve하지 않는 한, 문서화된 Linux setup에서는 이 override를 required로 취급하세요.

### 3. 생성된 Honcho file 검토

Gateway installer가 Honcho config를 준비하기 전에는 Honcho `docker compose up`을 실행하지 마세요. 위 추천 명령을 사용하면 installer가 이미 다음을 처리합니다.

- Honcho `.env`가 없으면 `.env.template`에서 생성합니다.
- Linux에서 Honcho `docker-compose.yml`이 없으면 `docker-compose.yml.example`에서 생성합니다.
- 기존 `.env` / compose file을 수정하기 전 backup합니다.
- 생성된 provider block을 검토할 수 있도록 `logs/honcho-env.latest.txt`에 저장합니다.

일부러 `--write-honcho-env`를 사용하지 않았다면, 평소 `LLM_OPENAI_API_KEY` / `LLM_ANTHROPIC_API_KEY` / `LLM_GEMINI_API_KEY`를 채우는 단계에서 저장된 block을 수동으로 적용하세요.

Minimum shape:

```env
LLM_OPENAI_API_KEY=<gateway-api-key-from-honcho-codex-gateway-.env>

DIALECTIC_LEVELS__minimal__MODEL_CONFIG__TRANSPORT=openai
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL=gpt-5.4-mini
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__OVERRIDES__BASE_URL=http://host.docker.internal:8787/v1
# dialectic low/medium/high/max, summary, deriver, dream deduction, dream induction에
# 같은 transport/model/base_url pattern을 반복합니다.

EMBEDDING_MODEL_CONFIG__TRANSPORT=openai
EMBEDDING_MODEL_CONFIG__MODEL=text-embedding-bge-m3
EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL=http://host.docker.internal:8787/v1
EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY_ENV=LLM_OPENAI_API_KEY
EMBEDDING_VECTOR_DIMENSIONS=1024
EMBEDDING_MODEL_CONFIG__DIMENSIONS_MODE=never
```

### 4. Start Honcho Docker quick install

`.env`가 LLM과 embeddings를 gateway로 가리킨 뒤 시작하세요. Honcho upstream Docker compose는 API를 `127.0.0.1:8000`에 노출하므로 self-hosted API URL은 보통 `http://localhost:8000`입니다.

```bash
cd <parent-directory>/honcho
docker compose up
```

Detached mode:

```bash
docker compose up -d
```

Honcho Docker quick install이 non-1536 embedding을 위해 `scripts/configure_embeddings.py`를 자동으로 실행하지 않는다면, API/deriver가 embedding을 쓰기 전에 Honcho API image/container 안에서 equivalent command를 실행하세요. Invariant는 다음과 같습니다.

```text
Honcho .env gateway settings first → Honcho startup/migrations → empty embedding columns configured to 1024 → API/deriver writes data
```

이미 실행 중이고 embeddings가 채워진 Honcho에 대해서는 이것을 in-place migration으로 취급하지 마세요. Fresh deployment를 세우고 data replay/re-embed 후 cut over하세요.

### 5. Run Hermes + Honcho setup

Honcho가 healthy가 된 뒤 Hermes integration guide를 따르세요.

```bash
hermes honcho setup
hermes honcho status
```

Hermes가 시작한 Honcho API URL을 가리키게 하세요. 예:

```text
http://localhost:8000
```

정확한 URL/JWT/workspace/session 선택은 Honcho deployment와 Hermes profile에 따라 달라집니다. Honcho `/health`가 OK인 뒤에만 실행하세요. 그렇지 않으면 독립적인 두 bootstrap을 동시에 디버깅하게 됩니다.

## Tested environment

이 저장소는 Linux에서만 개발되고 smoke-tested 되었습니다.

- Host OS: Linux
- Runtime hardware: GB10 기반 MSI EdgeXpert 1TB 모델
- Honcho upstream Docker compose API port: `127.0.0.1:8000:8000`
- Gateway Docker compose published port: `127.0.0.1:8787:8787`
- Honcho container는 위 Linux `host-gateway` override를 통해 `http://host.docker.internal:8787/v1`로 gateway에 접근합니다.

macOS와 Windows Docker Desktop은 `host.docker.internal` 처리 방식이 다를 수 있으며, 이 저장소에서는 아직 테스트하지 않았습니다.

## Smoke tests

Gateway only:

```bash
curl -sS http://127.0.0.1:8787/health
# /v1/* routes에는 gateway .env의 GATEWAY_API_KEY를 사용한 HTTP Authorization Bearer header를 포함하세요.
curl -sS http://127.0.0.1:8787/v1/models \
  -H "<gateway authorization header>"
curl -sS -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H "<gateway authorization header>" \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-5.4-mini","messages":[{"role":"user","content":"Reply exactly: smoke ok"}]}'
```

Gateway를 통한 embedding은 embedding server/model이 실행 중이어야 합니다.

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/embeddings \
  -H "<gateway authorization header>" \
  -H 'content-type: application/json' \
  -d '{"model":"text-embedding-bge-m3","input":"smoke"}'
```

Honcho startup 이후:

```bash
curl -sS http://localhost:8000/health
```

그 다음 Honcho API 또는 Hermes Honcho setup/status로 memory operation을 확인하세요.
