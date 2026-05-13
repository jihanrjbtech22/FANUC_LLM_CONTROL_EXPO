#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[setup] Repository root: $ROOT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[setup] Python 3 is required but was not found on PATH."
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[setup] Creating virtual environment in .venv"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "[setup] Activating virtual environment"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[setup] Upgrading pip"
python -m pip install --upgrade pip

echo "[setup] Installing Python dependencies"
python -m pip install -r "$ROOT_DIR/requirements.txt"

echo "[setup] Verifying core imports"
python - <<'PY'
import sys

checks = [
    ("numpy", "numpy"),
    ("sounddevice", "sounddevice"),
    ("faster_whisper", "faster_whisper"),
]

failed = []
for label, module_name in checks:
    try:
        __import__(module_name)
        print(f"[setup] OK: {label}")
    except Exception as exc:
        failed.append((label, exc))
        print(f"[setup] FAIL: {label}: {exc}")

if failed:
    print("[setup] One or more imports failed. If sounddevice is missing system libraries, install them and rerun setup.")
    sys.exit(1)
PY

echo
echo "[setup] Setup complete. Next steps:"
echo "[setup] 1. Start Ollama with: ollama serve"
echo "[setup] 2. Pull a model with: ollama pull llama3:latest"
echo "[setup] 3. Start the app with: python3 master_terminal_chat.py --frontend"