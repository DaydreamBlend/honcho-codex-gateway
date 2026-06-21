#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PROJECT_NAME="honcho-codex-gateway"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_AUTH=1
RUN_DOCKER=1
PRINT_ONLY=0
WRITE_HONCHO_ENV=0
HONCHO_DIR="${HONCHO_DIR:-}"
GATEWAY_BASE_URL="http://host.docker.internal:8787/v1"
CHAT_MODEL="gpt-5.4-mini"
EMBEDDING_MODEL="text-embedding-bge-m3"
EMBEDDING_DIMENSIONS="1024"
MODEL_FILE="models/bge-m3-FP16.gguf"
MODEL_URL="${MODEL_URL:-https://huggingface.co/gpustack/bge-m3-GGUF/resolve/main/bge-m3-FP16.gguf}"
MODEL_SHA256="${MODEL_SHA256:-daec91ffb5dd0c27411bd71f29932917c49cf529a641d0168496c3a501e3062c}"
DOWNLOAD_MODEL=1
DOCKER_CMD=(docker)
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Gateway-first installer for Honcho's Docker quick install.
Run this before `docker compose up` in the Honcho checkout. It prepares the
gateway, optionally runs Codex OAuth, optionally starts the separate Docker
stack, and prepares the Honcho .env values needed before Honcho startup.
Verbose install output is written to logs/install-*.log so the final console
summary stays readable.

Options:
  --gateway-base-url URL       URL Honcho containers should use (default: http://host.docker.internal:8787/v1)
  --chat-model MODEL           Chat model advertised to Honcho (default: gpt-5.4-mini)
  --embedding-model MODEL      Embedding model name for Honcho/gateway (default: text-embedding-bge-m3)
  --embedding-dimensions N     Embedding vector dimensions (default: 1024)
  --model-url URL              GGUF model URL to download when missing
  --skip-model-download        Do not download the default GGUF model when missing
  --honcho-dir PATH            Honcho checkout used with --write-honcho-env
  --write-honcho-env           Create/update Honcho .env from .env.template and gateway settings
  --skip-auth                  Do not run Codex OAuth login
  --print-only                 Only print Honcho .env block; do not write/start anything
  -h, --help                   Show this help

Fresh Docker quick-install order after this script:
  1. In Honcho: cp docker-compose.yml.example docker-compose.yml
  2. Run this installer with: ./install.sh --write-honcho-env --honcho-dir ../honcho
  3. Review Honcho .env and OAuth status shown in the final summary.
  4. In Honcho: docker compose up
  5. Run Hermes Honcho setup after Honcho is healthy.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gateway-base-url) GATEWAY_BASE_URL="$2"; shift 2 ;;
    --chat-model) CHAT_MODEL="$2"; shift 2 ;;
    --embedding-model) EMBEDDING_MODEL="$2"; shift 2 ;;
    --embedding-dimensions) EMBEDDING_DIMENSIONS="$2"; shift 2 ;;
    --model-url) MODEL_URL="$2"; shift 2 ;;
    --skip-model-download) DOWNLOAD_MODEL=0; shift ;;
    --honcho-dir) HONCHO_DIR="$2"; shift 2 ;;
    --write-honcho-env) WRITE_HONCHO_ENV=1; shift ;;
    --skip-auth) RUN_AUTH=0; shift ;;
    --print-only) PRINT_ONLY=1; RUN_AUTH=0; RUN_DOCKER=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$PRINT_ONLY" == "1" ]]; then
  exec "$PYTHON_BIN" scripts/prepare_fresh_install.py \
    --print-only \
    --gateway-base-url "$GATEWAY_BASE_URL" \
    --chat-model "$CHAT_MODEL" \
    --embedding-model "$EMBEDDING_MODEL" \
    --embedding-dimensions "$EMBEDDING_DIMENSIONS"
fi

if [[ "$WRITE_HONCHO_ENV" == "1" && -z "$HONCHO_DIR" ]]; then
  echo "ERROR: --write-honcho-env requires --honcho-dir /path/to/honcho" >&2
  exit 2
fi

