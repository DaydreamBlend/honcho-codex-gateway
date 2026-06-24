#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PROJECT_NAME="honcho-codex-gateway"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_AUTH=1
RUN_DOCKER=1
PRINT_ONLY=0
INTERACTIVE_MODE=auto
WRITE_HONCHO_ENV=auto
NO_WRITE_HONCHO_ENV=0
FORCE_EMBEDDING_DIMENSION_CHANGE=0
HONCHO_DIR="${HONCHO_DIR:-}"
GATEWAY_BASE_URL="http://host.docker.internal:8787/v1"
CHAT_MODEL="gpt-5.4-mini"
EMBEDDING_MODEL="text-embedding-bge-m3"
EMBEDDING_DIMENSIONS="auto"
EMBEDDING_DIMENSIONS_FALLBACK="1024"
EMBEDDING_PRESET="bge-m3-fp16"
MODEL_FILE=""
MODEL_SOURCE_FILE=""
MODEL_URL="${MODEL_URL:-https://huggingface.co/gpustack/bge-m3-GGUF/resolve/main/bge-m3-FP16.gguf}"
MODEL_SHA256="${MODEL_SHA256:-daec91ffb5dd0c27411bd71f29932917c49cf529a641d0168496c3a501e3062c}"
MODEL_URL_SET=0
MODEL_SHA256_SET=0
MODEL_SELECTION_SET=0
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
  --embedding-preset NAME     Embedding preset (default: bge-m3-fp16; currently the only bundled preset)
  --embedding-model MODEL      Embedding model name for Honcho/gateway (default: text-embedding-bge-m3)
  --embedding-dimensions N     Embedding vector dimensions, or auto (default: auto)
  --model-file PATH            Copy an existing local GGUF into ./models/ and use it
  --model-url URL              GGUF model URL to download into ./models/ when missing
  --model-path PATH            Path under this project to store/mount the selected GGUF
  --model-sha256 SHA256        Expected SHA256 for downloaded GGUF (empty disables check)
  --skip-model-download        Do not download the default GGUF model when missing
  --honcho-dir PATH            Honcho checkout override (default: auto-detect sibling ../honcho)
  --write-honcho-env           Force create/update Honcho .env/compose integration
  --no-write-honcho-env        Do not create/update Honcho .env or compose
  --force-embedding-dimension-change
                                Allow rewriting an existing Honcho .env with a different embedding dimension
  --interactive                Ask which embedding GGUF to use even when stdin is not a TTY
  --non-interactive            Do not prompt; use options/defaults only
  --skip-auth                  Do not run Codex OAuth login
  --print-only                 Only print Honcho .env block; do not write/start anything
  -h, --help                   Show this help

Fresh Docker quick-install order after this script:
  1. Clone Honcho and this gateway as sibling directories.
  2. Run this installer with: sudo ./install.sh
  3. Review Honcho .env / docker-compose.yml and OAuth status shown in the final summary.
  4. In Honcho: docker compose up
  5. Run Hermes Honcho setup after Honcho is healthy.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gateway-base-url) GATEWAY_BASE_URL="$2"; shift 2 ;;
    --chat-model) CHAT_MODEL="$2"; shift 2 ;;
    --embedding-preset) EMBEDDING_PRESET="$2"; shift 2 ;;
    --embedding-model) EMBEDDING_MODEL="$2"; shift 2 ;;
    --embedding-dimensions) EMBEDDING_DIMENSIONS="$2"; shift 2 ;;
    --model-file) MODEL_SOURCE_FILE="$2"; DOWNLOAD_MODEL=0; MODEL_SELECTION_SET=1; shift 2 ;;
    --model-url) MODEL_URL="$2"; MODEL_URL_SET=1; MODEL_SELECTION_SET=1; shift 2 ;;
    --model-path) MODEL_FILE="$2"; MODEL_SELECTION_SET=1; shift 2 ;;
    --model-sha256) MODEL_SHA256="$2"; MODEL_SHA256_SET=1; shift 2 ;;
    --skip-model-download) DOWNLOAD_MODEL=0; MODEL_SELECTION_SET=1; shift ;;
    --honcho-dir) HONCHO_DIR="$2"; shift 2 ;;
    --write-honcho-env) WRITE_HONCHO_ENV=1; shift ;;
    --no-write-honcho-env) WRITE_HONCHO_ENV=0; NO_WRITE_HONCHO_ENV=1; shift ;;
    --force-embedding-dimension-change) FORCE_EMBEDDING_DIMENSION_CHANGE=1; shift ;;
    --interactive) INTERACTIVE_MODE=1; shift ;;
    --non-interactive) INTERACTIVE_MODE=0; shift ;;
    --skip-auth) RUN_AUTH=0; shift ;;
    --print-only) PRINT_ONLY=1; RUN_AUTH=0; RUN_DOCKER=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

