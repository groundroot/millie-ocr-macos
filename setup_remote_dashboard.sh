#!/bin/zsh
set -euo pipefail

TAILSCALE_BIN="${MILLIE_OCR_TAILSCALE_BIN:-}"
if [[ -z "$TAILSCALE_BIN" ]]; then
  for candidate in \
    /Applications/Tailscale.app/Contents/MacOS/Tailscale \
    /opt/homebrew/bin/tailscale \
    /usr/local/bin/tailscale; do
    if [[ -x "$candidate" ]]; then
      TAILSCALE_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$TAILSCALE_BIN" || ! -x "$TAILSCALE_BIN" ]]; then
  printf '%s\n' 'Tailscale이 필요합니다: https://tailscale.com/download/mac' >&2
  exit 10
fi

if [[ "${1:-}" == "--disable" ]]; then
  "$TAILSCALE_BIN" serve --https=443 --set-path=/millie-ocr off
  /bin/rm -f -- "$HOME/.cache/millie-ocr/remote-url.txt"
  printf '%s\n' 'remote_dashboard=disabled'
  exit 0
fi

STATUS_JSON="$($TAILSCALE_BIN status --json)"
BACKEND_STATE="$(/usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("BackendState", ""))' <<< "$STATUS_JSON")"
if [[ "$BACKEND_STATE" != "Running" ]]; then
  /usr/bin/open -a Tailscale
  printf '%s\n' 'Tailscale을 켜고 Mac과 iPhone에서 같은 계정으로 로그인한 뒤 이 명령을 다시 실행하세요.' >&2
  exit 11
fi

DNS_NAME="$(/usr/bin/python3 -c 'import json,sys; print((json.load(sys.stdin).get("Self", {}).get("DNSName") or "").rstrip("."))' <<< "$STATUS_JSON")"
if [[ -z "$DNS_NAME" ]]; then
  printf '%s\n' 'Tailscale의 고정 장치 주소를 확인하지 못했습니다.' >&2
  exit 12
fi

set +e
SERVE_OUTPUT="$(/usr/bin/python3 - "$TAILSCALE_BIN" <<'PY'
import subprocess
import sys

command = [
    sys.argv[1],
    "serve",
    "--bg",
    "--yes",
    "--https=443",
    "--set-path=/millie-ocr",
    "http://127.0.0.1:8765",
]
process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    output, _ = process.communicate(timeout=15)
except subprocess.TimeoutExpired:
    process.terminate()
    output, _ = process.communicate(timeout=5)
    print(output, end="")
    raise SystemExit(124)
print(output, end="")
raise SystemExit(process.returncode)
PY
)"
SERVE_RESULT=$?
set -e
if [[ "$SERVE_RESULT" != "0" ]]; then
  AUTH_URL="$(printf '%s\n' "$SERVE_OUTPUT" | /usr/bin/sed -n 's/.*\(https:\/\/login\.tailscale\.com\/f\/serve[^[:space:]]*\).*/\1/p' | /usr/bin/head -n 1)"
  if [[ -n "$AUTH_URL" ]]; then
    /usr/bin/open "$AUTH_URL"
    printf 'Tailscale 최초 승인 페이지를 열었습니다: %s\n' "$AUTH_URL" >&2
    printf '%s\n' 'Serve를 허용한 뒤 이 명령을 다시 실행하세요.' >&2
    exit 13
  fi
  printf '%s\n' "$SERVE_OUTPUT" >&2
  exit "$SERVE_RESULT"
fi

REMOTE_URL="https://${DNS_NAME}/millie-ocr/"
/bin/mkdir -p "$HOME/.cache/millie-ocr"
/usr/bin/printf '%s\n' "$REMOTE_URL" > "$HOME/.cache/millie-ocr/remote-url.txt"
printf 'remote_url=%s\n' "$REMOTE_URL"
printf '%s\n' 'access=tailnet-only'
printf '%s\n' 'mode=read-only'
