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
| Windows 11 + Docker Desktop, existing install/update path | 테스트됨 |
| Native Windows fresh install / WSL2 / macOS | 아직 완전하게 검증되지 않음 |
| Public hosted deployment | 지원하지 않음 |

Default install은 다음 경로로 smoke-tested 되었습니다.

- Honcho API health: `127.0.0.1:8000`
- Gateway health: `127.0.0.1:8787`
- Codex-backed Honcho chat
- 1024-dimensional BGE-M3 embeddings
- llama.cpp/GGUF token count를 반환하는 gateway `/internal/token-count`
- Honcho queue drain to zero pending work units
- 기존 1024-dimensional pgvector database를 유지한 Windows 11 + Docker Desktop 환경의 Honcho 3.1 update
- Rebuild 후 tokenizer patch V2 적용·idempotent 재적용과 Honcho-to-gateway embedding request

## 빠른 설치

아래의 automated `sudo ./install.sh` 흐름은 여전히 Linux-first입니다. Windows 검증 범위는 기존 native Windows 11 checkout과 Docker Desktop update path이며, fresh installer나 OAuth bootstrap 전체는 포함하지 않습니다.

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

Patch는 marker가 있고 idempotent합니다. 현재 helper는 legacy Honcho embedding client와 Honcho 3.1 layout을 모두 지원합니다. 알 수 없는 future upstream layout에서는 부분적으로 patch된 파일을 쓰지 않고 먼저 실패합니다.

Honcho update로 patch가 사라졌다면 다시 실행하세요.

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
DIALECTIC_LEVELS__minimal__MODEL_CONFIG__MODEL=gpt-5.6-terra
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

`DIALECTIC_LEVELS__minimal__...` 줄은 `minimal` tier에 사용할 model을 지정할 뿐,
active default를 `minimal`로 바꾸지 않습니다. Honcho는 chat마다 tier를 선택하며
upstream default는 `low`입니다.

## chat model pass-through

`/v1/chat/completions`에서 gateway는 Honcho 요청의 `model` 값을 바꾸지 않고 authenticated Codex Responses backend로 그대로 전달합니다. Chat-model allowlist, alias map, silent fallback을 두지 않으며, 실제 사용 가능 여부는 현재 Codex account/catalog가 결정합니다.

Upstream catalog는 gateway와 독립적으로 바뀔 수 있으므로 `/v1/models`는 local embedding model만 표시합니다. Installer가 Honcho에 쓰는 default chat model은 `gpt-5.6-terra`이며, 다른 upstream model은 `--chat-model`로 명시할 수 있습니다.

```bash
sudo ./install.sh --chat-model gpt-5.6-terra
```

### Terra를 기본값으로 쓰는 이유

2026-07-20 확인 시점에 authenticated Codex catalog는 `gpt-5.4-mini`를 여전히
반환했지만, `visibility=hide`, `supported_in_api=true`,
`use_responses_lite=false`로 표시했습니다. `upgrade` metadata는
`gpt-5.6-luna`를 가리키며 migration 문구는 Mini가 더 이상 제공되지 않는다고
안내합니다. 따라서 Mini는 일반 Codex OAuth model picker에서는 보이지 않지만,
명시적인 legacy request는 아직 성공할 수 있습니다. Live control에서 gateway는
`model=gpt-5.4-mini`를 변경하지 않았고 response도
`model=gpt-5.4-mini`라고 보고했습니다. Gateway가 Luna나 Terra로 fallback한 것은
아닙니다.

