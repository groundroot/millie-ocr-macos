#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: install_surya_macos.sh [--root PATH] [--python PATH] [--revision REF] [--no-update] [--check]' \
    '' \
    'Installs official Surya OCR source, its Python environment, PDF helpers,' \
    'and the llama.cpp runtime required on macOS.'
}

cache_base="${XDG_CACHE_HOME:-${HOME}/.cache}"
engine_root="${cache_base}/codex-korean-ocr/surya2"
python_bin="${PYTHON_BIN:-python3}"
revision=""
update_source=1
check_only=0

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
    --check)
      check_only=1
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

hardware_arch="x86_64"
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || printf 0)" = "1" ]; then
  hardware_arch="arm64"
fi

python_arch() {
  "$1" -c 'import platform; print(platform.machine())' 2>/dev/null
}

python_is_compatible() {
  EXPECTED_MACHINE="$hardware_arch" "$1" - <<'PY' >/dev/null 2>&1
import os
import platform
import sys

if sys.version_info < (3, 10) or platform.machine() != os.environ["EXPECTED_MACHINE"]:
    raise SystemExit(1)
PY
}

if ! python_is_compatible "$python_bin"; then
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$candidate" ] && python_is_compatible "$candidate"; then
      python_bin="$candidate"
      break
    fi
  done
fi

if ! python_is_compatible "$python_bin"; then
  printf 'Native %s Python 3.10 or newer is required; selected Python is %s (%s).\n' \
    "$hardware_arch" "$python_bin" "$(python_arch "$python_bin" || printf unknown)" >&2
  exit 3
fi

"$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python 3.10 or newer is required')
PY

src_dir="${engine_root}/surya-src"
venv_dir="${engine_root}/surya-venv"
mkdir -p "$engine_root"

engine_is_healthy() {
  [ -x "${venv_dir}/bin/python" ] && \
  [ -x "${venv_dir}/bin/surya_ocr" ] && \
  EXPECTED_MACHINE="$hardware_arch" "${venv_dir}/bin/python" - <<'PY' >/dev/null 2>&1
import os
import platform

if platform.machine() != os.environ["EXPECTED_MACHINE"]:
    raise SystemExit(1)

from PIL import Image
import reportlab
import surya

Image.new("RGB", (1, 1)).tobytes()
PY
}

if [ "$check_only" -eq 1 ]; then
  if engine_is_healthy; then
    printf 'engine_status=healthy\n'
    printf 'architecture=%s\n' "$hardware_arch"
    exit 0
  fi
  printf 'engine_status=invalid\n' >&2
  printf 'expected_architecture=%s\n' "$hardware_arch" >&2
  exit 4
fi

if [ ! -d "${src_dir}/.git" ]; then
  git clone --depth 1 https://github.com/datalab-to/surya.git "$src_dir"
elif [ "$update_source" -eq 1 ]; then
  git -C "$src_dir" pull --ff-only
fi

if [ -n "$revision" ]; then
  git -C "$src_dir" fetch --depth 1 origin "$revision"
  git -C "$src_dir" checkout --detach FETCH_HEAD
fi

if [ -d "$venv_dir" ] && ! engine_is_healthy; then
  printf 'Rebuilding incompatible OCR environment for %s.\n' "$hardware_arch"
  /bin/rm -rf -- "$venv_dir"
fi

if [ ! -x "${venv_dir}/bin/python" ]; then
  ARCHFLAGS="-arch ${hardware_arch}" "$python_bin" -m venv "$venv_dir"
fi

PIP_NO_CACHE_DIR=1 ARCHFLAGS="-arch ${hardware_arch}" \
  "${venv_dir}/bin/python" -m pip install --no-cache-dir --upgrade pip
PIP_NO_CACHE_DIR=1 ARCHFLAGS="-arch ${hardware_arch}" \
  "${venv_dir}/bin/python" -m pip install --no-cache-dir "$src_dir" reportlab pypdf img2pdf

if ! engine_is_healthy; then
  printf 'OCR environment validation failed after installation (%s).\n' "$hardware_arch" >&2
  exit 5
fi

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
printf 'architecture=%s\n' "$hardware_arch"
printf 'llama_server=%s\n' "$(command -v llama-server)"