download_model_if_needed() {
  if [[ -L "$MODEL_FILE" || -f "$MODEL_FILE" ]]; then
    echo "==> GGUF model already present: $MODEL_FILE"
    return 0
  fi
  if [[ -d "$MODEL_FILE" ]]; then
    echo "==> Removing directory created at model file path: $MODEL_FILE"
    rmdir "$MODEL_FILE" 2>/dev/null || {
      echo "ERROR: $MODEL_FILE is a non-empty directory; remove it or replace it with the GGUF file." >&2
      exit 1
    }
  fi
  if [[ "$DOWNLOAD_MODEL" != "1" ]]; then
    echo "WARNING: $MODEL_FILE is missing and model download is disabled."
    echo "         embedding-server will fail until you place or symlink the GGUF there."
    return 0
  fi

  echo "==> Downloading MIT-licensed default embedding model: gpustack/bge-m3-GGUF bge-m3-FP16.gguf"
  echo "    URL: $MODEL_URL"
  echo "    Output: $MODEL_FILE"
  echo "    Download progress is written to: $LOG_FILE"
  mkdir -p "$(dirname "$MODEL_FILE")"
  tmp_file="$MODEL_FILE.download"
  rm -f "$tmp_file"
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail --progress-bar "$MODEL_URL" -o "$tmp_file" >>"$LOG_FILE" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$tmp_file" "$MODEL_URL" >>"$LOG_FILE" 2>&1
  else
    echo "ERROR: curl or wget is required to download $MODEL_URL" >&2
    exit 1
  fi

  actual_sha="$(sha256sum "$tmp_file" | awk '{print $1}')"
  if [[ -n "$MODEL_SHA256" && "$actual_sha" != "$MODEL_SHA256" ]]; then
    rm -f "$tmp_file"
    echo "ERROR: downloaded GGUF checksum mismatch." >&2
    echo "       expected: $MODEL_SHA256" >&2
    echo "       actual:   $actual_sha" >&2
    exit 1
  fi
  mv "$tmp_file" "$MODEL_FILE"
  echo "==> GGUF model ready: $MODEL_FILE"
}

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
echo "==> Preparing gateway project at $ROOT"
echo "==> Verbose install log: $LOG_FILE"
mkdir -p .auth models
chmod 700 .auth || true

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

download_model_if_needed

{
  "$PYTHON_BIN" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -e .
} >>"$LOG_FILE" 2>&1

# shellcheck disable=SC1091
source .venv/bin/activate
PREPARE_ARGS=(
  --gateway-base-url "$GATEWAY_BASE_URL"
  --chat-model "$CHAT_MODEL"
  --embedding-model "$EMBEDDING_MODEL"
  --embedding-dimensions "$EMBEDDING_DIMENSIONS"
)
if [[ "$WRITE_HONCHO_ENV" == "1" ]]; then
  PREPARE_ARGS+=(--write-honcho-env)
fi
if [[ -n "$HONCHO_DIR" ]]; then
  PREPARE_ARGS+=(--honcho-dir "$HONCHO_DIR")
fi
python scripts/prepare_fresh_install.py "${PREPARE_ARGS[@]}" > "$LOG_DIR/honcho-env.latest.txt"
cat "$LOG_DIR/honcho-env.latest.txt" >> "$LOG_FILE"

if [[ "$RUN_AUTH" == "1" ]]; then
  echo
  echo "==> Starting Codex OAuth bootstrap"
  echo "    This stores credentials under $ROOT/.auth (ignored by git/docker builds)."
  CODEX_AUTH_DIR="$ROOT/.auth" honcho-codex-auth login --no-browser
else
  echo "==> Skipping Codex OAuth bootstrap (--skip-auth)."
fi

if [[ "$RUN_DOCKER" == "1" ]]; then
  if ! docker ps >/dev/null 2>&1; then
    if command -v sudo >/dev/null 2>&1; then
      echo "==> Docker requires elevated privileges; using sudo docker for compose startup."
      sudo -v
      DOCKER_CMD=(sudo docker)
    else
      echo "ERROR: docker is not accessible and sudo is not available." >&2
      exit 1
    fi
  fi
  echo
  echo "==> Starting separate Docker stack: $PROJECT_NAME"
  "${DOCKER_CMD[@]}" compose -p "$PROJECT_NAME" up -d --build >>"$LOG_FILE" 2>&1
  echo "==> Gateway health probe"
  curl -fsS http://127.0.0.1:8787/health >>"$LOG_FILE" 2>&1 || true
else
  echo "==> Skipping Docker startup."
fi

HONCHO_ENV_TARGET="not written; rerun with --write-honcho-env --honcho-dir /path/to/honcho or read $LOG_DIR/honcho-env.latest.txt"
if [[ "$WRITE_HONCHO_ENV" == "1" && -n "$HONCHO_DIR" ]]; then
  HONCHO_ENV_TARGET="$HONCHO_DIR/.env"
fi

cat <<EOF

Done.

Install log:
  $LOG_FILE

Honcho .env:
  $HONCHO_ENV_TARGET
  - Review LLM_OPENAI_API_KEY and gateway base URL before starting Honcho.
  - If not written automatically, apply the block saved at:
    $LOG_DIR/honcho-env.latest.txt

Embedding model:
  $MODEL_FILE
  - Default source: gpustack/bge-m3-GGUF bge-m3-FP16.gguf (MIT license)
  - Skip automatic download with: ./install.sh --skip-model-download

OAuth:
  - Codex credentials are stored under:
    $ROOT/.auth
  - Re-run OAuth only if the gateway reports auth failures:
    CODEX_AUTH_DIR="$ROOT/.auth" honcho-codex-auth login --no-browser

Next:
  cd /path/to/honcho
  docker compose up

EOF