is_honcho_checkout() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  [[ -f "$dir/.env.template" || -f "$dir/.env" || -f "$dir/docker-compose.yml.example" || -f "$dir/docker-compose.yml" ]]
}

resolve_honcho_dir() {
  local candidate=""
  if [[ -n "$HONCHO_DIR" ]]; then
    if ! is_honcho_checkout "$HONCHO_DIR"; then
      echo "ERROR: --honcho-dir does not look like a Honcho checkout: $HONCHO_DIR" >&2
      exit 2
    fi
    HONCHO_DIR="$(cd "$HONCHO_DIR" && pwd)"
    if [[ "$NO_WRITE_HONCHO_ENV" != "1" ]]; then
      WRITE_HONCHO_ENV=1
    fi
    return 0
  fi

  local candidates=(
    "$ROOT/../honcho"
    "$ROOT/../../honcho"
    "$(pwd)/../honcho"
  )
  for candidate in "${candidates[@]}"; do
    if is_honcho_checkout "$candidate"; then
      HONCHO_DIR="$(cd "$candidate" && pwd)"
      if [[ "$WRITE_HONCHO_ENV" == "auto" ]]; then
        WRITE_HONCHO_ENV=1
      fi
      echo "==> Auto-detected Honcho checkout: $HONCHO_DIR"
      return 0
    fi
  done

  if [[ "$WRITE_HONCHO_ENV" == "1" ]]; then
    echo "ERROR: Could not auto-detect Honcho checkout. Clone Honcho next to this repo or pass --honcho-dir /path/to/honcho." >&2
    exit 2
  fi

  if [[ "$WRITE_HONCHO_ENV" == "auto" ]]; then
    if [[ "$PRINT_ONLY" != "1" && ( "$INTERACTIVE_MODE" == "1" || ( "$INTERACTIVE_MODE" == "auto" && -t 0 ) ) ]]; then
      printf "Honcho checkout path [../honcho]: "
      IFS= read -r candidate || candidate=""
      candidate="${candidate:-../honcho}"
      if is_honcho_checkout "$candidate"; then
        HONCHO_DIR="$(cd "$candidate" && pwd)"
        WRITE_HONCHO_ENV=1
        echo "==> Using Honcho checkout: $HONCHO_DIR"
        return 0
      fi
      echo "ERROR: path does not look like a Honcho checkout: $candidate" >&2
      exit 2
    fi
    WRITE_HONCHO_ENV=0
    echo "WARNING: Honcho checkout was not auto-detected; Honcho .env/compose will not be written."
    echo "         Clone Honcho next to this repo, pass --honcho-dir, or use --write-honcho-env."
  fi
}

resolve_honcho_dir

