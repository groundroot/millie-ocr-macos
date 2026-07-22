#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SOURCE_DIR="${0:A:h}"
INSTALL_DIR="${MILLIE_OCR_INSTALL_DIR:-$HOME/Library/Application Support/MillieOCR}"
DASHBOARD_LABEL="com.millieocr.dashboard"
DASHBOARD_PLIST="$HOME/Library/LaunchAgents/${DASHBOARD_LABEL}.plist"
RUNTIME_PYTHON="${MILLIE_OCR_DASHBOARD_PYTHON:-/usr/bin/python3}"

if [[ ! -x "$RUNTIME_PYTHON" ]]; then
  printf '%s\n' 'Python 3 is required. Run: brew install python' >&2
  exit 10
fi
if ! "$RUNTIME_PYTHON" -c 'import plistlib'; then
  printf '%s\n' 'The selected Python cannot load its standard plist library.' >&2
  exit 10
fi
if ! command -v orca >/dev/null 2>&1; then
  printf '%s\n' \
    'Orca and its CLI are required.' \
    'Install: brew install --cask stablyai/orca/orca' \
    'Then open Orca and enable Settings > General > Orca CLI.' >&2
  exit 11
fi

/bin/mkdir -p "$INSTALL_DIR" "$HOME/Library/Logs" "$HOME/Library/LaunchAgents" "$HOME/.cache/millie-ocr"
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
  Millie_OCR.applescript \
  Shortcut_Action.applescript \
  README.md; do
  /usr/bin/ditto "$SOURCE_DIR/$file" "$INSTALL_DIR/$file"
done

/bin/chmod 755 \
  "$INSTALL_DIR/run_millie_ocr.sh" \
  "$INSTALL_DIR/status_store.py" \
  "$INSTALL_DIR/dashboard_server.py" \
  "$INSTALL_DIR/install_dashboard_agent.py" \
  "$INSTALL_DIR/capture_millie_pages_stable.py" \
  "$INSTALL_DIR/text_to_markdown.py" \
  "$INSTALL_DIR/text_to_epub.py" \
  "$INSTALL_DIR/install_surya_macos.sh" \
  "$INSTALL_DIR/make_searchable_pdf.py"

/usr/bin/osacompile -o "$INSTALL_DIR/Millie_OCR.scpt" "$INSTALL_DIR/Millie_OCR.applescript"
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
