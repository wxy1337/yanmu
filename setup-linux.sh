#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_FILE="$ROOT_DIR/.env"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 was not found. Install Python 3.10 or newer first." >&2
  exit 1
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Python 3.10 or newer is required." >&2
  exit 1
}

if [ ! -x "$VENV_PYTHON" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROOT_DIR/requirements-dev.txt"

if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  echo "Created .env"
fi

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -qE "^[[:space:]]*${key}=" "$ENV_FILE"; then
    sed -i "s|^[[:space:]]*${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}

set_env_value "APP_HOST" "${APP_HOST:-0.0.0.0}"
set_env_value "APP_PORT" "${APP_PORT:-8000}"
set_env_value "DATA_DIR" "${DATA_DIR:-./data}"
set_env_value "WHISPER_MODEL" "${WHISPER_MODEL:-medium}"
set_env_value "WHISPER_DEVICE" "${WHISPER_DEVICE:-auto}"
set_env_value "WHISPER_COMPUTE_TYPE" "${WHISPER_COMPUTE_TYPE:-auto}"
set_env_value "ACCELERATION_MODE" "${ACCELERATION_MODE:-auto}"
set_env_value "GPU_VIDEO_ENCODER" "${GPU_VIDEO_ENCODER:-auto}"
set_env_value "CUDA_DLL_DIRECTORY" ""
set_env_value "TRANSLATION_PROVIDER" "${TRANSLATION_PROVIDER:-openai_compatible}"
set_env_value "TRANSLATION_BASE_URL" "${TRANSLATION_BASE_URL:-https://api.openai.com/v1}"
set_env_value "TRANSLATION_API_KEY" "${TRANSLATION_API_KEY:-}"
set_env_value "TRANSLATION_MODEL" "${TRANSLATION_MODEL:-gpt-4.1-mini}"
set_env_value "TRANSLATION_TIMEOUT_SECONDS" "${TRANSLATION_TIMEOUT_SECONDS:-90}"

mkdir -p "$ROOT_DIR/data/jobs" "$ROOT_DIR/.tools/hf-home"

echo "Setup complete. Run ./start-linux.sh to start YanMu."