prompt_embedding_model_selection() {
  echo
  echo "Embedding GGUF model setup"
  echo "  1) Download bundled default: BGE-M3 FP16 GGUF (1024 dim, recommended)"
  echo "  2) Copy an existing local GGUF into ./models/"
  echo "  3) Paste a Hugging Face GGUF download URL"
  printf "Choose [1]: "
  IFS= read -r choice || choice=""
  choice="${choice:-1}"
  case "$choice" in
    1)
      echo "==> Selected bundled BGE-M3 FP16 GGUF."
      ;;
    2)
      printf "Path to local GGUF: "
      IFS= read -r MODEL_SOURCE_FILE || MODEL_SOURCE_FILE=""
      if [[ -z "$MODEL_SOURCE_FILE" ]]; then
        echo "ERROR: local GGUF path is required." >&2
        exit 2
      fi
      DOWNLOAD_MODEL=0
      MODEL_SELECTION_SET=1
      printf "Honcho embedding model name [${EMBEDDING_MODEL}]: "
      IFS= read -r answer || answer=""
      EMBEDDING_MODEL="${answer:-$EMBEDDING_MODEL}"
      printf "Embedding dimensions [auto]: "
      IFS= read -r answer || answer=""
      EMBEDDING_DIMENSIONS="${answer:-auto}"
      ;;
    3)
      printf "Hugging Face GGUF URL: "
      IFS= read -r MODEL_URL || MODEL_URL=""
      if [[ -z "$MODEL_URL" ]]; then
        echo "ERROR: Hugging Face GGUF URL is required." >&2
        exit 2
      fi
      MODEL_URL="$(PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -m honcho_codex_gateway.hf_gguf "$MODEL_URL")" || exit 2
      MODEL_URL_SET=1
      MODEL_SELECTION_SET=1
      printf "Expected SHA256 (leave empty only if you accept no checksum verification): "
      IFS= read -r MODEL_SHA256 || MODEL_SHA256=""
      MODEL_SHA256_SET=1
      printf "Honcho embedding model name [${EMBEDDING_MODEL}]: "
      IFS= read -r answer || answer=""
      EMBEDDING_MODEL="${answer:-$EMBEDDING_MODEL}"
      printf "Embedding dimensions [auto]: "
      IFS= read -r answer || answer=""
      EMBEDDING_DIMENSIONS="${answer:-auto}"
      ;;
    *)
      echo "ERROR: unsupported choice: $choice" >&2
      exit 2
      ;;
  esac
}

if [[ "$PRINT_ONLY" != "1" && "$MODEL_SELECTION_SET" != "1" ]]; then
  if [[ "$INTERACTIVE_MODE" == "1" || ( "$INTERACTIVE_MODE" == "auto" && -t 0 ) ]]; then
    prompt_embedding_model_selection
  fi
fi

if [[ "$MODEL_URL_SET" == "1" ]]; then
  MODEL_URL="$(PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -m honcho_codex_gateway.hf_gguf "$MODEL_URL")" || exit 2
fi

url_basename() {
  "$PYTHON_BIN" - "$1" <<'PY'
from urllib.parse import urlparse, unquote
import os, sys
path = unquote(urlparse(sys.argv[1]).path)
name = os.path.basename(path.rstrip('/')) or 'embedding-model.gguf'
print(name)
PY
}

model_path_from_name() {
  local name="$1"
  name="${name##*/}"
  if [[ "$name" != *.gguf ]]; then
    name="$name.gguf"
  fi
  printf 'models/%s\n' "$name"
}

if [[ -z "$MODEL_FILE" ]]; then
  if [[ -n "$MODEL_SOURCE_FILE" ]]; then
    MODEL_FILE="$(model_path_from_name "$MODEL_SOURCE_FILE")"
  else
    MODEL_FILE="$(model_path_from_name "$(url_basename "$MODEL_URL")")"
  fi
fi

if [[ "$MODEL_URL_SET" == "1" && "$MODEL_SHA256_SET" != "1" ]]; then
  echo "ERROR: --model-url requires --model-sha256 SHA256, or --model-sha256 '' to disable checksum verification intentionally." >&2
  exit 2
fi

