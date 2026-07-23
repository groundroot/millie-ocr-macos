#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  printf '%s\n' '마이북은 macOS에서만 업데이트할 수 있습니다.' >&2
  exit 1
fi

APP_PATH="$HOME/Applications/마이북.app"
LEGACY_APP_PATH="$HOME/Applications/밀리 OCR.app"
if [[ ! -d "$APP_PATH" && ! -d "$LEGACY_APP_PATH" ]]; then
  printf '%s\n' '설치된 마이북 앱을 찾지 못했습니다.' >&2
  printf '%s\n' '먼저 README의 한 줄 설치 명령을 실행하세요.' >&2
  exit 13
fi

if /usr/bin/pgrep -f '/run_millie_ocr\.sh([[:space:]]|$)' >/dev/null 2>&1; then
  printf '%s\n' '마이북 작업이 진행 중입니다. 작업이 끝난 뒤 다시 업데이트하세요.' >&2
  exit 14
fi

TEMPORARY_DIR=""
cleanup() {
  if [[ -n "$TEMPORARY_DIR" && "$TEMPORARY_DIR" == /tmp/mybook-code-update.* && -d "$TEMPORARY_DIR" ]]; then
    /bin/rm -rf -- "$TEMPORARY_DIR"
  fi
}
trap cleanup EXIT

if [[ -n "${MYBOOK_UPDATE_SOURCE_DIR:-}" ]]; then
  REPOSITORY_DIR="${MYBOOK_UPDATE_SOURCE_DIR:A}"
else
  printf '%s\n' '[1/3] GitHub에서 최신 마이북 코드를 받습니다.'
  TEMPORARY_DIR="$(/usr/bin/mktemp -d /tmp/mybook-code-update.XXXXXX)"
  ARCHIVE_PATH="$TEMPORARY_DIR/MyBookOCR.tar.gz"
  /usr/bin/curl -fL --retry 3 --connect-timeout 10 \
    -o "$ARCHIVE_PATH" \
    https://github.com/groundroot/MyBookOCR/archive/refs/heads/main.tar.gz
  /usr/bin/tar -xzf "$ARCHIVE_PATH" -C "$TEMPORARY_DIR"
  REPOSITORY_DIR="$TEMPORARY_DIR/MyBookOCR-main"
fi

if [[ ! -f "$REPOSITORY_DIR/install_local.sh" || ! -f "$REPOSITORY_DIR/run_millie_ocr.sh" ]]; then
  printf '%s\n' '받은 업데이트 파일이 완전하지 않습니다. 기존 설치는 변경하지 않았습니다.' >&2
  exit 15
fi

printf '%s\n' '[2/3] 앱과 보안 권한은 그대로 두고 실행 코드만 교체합니다.'
MILLIE_OCR_CODE_ONLY_UPDATE=1 \
MILLIE_OCR_SKIP_PERMISSION_SETUP=1 \
  /bin/zsh "$REPOSITORY_DIR/install_local.sh"

printf '%s\n' '[3/3] 업데이트를 확인합니다.'
if ! /usr/bin/curl -fsS --max-time 1 http://127.0.0.1:8765/health >/dev/null 2>&1; then
  printf '%s\n' '코드는 업데이트했지만 대시보드 응답을 확인하지 못했습니다.' >&2
  exit 12
fi

printf '\n%s\n' '마이북 코드 업데이트가 완료되었습니다.'
printf '%s\n' '앱 번들·서명·손쉬운 사용·화면 녹화 권한은 변경하지 않았습니다.'