다만 response의 model label만으로 실제 요청을 처리한 OpenAI 내부 deployment나
weights를 확인할 수는 없습니다. 외부에서 관찰할 수 없는 compatibility route 또는
alias가 남아 있을 가능성이 있으므로, 이 프로젝트는 hidden Mini를 지원되는 운영
기본값으로 간주하지 않습니다. Official Codex client source에서도
[`visibility`는 model picker 표시 여부를 정하고](https://github.com/openai/codex/blob/3e2f79727a4e8ddfc8e3acb838d496b121094b9e/codex-rs/protocol/src/openai_models.rs#L622-L633),
`upgrade`는 명시적인 client-side migration prompt를 구동합니다.
[Configured model은 해당 migration을 수락할 때 변경됩니다](https://github.com/openai/codex/blob/3e2f79727a4e8ddfc8e3acb838d496b121094b9e/codex-rs/tui/src/app/startup_prompts.rs#L182-L203).
이 client code path만으로 transparent server-side alias가 있다고 볼 수는 없습니다.

Luna는 catalog가 안내하는 Mini 후속 model이지만, 정직한
`originator=honcho_codex_gateway`를 사용한 control에서는 약 31초 뒤 간헐적인
upstream `response.failed(server_error)`가 재현됐습니다. Terra는 picker에 표시되고
`supported_in_api=true`이며, 같은 plain 및 two-round tool-loop control을 해당 실패
패턴 없이 완료했습니다. 따라서 installer는 hidden Mini에 의존하거나 model을 몰래
치환하거나 official Codex client를 사칭하지 않고, Terra를 명시적으로 기본 사용합니다.

## 기존 Honcho 업데이트와 Terra 전환

Tokenizer patch는 의도적으로 `src/embedding_client.py`를 수정합니다. 따라서 Honcho를 pull하기 전에 생성된 patch를 복원해야 합니다. `git status`에 이 patch 외의 tracked change가 보이면 먼저 멈추고 확인하세요.

```bash
# 1. Honcho checkout 업데이트
cd /path/to/honcho
git status --short
git restore src/embedding_client.py
rm -f src/embedding_client.py.bak.honcho-codex-gateway-*
git pull --ff-only

# 2. Gateway 업데이트, Honcho의 chat route 9개를 Terra로 변경,
#    tokenizer/Compose integration patch 재적용
cd ../honcho-codex-gateway
git pull --ff-only
sudo ./install.sh \
  --honcho-dir ../honcho \
  --chat-model gpt-5.6-terra \
  --skip-auth \
  --non-interactive

# 3. Gateway를 먼저 rebuild한 뒤 Honcho rebuild
sudo docker compose up -d --build
cd ../honcho
sudo docker compose up -d --build
```

`--skip-auth`는 기존 Codex OAuth login을 그대로 유지합니다. Re-authentication이 필요할 때만 빼세요. Installer는 Honcho `.env`를 backup하고 Dialectic minimal/low/medium/high/max, Summary, Deriver, Dream 두 route를 갱신한 뒤 GGUF tokenizer patch를 다시 적용합니다.

Native Windows에서는 해당 명령을 제공하는 shell에서 같은 `git` 및 `docker compose` 명령을 사용하고, `sudo`를 사용할 수 없다면 생략하세요. 이 existing-install update path는 검증했지만, complete fresh-install 및 OAuth-bootstrap flow까지 Windows-tested라고 주장하지는 않습니다.

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

Gateway를 통한 direct Terra chat:

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer ***" \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-5.6-terra","messages":[{"role":"user","content":"Reply exactly: terra ok"}]}'
```

Gateway는 요청된 model name을 그대로 유지하고, authenticated Codex model
catalog에서 upstream Responses protocol profile을 선택합니다. 기본값
`CODEX_GATEWAY_RESPONSES_PROFILE=auto`는 process당 한 번 `/models`를 조회하고,
`CODEX_GATEWAY_CLIENT_VERSION`을 사용해 각 model의 `use_responses_lite` flag를
읽습니다. 같은 protocol version을 Gateway 자체 identity인
`CODEX_GATEWAY_ORIGINATOR=honcho_codex_gateway`와 함께 보내며, official Codex
CLI를 사칭하지 않습니다. Chat model allowlist나 alias table은 유지하지 않습니다.
Catalog에 없는 future model도 그대로 전달하며 standard Full Responses profile을
사용합니다.

Catalog에서 `use_responses_lite=true`인 model은 live client가 Responses Lite
header를 추가하고, top-level instructions를 developer input item으로 옮기며,
`reasoning.context=all_turns`와 `parallel_tool_calls=false`를 적용합니다. `false`인
model은 기존 Full Responses request shape를 유지합니다. Catalog discovery가
불가능할 때만 operator recovery override로
`CODEX_GATEWAY_RESPONSES_PROFILE=full` 또는 `lite`를 명시할 수 있습니다.

### Honcho Dialectic level과 model reasoning effort

둘 다 `low` 같은 단어를 쓸 수 있지만 서로 독립된 control입니다.

| Control | Layer | Values | Default 또는 policy |
| --- | --- | --- | --- |
| Honcho `reasoning_level` | Context retrieval, tools, iteration limit를 정하는 Dialectic orchestration | `minimal`, `low`, `medium`, `high`, `max` | Upstream Honcho default는 `low` |
| Model `thinking_effort` / `reasoning_effort` | Provider-side model compute | Backend별로 다름. 현재 Codex 예시는 `none`, `low`, `medium`, `high`, `xhigh` | 명시값은 그대로 전달하고, Honcho가 field를 생략할 때만 gateway policy 적용 |

원래 5.4 Mini 구성에 사용했던 upstream Honcho revision `60a15e6`에서도
[API schema](https://github.com/plastic-labs/honcho/blob/60a15e6/src/schemas/api.py#L564-L566)와
[Dialectic agent](https://github.com/plastic-labs/honcho/blob/60a15e6/src/dialectic/core.py#L62-L70)의
default는 모두 `low`였습니다. `minimal`은 별도로 명시하는 tier였습니다. 다섯 tier가
모두 `gpt-5.4-mini`를 가리켰으므로 model 선택이 `minimal` 선택을 의미하지도
않았습니다. 당시 [tier 설정](https://github.com/plastic-labs/honcho/blob/60a15e6/src/config.py#L946-L982)에서
`minimal`은 tool iteration 1회와 output 250-token cap을 사용했고, `low`는 tool
iteration을 최대 5회 허용했습니다. Caller는 request마다 tier를 override할 수 있지만,
그 선택도 tier에 mapping된 model과는 독립적입니다.

Honcho는 `ModelConfig.thinking_effort`를 Chat Completions의
`reasoning_effort` field로 보냅니다. 원래 5.4 Mini model config는 이 값을 설정하지
않았고 Honcho [OpenAI backend](https://github.com/plastic-labs/honcho/blob/60a15e6/src/llm/backends/openai.py#L336-L337)도
wire field를 생략했습니다. 이는 명시적 `reasoning_effort="none"`과 동일한
contract가 아닙니다. Field가 생략된 요청에 대해 현재 gateway는 tool context가
없으면 `CODEX_GATEWAY_REASONING_EFFORT`(기본 `none`), tool 정의나 tool-call
history가 있으면 `CODEX_GATEWAY_TOOL_REASONING_EFFORT`(기본 `low`)를 사용합니다.
명시된 effort는 변경하지 않습니다.

Adapter는 모든 effort에서 선택된 effort만 보내고 `reasoning.summary`와
`reasoning.encrypted_content`는 생략합니다. 이 Chat Completions facade는 Responses
reasoning artifacts를 다음 round로 보존하지 못하며, 해당 산출물을 요청하면 late
streaming failure가 재현됐습니다.

이 omitted-effort policy는 tool selection과 final synthesis 모두 현재 검증된 가장
낮은 tool-capable effort를 유지하기 위한 설정입니다. 올바른 Responses Lite
formatting은 기존 Full/Lite mismatch를 제거하지만, Codex OAuth backend는
effort와 별개로 간헐적인 late
`server_error` event를 반환할 수 있습니다. 위 호환성·안정성 이유로 installer는
`gpt-5.6-terra`를 기본값으로 사용합니다. Luna도
`--chat-model gpt-5.6-luna`로 명시 선택할 수 있으며, gateway는 model을 몰래
대체하지 않습니다.

현재 `gpt-5.6-luna` Codex backend가 거부하는 것은 literal model field
`reasoning_effort="minimal"`입니다. 실제 HTTP 오류는 Responses API effort
지원값으로 `none`, `low`, `medium`, `high`, `xhigh`를 알렸습니다. 이것은 Honcho의
agent-level `reasoning_level="minimal"`이 유효한 것과 모순되지 않습니다. Gateway는
명시된 model effort를 몰래 치환하지 않으며, effort가 생략됐을 때만 위 gateway
policy를 사용합니다.

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

Honcho chat smoke입니다. 아래 명령은 해당 tier를 확인하려고 `minimal`을 명시한
것이지 Honcho default `low` 경로를 검사하는 명령이 아닙니다. Upstream default를
검사하려면 `reasoning_level`을 생략하거나 `low`로 지정하세요.

```bash
curl -sS -X POST http://127.0.0.1:8000/v3/workspaces/hermes/peers/honcho-codex-smoke/chat \
  -H 'content-type: application/json' \
  -d '{"query":"Reply exactly: smoke ok","stream":false,"reasoning_level":"minimal"}'
```

## notes and limitations

- Default install은 local-only, single-user use를 전제로 합니다.
- Gateway는 기본적으로 `127.0.0.1`에 bind됩니다.
- Existing Honcho database에 이미 다른 vector dimension의 embedding schema가 채워져 있다면 추가 작업이 필요합니다.
- Windows 11 + Docker Desktop은 existing Honcho deployment의 upstream update, tokenizer patch 재적용, rebuild, embedding smoke path까지 검증했습니다. Native Windows fresh install, WSL2, macOS는 아직 완전하게 검증되지 않았습니다.
- 이 프로젝트는 사용자 본인의 OAuth credential에 의존합니다. Credential을 공유, pooling, rotation, resale하지 마세요.

## license and provenance

이 저장소는 AGPL-3.0-or-later로 라이선스됩니다. Honcho의 AGPL-3.0 codebase와 호환성을 유지하면서 MIT-licensed Hermes-derived OAuth/auth pattern을 combined work의 일부로 재배포할 수 있도록 이 라이선스를 사용합니다.

이 프로젝트의 Codex OAuth/auth handling은 Nous Research의 MIT-licensed Hermes Agent에 있는 OpenAI Codex OAuth code pattern을 참고하고 일부 조정해 사용합니다.

이 프로젝트는 OpenAI, Honcho, Hermes Agent, Nous Research, Plastic Labs의 공식 프로젝트가 아닙니다.

이 저장소의 일부 코드와 문서 초안은 maintainer 검토하에 AI 도움을 받아 작성 또는 수정되었습니다. Attribution과 provenance detail은 `NOTICE.md`를 참고하세요.
