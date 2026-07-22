#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  printf '%s\n' 'Millie OCR는 macOS에서만 설치할 수 있습니다.' >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  printf '%s\n' 'Homebrew를 먼저 설치합니다. macOS가 관리자 암호를 요청할 수 있습니다.'
  /bin/bash -c "$(/usr/bin/curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    export PATH="/opt/homebrew/bin:$PATH"
  elif [[ -x /usr/local/bin/brew ]]; then
    export PATH="/usr/local/bin:$PATH"
  fi
fi

brew install python poppler llama.cpp git

SCRIPT_DIR="${0:A:h}"
if [[ -f "$SCRIPT_DIR/install_local.sh" && -f "$SCRIPT_DIR/run_millie_ocr.sh" ]]; then
  REPOSITORY_DIR="$SCRIPT_DIR"
  TEMPORARY_DIR=""
else
  TEMPORARY_DIR="$(/usr/bin/mktemp -d /tmp/millie-ocr-install.XXXXXX)"
  trap '/bin/rm -rf -- "$TEMPORARY_DIR"' EXIT
  REPOSITORY_DIR="$TEMPORARY_DIR/repository"
  /usr/bin/git clone --depth 1 https://github.com/groundroot/millie-ocr-macos.git "$REPOSITORY_DIR"
fi

/bin/zsh "$REPOSITORY_DIR/install_local.sh"

printf '\n%s\n' '설치가 완료되었습니다.'
printf '%s\n' '1. ~/Applications/밀리 OCR.app을 단축어의 “앱 열기” 동작으로 선택하세요.'
printf '%s\n' '2. 실행할 때마다 결과 저장 폴더를 선택할 수 있습니다.'
printf '%s\n' '3. 처음 실행 시 macOS의 손쉬운 사용 및 화면 녹화 권한을 허용하세요.'
/usr/bin/open -R "$HOME/Applications/밀리 OCR.app" >/dev/null 2>&1 || true
