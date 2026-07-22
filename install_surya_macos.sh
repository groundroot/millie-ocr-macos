#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: install_surya_macos.sh [--root PATH] [--python PATH] [--revision REF] [--no-update]' \
    '' \
    'Installs official Surya OCR source, its Python environment, PDF helpers,' \
    'and the llama.cpp runtime required on macOS.'
}

cache_base="${XDG_CACHE_HOME:-${HOME}/.cache}"
engine_root="${cache_base}/codex-korean-ocr/surya2"
python_bin="${PYTHON_BIN:-python3}"
revision=""
update_source=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      engine_root="$2"
      shift 2
      ;;
    --python)
      python_bin="$2"
      shift 2
      ;;
    --revision)
      revision="$2"
      shift 2
      ;;
    --no-update)
      update_source=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "$(uname -s)" != "Darwin" ]; then
  printf '%s\n' 'This setup script targets macOS. Install llama-server manually on other systems.' >&2
  exit 1
fi

"$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python 3.10 or newer is required')
PY

src_dir="${engine_root}/surya-src"
venv_dir="${engine_root}/surya-venv"
mkdir -p "$engine_root"

if [ ! -d "${src_dir}/.git" ]; then
  git clone --depth 1 https://github.com/datalab-to/surya.git "$src_dir"
elif [ "$update_source" -eq 1 ]; then
  git -C "$src_dir" pull --ff-only
fi

if [ -n "$revision" ]; then
  git -C "$src_dir" fetch --depth 1 origin "$revision"
  git -C "$src_dir" checkout --detach FETCH_HEAD
fi

if [ ! -x "${venv_dir}/bin/python" ]; then
  "$python_bin" -m venv "$venv_dir"
fi

"${venv_dir}/bin/python" -m pip install --upgrade pip
"${venv_dir}/bin/python" -m pip install "$src_dir" reportlab pypdf img2pdf

if ! command -v llama-server >/dev/null 2>&1; then
  if ! command -v brew >/dev/null 2>&1; then
    printf '%s\n' 'Homebrew is required to install llama.cpp automatically.' >&2
    exit 1
  fi
  brew install llama.cpp
fi

if ! command -v pdftotext >/dev/null 2>&1 || \
   ! command -v pdfinfo >/dev/null 2>&1 || \
   ! command -v pdftoppm >/dev/null 2>&1; then
  if ! command -v brew >/dev/null 2>&1; then
    printf '%s\n' 'Homebrew is required to install Poppler automatically.' >&2
    exit 1
  fi
  brew install poppler
fi

printf 'engine_root=%s\n' "$engine_root"
printf 'surya_commit=%s\n' "$(git -C "$src_dir" rev-parse HEAD)"
printf 'python=%s\n' "${venv_dir}/bin/python"
printf 'surya_ocr=%s\n' "${venv_dir}/bin/surya_ocr"
printf 'llama_server=%s\n' "$(command -v llama-server)"
