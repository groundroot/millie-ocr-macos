#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ "${1:-}" != "--yes" ]]; then
  printf '%s\n' '마이북 앱, 설정, OCR 모델 캐시, 대시보드, 로그와 권한 기록을 삭제합니다.'
  printf '%s\n' '사용자가 만든 PDF·EPUB·Markdown·이미지 결과 폴더와 공용 Homebrew 도구는 삭제하지 않습니다.'
  printf '%s\n' '삭제하려면 이 스크립트에 --yes를 지정해 다시 실행하세요.'
  exit 2
fi

if [[ -z "${HOME:-}" || "$HOME" == "/" ]]; then
  printf '%s\n' '안전한 사용자 홈 폴더를 확인하지 못해 삭제를 중단합니다.' >&2
  exit 10
fi

SUPPORT_DIR="$HOME/Library/Application Support/MillieOCR"
CACHE_DIR="$HOME/.cache/millie-ocr"
APP_PATH="$HOME/Applications/마이북.app"
LEGACY_APP_PATH="$HOME/Applications/밀리 OCR.app"
AGENT_PLIST="$HOME/Library/LaunchAgents/com.millieocr.dashboard.plist"
SHORTCUT_LOG="$HOME/Library/Logs/MillieOCRShortcut.log"
DASHBOARD_LOG="$HOME/Library/Logs/MillieOCRDashboard.log"
AGENT_DOMAIN="gui/$(/usr/bin/id -u)"
LAUNCH_SERVICES_REGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

# Disable the private Tailscale dashboard route before its helper is removed.
if [[ -x "$SUPPORT_DIR/setup_remote_dashboard.sh" ]]; then
  /bin/zsh "$SUPPORT_DIR/setup_remote_dashboard.sh" --disable >/dev/null 2>&1 || true
fi

# Stop only the runner recorded by this installation and verify its command
# before sending a signal.
RUNNER_PID_FILE="$CACHE_DIR/active-run.lock/pid"
if [[ -r "$RUNNER_PID_FILE" ]]; then
  RUNNER_PID="$(<"$RUNNER_PID_FILE")"
  if [[ "$RUNNER_PID" == <-> && "$RUNNER_PID" -gt 1 ]]; then
    RUNNER_COMMAND="$(/bin/ps -p "$RUNNER_PID" -o command= 2>/dev/null || true)"
    if [[ "$RUNNER_COMMAND" == *"run_millie_ocr.sh"* ]]; then
      /bin/kill -TERM "$RUNNER_PID" >/dev/null 2>&1 || true
      for attempt in {1..20}; do
        /bin/kill -0 "$RUNNER_PID" >/dev/null 2>&1 || break
        /bin/sleep 0.1
      done
      /bin/kill -KILL "$RUNNER_PID" >/dev/null 2>&1 || true
    fi
  fi
fi

/bin/launchctl bootout "$AGENT_DOMAIN/com.millieocr.dashboard" >/dev/null 2>&1 || true

for installed_app in "$APP_PATH" "$LEGACY_APP_PATH"; do
  if [[ -d "$installed_app" ]]; then
    /usr/bin/pkill -f "$installed_app/Contents/MacOS/applet" >/dev/null 2>&1 || true
    if [[ -x "$LAUNCH_SERVICES_REGISTER" ]]; then
      "$LAUNCH_SERVICES_REGISTER" -u "$installed_app" >/dev/null 2>&1 || true
    fi
  fi
done

# Remove this app's macOS privacy decisions so a later clean install starts
# from a known state. Unsupported services are ignored on older macOS releases.
/usr/bin/tccutil reset Accessibility com.groundroot.millieocr >/dev/null 2>&1 || true
/usr/bin/tccutil reset ScreenCapture com.groundroot.millieocr >/dev/null 2>&1 || true
/usr/bin/tccutil reset AppleEvents com.groundroot.millieocr >/dev/null 2>&1 || true

# All deletion targets are fixed children of the validated user home above.
/bin/rm -rf -- "$SUPPORT_DIR" "$CACHE_DIR" "$APP_PATH" "$LEGACY_APP_PATH"
/bin/rm -f -- "$AGENT_PLIST" "$SHORTCUT_LOG" "$DASHBOARD_LOG"

printf '%s\n' '마이북을 완전히 삭제했습니다.'
printf '%s\n' '사용자가 만든 결과 폴더와 Homebrew 공용 도구는 보존했습니다.'
printf '%s\n' '단축어 앱에 직접 만든 “마이북” 단축어가 있다면 단축어 앱에서 삭제하세요.'
