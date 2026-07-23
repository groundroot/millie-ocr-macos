#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

stage() {
  printf '\n[%s] %s\n' "$1" "$2"
}

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  printf '%s\n' '마이북은 macOS에서만 설치할 수 있습니다.' >&2
  exit 1
fi

stage "1/5" "Homebrew를 확인합니다."
if ! command -v brew >/dev/null 2>&1; then
  printf '%s\n' 'Homebrew를 설치합니다. macOS가 관리자 암호를 요청할 수 있습니다.'
  /bin/bash -c "$(/usr/bin/curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    export PATH="/opt/homebrew/bin:$PATH"
  elif [[ -x /usr/local/bin/brew ]]; then
    export PATH="/usr/local/bin:$PATH"
  fi
else
  printf '%s\n' '기존 Homebrew를 사용합니다.'
fi

stage "2/5" "Python·PDF 도구·llama.cpp·Git을 준비합니다."
brew install python poppler llama.cpp git

stage "3/5" "최신 마이북 파일을 준비합니다."
SCRIPT_DIR="${0:A:h}"
if [[ -f "$SCRIPT_DIR/install_local.sh" && -f "$SCRIPT_DIR/run_millie_ocr.sh" ]]; then
  REPOSITORY_DIR="$SCRIPT_DIR"
  TEMPORARY_DIR=""
else
  TEMPORARY_DIR="$(/usr/bin/mktemp -d /tmp/millie-ocr-install.XXXXXX)"
  trap '/bin/rm -rf -- "$TEMPORARY_DIR"' EXIT
  REPOSITORY_DIR="$TEMPORARY_DIR/repository"
  /usr/bin/git clone --depth 1 https://github.com/groundroot/MyBookOCR.git "$REPOSITORY_DIR"
fi

stage "4/5" "앱과 대시보드를 설치합니다."
/bin/zsh "$REPOSITORY_DIR/install_local.sh"

DEFAULT_ENGINE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/millie-ocr/surya2"
LEGACY_ENGINE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/codex-korean-ocr/surya2"
if [[ -x "$LEGACY_ENGINE_ROOT/surya-venv/bin/surya_ocr" ]]; then
  ENGINE_ROOT="$LEGACY_ENGINE_ROOT"
else
  ENGINE_ROOT="$DEFAULT_ENGINE_ROOT"
fi

stage "5/5" "한글 OCR 엔진을 확인합니다."
if [[ "${MILLIE_OCR_SKIP_ENGINE_SETUP:-0}" == "1" ]]; then
  printf '%s\n' '요청에 따라 OCR 엔진 설치를 건너뜁니다.'
elif ! /bin/bash "$REPOSITORY_DIR/install_surya_macos.sh" \
    --root "$ENGINE_ROOT" \
    --python "$(command -v python3)" \
    --check >/dev/null 2>&1; then
  printf '%s\n' '현재 Mac과 맞지 않거나 손상된 OCR 환경을 다시 만듭니다.'
  /bin/bash "$REPOSITORY_DIR/install_surya_macos.sh" \
    --root "$ENGINE_ROOT" \
    --python "$(command -v python3)" \
    --no-update
else
  printf '기존 OCR 엔진을 유지합니다: %s\n' "$ENGINE_ROOT"
fi

if [[ "${MILLIE_OCR_SKIP_ENGINE_SETUP:-0}" != "1" ]]; then
  /bin/bash "$REPOSITORY_DIR/install_surya_macos.sh" \
    --root "$ENGINE_ROOT" \
    --python "$(command -v python3)" \
    --check >/dev/null
fi

for attempt in {1..20}; do
  if /usr/bin/curl -fsS --max-time 0.4 http://127.0.0.1:8765/health >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 0.1
done

if ! /usr/bin/curl -fsS --max-time 1 http://127.0.0.1:8765/health >/dev/null 2>&1; then
  printf '%s\n' '대시보드 시작을 확인하지 못했습니다.' >&2
  exit 12
fi

printf '\n%s\n' '설치가 완료되었습니다.'
printf '%s\n' '1. 응용 프로그램의 “마이북”을 직접 실행하거나 기존 단축어를 사용하세요.'
printf '%s\n' '2. 실행할 때마다 결과 저장 폴더와 결과 종류를 선택할 수 있습니다.'
printf '%s\n' '3. 처음 설치라면 손쉬운 사용과 화면 녹화에서 “마이북” 승인이 확인되었습니다.'
printf '%s\n' '4. 같은 명령을 다시 실행하면 보안 권한을 유지한 채 최신 버전으로 업데이트됩니다.'
/usr/bin/open -R "$HOME/Applications/마이북.app" >/dev/null 2>&1 || true
/usr/bin/open http://127.0.0.1:8765 >/dev/null 2>&1 || true