case "$MODEL_FILE" in
  models/*|./models/*) ;;
  *)
    echo "ERROR: --model-path must be under ./models for portable Docker Compose installs: $MODEL_FILE" >&2
    exit 2
    ;;
esac

if [[ "$EMBEDDING_PRESET" != "bge-m3-fp16" ]]; then
  echo "ERROR: unsupported --embedding-preset: $EMBEDDING_PRESET" >&2
  echo "       Currently supported: bge-m3-fp16. Use --model-file/--model-url with --embedding-model and --embedding-dimensions for custom GGUFs." >&2
  exit 2
fi

if [[ "$PRINT_ONLY" == "1" ]]; then
  exec "$PYTHON_BIN" scripts/prepare_fresh_install.py \
    --print-only \
    --gateway-base-url "$GATEWAY_BASE_URL" \
    --chat-model "$CHAT_MODEL" \
    --embedding-model "$EMBEDDING_MODEL" \
    --embedding-dimensions "$EMBEDDING_DIMENSIONS" \
    --embedding-gguf "$MODEL_FILE" \
    --embedding-dimensions-fallback "$EMBEDDING_DIMENSIONS_FALLBACK"
fi

if [[ "$WRITE_HONCHO_ENV" == "1" && -z "$HONCHO_DIR" ]]; then
  echo "ERROR: --write-honcho-env requires --honcho-dir /path/to/honcho" >&2
  exit 2
fi

download_model_if_needed() {
  if [[ -n "$MODEL_SOURCE_FILE" ]]; then
    if [[ ! -f "$MODEL_SOURCE_FILE" ]]; then
      echo "ERROR: --model-file does not point to a readable file: $MODEL_SOURCE_FILE" >&2
      exit 1
    fi
    mkdir -p "$(dirname "$MODEL_FILE")"
    if [[ "$(realpath "$MODEL_SOURCE_FILE")" != "$(realpath -m "$MODEL_FILE")" ]]; then
      cp -f "$MODEL_SOURCE_FILE" "$MODEL_FILE"
    fi
    echo "==> GGUF model copied into project models directory"
    echo "    Source: $MODEL_SOURCE_FILE"
    echo "    Runtime model path: $MODEL_FILE"
    return 0
  fi

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
    echo "         embedding-server will fail until you place a GGUF there or update EMBEDDING_GGUF_PATH."
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
  --embedding-gguf "$MODEL_FILE"
  --embedding-dimensions-fallback "$EMBEDDING_DIMENSIONS_FALLBACK"
)
if [[ "$WRITE_HONCHO_ENV" == "1" ]]; then
  PREPARE_ARGS+=(--write-honcho-env)
fi
if [[ "$FORCE_EMBEDDING_DIMENSION_CHANGE" == "1" ]]; then
  PREPARE_ARGS+=(--force-embedding-dimension-change)
fi
if [[ -n "$HONCHO_DIR" ]]; then
  PREPARE_ARGS+=(--honcho-dir "$HONCHO_DIR")
fi
python scripts/prepare_fresh_install.py "${PREPARE_ARGS[@]}" > "$LOG_DIR/honcho-env.latest.txt"
cat "$LOG_DIR/honcho-env.latest.txt" >> "$LOG_FILE"

patch_honcho_compose_for_linux() {
  if [[ "$WRITE_HONCHO_ENV" != "1" || -z "$HONCHO_DIR" ]]; then
    return 0
  fi
  if [[ "$(uname -s)" != "Linux" ]]; then
    echo "==> Skipping Honcho host-gateway compose patch: non-Linux host detected ($(uname -s))."
    return 0
  fi
  echo "==> Ensuring Honcho docker-compose.yml exists and api/deriver can reach host.docker.internal on Linux"
  PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -m honcho_codex_gateway.honcho_compose "$HONCHO_DIR" | tee -a "$LOG_FILE"
}

patch_honcho_compose_for_linux

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

HONCHO_ENV_TARGET="not written; clone Honcho next to this repo, rerun install.sh, or pass --honcho-dir /path/to/honcho"
HONCHO_COMPOSE_TARGET="not managed; clone Honcho next to this repo, rerun install.sh, or pass --honcho-dir /path/to/honcho on Linux"
if [[ "$WRITE_HONCHO_ENV" == "1" && -n "$HONCHO_DIR" ]]; then
  HONCHO_ENV_TARGET="$HONCHO_DIR/.env"
  HONCHO_COMPOSE_TARGET="$HONCHO_DIR/docker-compose.yml"
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

Honcho docker-compose.yml:
  $HONCHO_COMPOSE_TARGET
  - On Linux, review the generated/patched host-gateway extra_hosts entries before starting Honcho.

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
