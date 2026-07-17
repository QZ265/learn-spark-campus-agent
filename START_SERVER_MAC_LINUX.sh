#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "PyLearnSpark A3 Voice Final"
echo "This terminal must stay open while using the website."
if [ -x ".venv-lightrag/bin/python" ]; then
  PYTHON_BIN=".venv-lightrag/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-}"
  if [ -z "$PYTHON_BIN" ]; then
    for candidate in python3.13 python3.12 python3.11 python3.10; do
      if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; break; fi
    done
  fi
  CODEX_PYTHON="/Users/dhang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
  if [ -z "$PYTHON_BIN" ] && [ -x "$CODEX_PYTHON" ]; then PYTHON_BIN="$CODEX_PYTHON"; fi
  if [ -z "$PYTHON_BIN" ]; then
    echo "LightRAG 1.5.4 requires Python 3.10 or newer. Please install Python 3.12."
    exit 1
  fi
  "$PYTHON_BIN" -m venv .venv-lightrag
fi
source .venv-lightrag/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
