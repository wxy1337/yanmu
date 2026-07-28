#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Dependencies are not installed. Run ./setup-linux.sh first." >&2
  exit 1
fi

export HF_HOME="${HF_HOME:-$ROOT_DIR/.tools/hf-home}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export HF_HUB_DISABLE_SYMLINKS_WARNING="${HF_HUB_DISABLE_SYMLINKS_WARNING:-1}"

mkdir -p "$HF_HOME"

exec "$VENV_PYTHON" "$ROOT_DIR/run.py"
