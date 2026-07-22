#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SOURCE_DIR="${0:A:h}"
INSTALL_DIR="${MILLIE_OCR_INSTALL_DIR:-$HOME/Library/Application Support/MillieOCR}"
DASHBOARD_LABEL="com.millieocr.dashboard"
DASHBOARD_PLIST="$HOME/Library/LaunchAgents/${DASHBOARD_LABEL}.plist"
RUNTIME_PYTHON="${MILLIE_OCR_DASHBOARD_PYTHON:-}"
APP_DIR="$HOME/Applications"
APP_PATH="$APP_DIR/밀리 OCR.app"

if [[ -z "$RUNTIME_PYTHON" ]]; then
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import plistlib' >/dev/null 2>&1; then
      RUNTIME_PYTHON="$candidate"
      break
    fi
  done
fi
if [[ ! -x "$RUNTIME_PYTHON" ]]; then
  printf '%s\n' 'Python 3 is required. Run: brew install python' >&2
  exit 10
fi
if ! "$RUNTIME_PYTHON" -c 'import plistlib'; then
  printf '%s\n' 'The selected Python cannot load its standard plist library.' >&2
  exit 10
fi
/bin/mkdir -p "$INSTALL_DIR" "$APP_DIR" "$HOME/Library/Logs" "$HOME/Library/LaunchAgents" "$HOME/.cache/millie-ocr"
for file in \
  run_millie_ocr.sh \
  status_store.py \
  dashboard_server.py \
  dashboard.html \
  install_dashboard_agent.py \
  capture_millie_pages_stable.py \
  text_to_markdown.py \
  text_to_epub.py \
  install_surya_macos.sh \
  make_searchable_pdf.py \
  millie_native.applescript \
  Millie_OCR.applescript \
  Shortcut_Action.applescript \
  bootstrap_macos.sh \
  README.md; do
  /usr/bin/ditto "$SOURCE_DIR/$file" "$INSTALL_DIR/$file"
done
/bin/mkdir -p "$INSTALL_DIR/assets"
/usr/bin/ditto "$SOURCE_DIR/assets/MillieOCRIcon.png" "$INSTALL_DIR/assets/MillieOCRIcon.png"
/usr/bin/ditto "$SOURCE_DIR/assets/MillieOCR.icns" "$INSTALL_DIR/assets/MillieOCR.icns"

/bin/chmod 755 \
  "$INSTALL_DIR/run_millie_ocr.sh" \
  "$INSTALL_DIR/status_store.py" \
  "$INSTALL_DIR/dashboard_server.py" \
  "$INSTALL_DIR/install_dashboard_agent.py" \
  "$INSTALL_DIR/capture_millie_pages_stable.py" \
  "$INSTALL_DIR/text_to_markdown.py" \
  "$INSTALL_DIR/text_to_epub.py" \
  "$INSTALL_DIR/install_surya_macos.sh" \
  "$INSTALL_DIR/make_searchable_pdf.py" \
  "$INSTALL_DIR/bootstrap_macos.sh"

/usr/bin/osacompile -o "$INSTALL_DIR/millie_native.scpt" "$INSTALL_DIR/millie_native.applescript"
/usr/bin/osacompile -o "$INSTALL_DIR/Millie_OCR.scpt" "$INSTALL_DIR/Millie_OCR.applescript"
/usr/bin/osacompile -o "$APP_PATH" "$INSTALL_DIR/Millie_OCR.applescript"
/usr/bin/ditto "$INSTALL_DIR/assets/MillieOCR.icns" "$APP_PATH/Contents/Resources/MillieOCR.icns"
/usr/libexec/PlistBuddy -c 'Delete :CFBundleIdentifier' "$APP_PATH/Contents/Info.plist" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string com.groundroot.millieocr' "$APP_PATH/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile MillieOCR' "$APP_PATH/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Delete :CFBundleIconName' "$APP_PATH/Contents/Info.plist" >/dev/null 2>&1 || true
/usr/bin/codesign --force --deep --sign - "$APP_PATH" >/dev/null
if [[ -n "$RUNTIME_PYTHON" && -x "$RUNTIME_PYTHON" ]]; then
  "$RUNTIME_PYTHON" "$INSTALL_DIR/install_dashboard_agent.py" \
    --output "$DASHBOARD_PLIST" \
    --python "$RUNTIME_PYTHON" \
    --install-dir "$INSTALL_DIR" \
    --home "$HOME" \
    --port 8765
  AGENT_DOMAIN="gui/$(/usr/bin/id -u)"
  if /bin/launchctl print "$AGENT_DOMAIN/$DASHBOARD_LABEL" >/dev/null 2>&1; then
    /bin/launchctl bootout "$AGENT_DOMAIN/$DASHBOARD_LABEL" >/dev/null 2>&1 || true
  fi
  /bin/launchctl bootstrap "$AGENT_DOMAIN" "$DASHBOARD_PLIST"
  for attempt in {1..20}; do
    if /usr/bin/curl -fsS --max-time 0.4 http://127.0.0.1:8765/health >/dev/null 2>&1; then
      break
    fi
    /bin/sleep 0.1
  done
fi
printf 'installed=%s\n' "$INSTALL_DIR"
printf 'app=%s\n' "$APP_PATH"
