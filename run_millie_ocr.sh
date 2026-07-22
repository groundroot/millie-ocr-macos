#!/bin/zsh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

BOOK_TITLE="${1:-}"
RUN_MODE="${2:-run}"
REQUESTED_RESULT_ROOT="${3:-}"
AUTO_TITLE=0
if [[ -z "$BOOK_TITLE" || "$BOOK_TITLE" == "--auto" ]]; then
  AUTO_TITLE=1
  BOOK_TITLE="밀리의서재"
fi
PACKAGE_DIR="${0:A:h}"
CACHE_BASE="${XDG_CACHE_HOME:-$HOME/.cache}"
DEFAULT_ENGINE_ROOT="$CACHE_BASE/millie-ocr/surya2"
LEGACY_ENGINE_ROOT="$CACHE_BASE/codex-korean-ocr/surya2"
if [[ -n "${MILLIE_OCR_ENGINE_ROOT:-}" ]]; then
  ENGINE_ROOT="$MILLIE_OCR_ENGINE_ROOT"
elif [[ -x "$LEGACY_ENGINE_ROOT/surya-venv/bin/python" ]]; then
  ENGINE_ROOT="$LEGACY_ENGINE_ROOT"
else
  ENGINE_ROOT="$DEFAULT_ENGINE_ROOT"
fi
ENGINE_PYTHON="$ENGINE_ROOT/surya-venv/bin/python"
SURYA_BIN="$ENGINE_ROOT/surya-venv/bin/surya_ocr"
RUNTIME_PYTHON="${MILLIE_OCR_PYTHON:-}"
if [[ -z "$RUNTIME_PYTHON" ]]; then
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import json, pathlib' >/dev/null 2>&1; then
      RUNTIME_PYTHON="$candidate"
      break
    fi
  done
fi
if [[ -z "$REQUESTED_RESULT_ROOT" && -z "${MILLIE_OCR_RESULT_ROOT:-}" && "$RUN_MODE" == "run" ]]; then
  if ! REQUESTED_RESULT_ROOT="$(/usr/bin/osascript -e 'POSIX path of (choose folder with prompt "PDF·Markdown·EPUB 결과를 저장할 폴더를 선택하세요.")' 2>/dev/null)"; then
    exit 0
  fi
fi
RESULT_ROOT="${MILLIE_OCR_RESULT_ROOT:-$HOME/Documents/Codex/OCR Results}"
if [[ -n "$REQUESTED_RESULT_ROOT" ]]; then
  RESULT_ROOT="$REQUESTED_RESULT_ROOT"
fi
NATIVE_SCRIPT="$PACKAGE_DIR/millie_native.scpt"
if [[ ! -f "$NATIVE_SCRIPT" ]]; then
  NATIVE_SCRIPT="$PACKAGE_DIR/millie_native.applescript"
fi
LOCK_DIR="$CACHE_BASE/millie-ocr/active-run.lock"
STATUS_FILE="${MILLIE_OCR_STATUS_FILE:-$CACHE_BASE/millie-ocr/status.json}"
DASHBOARD_PORT="${MILLIE_OCR_DASHBOARD_PORT:-8765}"
DASHBOARD_URL="http://127.0.0.1:${DASHBOARD_PORT}"
SHORTCUT_LOG="$HOME/Library/Logs/MillieOCRShortcut.log"
DASHBOARD_LOG="$HOME/Library/Logs/MillieOCRDashboard.log"
DASHBOARD_LABEL="com.millieocr.dashboard"

if [[ "$RUN_MODE" == "--smoke" ]]; then
  RESULT_ROOT="${TMPDIR:-/tmp}/millie-ocr-smoke"
fi

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"밀리 OCR\"" >/dev/null 2>&1 || true
}

status_update() {
  "$RUNTIME_PYTHON" "$PACKAGE_DIR/status_store.py" \
    --file "$STATUS_FILE" "$@" >/dev/null 2>&1 || true
}

launch_dashboard() {
  /bin/mkdir -p "$HOME/Library/Logs" "${STATUS_FILE:h}"
  if ! /usr/bin/curl -fsS --max-time 0.4 "$DASHBOARD_URL/health" >/dev/null 2>&1; then
    /bin/launchctl kickstart -k "gui/$(/usr/bin/id -u)/$DASHBOARD_LABEL" >/dev/null 2>&1 || true
    for attempt in {1..15}; do
      if /usr/bin/curl -fsS --max-time 0.4 "$DASHBOARD_URL/health" >/dev/null 2>&1; then
        break
      fi
      /bin/sleep 0.2
    done
  fi
  if ! /usr/bin/curl -fsS --max-time 0.4 "$DASHBOARD_URL/health" >/dev/null 2>&1; then
    /usr/bin/nohup "$RUNTIME_PYTHON" "$PACKAGE_DIR/dashboard_server.py" \
        --status-file "$STATUS_FILE" \
        --html "$PACKAGE_DIR/dashboard.html" \
        --port "$DASHBOARD_PORT" \
        >> "$DASHBOARD_LOG" 2>&1 </dev/null &
    for attempt in {1..15}; do
      if /usr/bin/curl -fsS --max-time 0.4 "$DASHBOARD_URL/health" >/dev/null 2>&1; then
        break
      fi
      /bin/sleep 0.2
    done
  fi
  if /usr/bin/curl -fsS --max-time 0.4 "$DASHBOARD_URL/health" >/dev/null 2>&1; then
    /usr/bin/open "$DASHBOARD_URL" >/dev/null 2>&1 || true
  else
    notify "대시보드를 열지 못했습니다. OCR 작업은 계속 진행합니다."
  fi
}

cleanup() {
  if [[ -n "${CAFFEINATE_PID:-}" ]]; then
    /bin/kill "$CAFFEINATE_PID" >/dev/null 2>&1 || true
  fi
  /bin/rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
}

fail() {
  local exit_code=$?
  status_update \
    --state error \
    --message "작업이 중단되었습니다. 실행 기록에서 원인을 확인해 주세요." \
    --error "종료 코드 ${exit_code} · ${SHORTCUT_LOG}"
  notify "작업이 중단됐습니다. 밀리 OCR 로그를 확인해 주세요."
  exit "$exit_code"
}

if [[ -z "$RUNTIME_PYTHON" || ! -x "$RUNTIME_PYTHON" ]]; then
  notify "Python 3가 필요합니다. 먼저 설치 안내를 확인해 주세요."
  exit 10
fi
launch_dashboard
if [[ ! -f "$NATIVE_SCRIPT" ]]; then
  status_update \
    --reset \
    --state error \
    --phase preparing \
    --message "밀리 OCR 창 제어 파일을 찾지 못했습니다." \
    --log-path "$SHORTCUT_LOG" \
    --error "설치 명령을 다시 실행해 주세요."
  notify "밀리 OCR을 다시 설치해 주세요."
  exit 11
fi

/bin/mkdir -p "$CACHE_BASE/millie-ocr" "$RESULT_ROOT"
if ! /bin/mkdir "$LOCK_DIR" 2>/dev/null; then
  notify "이미 다른 OCR 작업이 실행 중입니다."
  exit 2
fi
trap cleanup EXIT
trap fail ERR

status_update \
  --reset \
  --state running \
  --phase preparing \
  --message "OCR 작업을 준비하고 있습니다." \
  --phase-progress 0.05 \
  --book-title "$BOOK_TITLE" \
  --log-path "$SHORTCUT_LOG"

printf '[%s] launch mode=%s requested_book=%s result_root=%s\n' "$(/bin/date '+%Y-%m-%d %H:%M:%S')" "$RUN_MODE" "$BOOK_TITLE" "$RESULT_ROOT"

/usr/bin/caffeinate -dimsu -w $$ &
CAFFEINATE_PID=$!

if [[ ! -x "$ENGINE_PYTHON" || ! -x "$SURYA_BIN" ]]; then
  status_update --phase preparing --message "처음 한 번만 OCR 엔진을 설치하고 있습니다." --phase-progress 0.2
  notify "처음 한 번만 OCR 엔진을 설치합니다."
  "$PACKAGE_DIR/install_surya_macos.sh" --root "$ENGINE_ROOT" --python "$RUNTIME_PYTHON"
fi

/usr/bin/osascript \
  -e 'tell application id "kr.co.millie.MillieShelf" to activate' \
  >/dev/null 2>&1 || true
/bin/sleep 0.5
status_update --phase preparing --message "밀리의 서재에서 열린 책과 쪽수를 확인하고 있습니다." --phase-progress 0.5

if ! NATIVE_STATE="$(/usr/bin/osascript "$NATIVE_SCRIPT" state kr.co.millie.MillieShelf 2>&1)"; then
  status_update \
    --state error \
    --phase preparing \
    --message "밀리의서재 창을 확인하지 못했습니다." \
    --error "$NATIVE_STATE"
  notify "밀리의서재에서 책을 열고 손쉬운 사용 권한을 확인해 주세요."
  exit 3
fi
APP_PID="$(printf '%s\n' "$NATIVE_STATE" | /usr/bin/sed -n '1p')"
WINDOW_TITLE="$(printf '%s\n' "$NATIVE_STATE" | /usr/bin/sed -n '2p')"
if [[ -z "$APP_PID" || "$APP_PID" != <-> ]]; then
  status_update --state error --phase preparing --message "밀리의서재 창 정보를 읽지 못했습니다." --error "$NATIVE_STATE"
  notify "밀리의서재에서 책을 한 페이지로 열어 주세요."
  exit 3
fi

if [[ "$AUTO_TITLE" == "1" ]]; then
  BOOK_TITLE="$WINDOW_TITLE"
fi

if [[ "$RUN_MODE" == "--check" ]]; then
  status_update \
    --state idle \
    --phase preparing \
    --message "실행 준비가 완료되어 있습니다." \
    --book-title "$BOOK_TITLE"
  printf 'status=ready\nbook=%s\napp_pid=%s\nresult_root=%s\nengine=%s\n' "$BOOK_TITLE" "$APP_PID" "$RESULT_ROOT" "$ENGINE_PYTHON"
  exit 0
fi

SAFE_TITLE="$($RUNTIME_PYTHON -c 'import re,sys; s=re.sub(r"[\\/:*?\"<>|]+", "_", sys.argv[1]).strip(" ."); print(s or "밀리의서재")' "$BOOK_TITLE")"
STAMP="$(/bin/date +%Y%m%d_%H%M%S)"
RUN_DIR="$RESULT_ROOT/${SAFE_TITLE}_${STAMP}"
IMAGE_DIR="$RUN_DIR/images"
RESULTS_DIR="$RUN_DIR/surya-results"
PDF_PATH="$RUN_DIR/${SAFE_TITLE}_Surya2_OCR.pdf"
MARKDOWN_PATH="$RUN_DIR/${SAFE_TITLE}_extracted.md"
EPUB_PATH="$RUN_DIR/${SAFE_TITLE}_extracted.epub"
VALIDATION_DIR="$RUN_DIR/validation"

/bin/mkdir -p "$IMAGE_DIR" "$RESULTS_DIR" "$VALIDATION_DIR"
printf 'book=%s\nstarted=%s\napp_pid=%s\nresult_root=%s\n' "$BOOK_TITLE" "$STAMP" "$APP_PID" "$RESULT_ROOT" > "$RUN_DIR/run-info.txt"
status_update \
  --state running \
  --phase preparing \
  --message "${BOOK_TITLE}의 첫 페이지로 이동하고 있습니다." \
  --phase-progress 0.9 \
  --book-title "$BOOK_TITLE" \
  --run-dir "$RUN_DIR" \
  --pdf-path "$PDF_PATH" \
  --markdown-path "$MARKDOWN_PATH" \
  --epub-path "$EPUB_PATH" \
  --log-path "$SHORTCUT_LOG"
notify "페이지 캡처를 시작했습니다."

CAPTURE_EXTRA=(--app-pid "$APP_PID")
if [[ "$RUN_MODE" == "--smoke" ]]; then
  CAPTURE_EXTRA+=(--end-page 1)
fi

"$ENGINE_PYTHON" "$PACKAGE_DIR/capture_millie_pages_stable.py" \
  "$IMAGE_DIR" \
  --native-script "$NATIVE_SCRIPT" \
  --status-file "$STATUS_FILE" \
  "${CAPTURE_EXTRA[@]}"

if [[ "$RUN_MODE" == "--smoke" ]]; then
  status_update --state complete --phase complete --message "캡처 시험을 완료했습니다." --phase-progress 1
  printf 'status=smoke-pass\nimage=%s\n' "$IMAGE_DIR/page_0001.png"
  exit 0
fi

CAPTURE_MANIFEST="$RUN_DIR/capture_manifest.json"
CAPTURE_MANIFEST_IN_IMAGES="$IMAGE_DIR/capture_manifest.json"
if [[ ! -f "$CAPTURE_MANIFEST_IN_IMAGES" ]]; then
  printf 'Capture manifest is missing: %s\n' "$CAPTURE_MANIFEST_IN_IMAGES" >&2
  exit 7
fi
/bin/mv "$CAPTURE_MANIFEST_IN_IMAGES" "$CAPTURE_MANIFEST"
EXPECTED_PAGES="$("$RUNTIME_PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print(d["end_page"])' "$CAPTURE_MANIFEST")"
CAPTURED_PAGES="$(/usr/bin/find "$IMAGE_DIR" -maxdepth 1 -type f -name 'page_*.png' | /usr/bin/wc -l | /usr/bin/tr -d ' ')"
if [[ "$CAPTURED_PAGES" != "$EXPECTED_PAGES" || ! -f "$IMAGE_DIR/page_$(printf '%04d' "$EXPECTED_PAGES").png" ]]; then
  printf 'Capture incomplete: images=%s expected=%s\n' "$CAPTURED_PAGES" "$EXPECTED_PAGES" >&2
  exit 8
fi

printf '[%s] capture-complete pages=%s; starting-pdf-ocr\n' "$(/bin/date '+%Y-%m-%d %H:%M:%S')" "$CAPTURED_PAGES"
status_update \
  --state running \
  --phase ocr \
  --message "${CAPTURED_PAGES}쪽 캡처를 마쳤습니다. 한글 OCR을 시작합니다." \
  --current "$CAPTURED_PAGES" \
  --total "$EXPECTED_PAGES" \
  --phase-progress 0
notify "${CAPTURED_PAGES}쪽 캡처 완료. PDF 작업을 바로 시작합니다."
"$ENGINE_PYTHON" "$PACKAGE_DIR/make_searchable_pdf.py" \
  "$IMAGE_DIR" \
  "$PDF_PATH" \
  --surya-bin "$SURYA_BIN" \
  --results-dir "$RESULTS_DIR" \
  --status-file "$STATUS_FILE"

IMAGE_COUNT="$(/usr/bin/find "$IMAGE_DIR" -maxdepth 1 -type f -name 'page_*.png' | /usr/bin/wc -l | /usr/bin/tr -d ' ')"
PDF_PAGES="$(pdfinfo "$PDF_PATH" | /usr/bin/awk '/^Pages:/ {print $2}')"
if [[ "$IMAGE_COUNT" != "$PDF_PAGES" ]]; then
  printf 'Image/PDF page mismatch: %s != %s\n' "$IMAGE_COUNT" "$PDF_PAGES" >&2
  exit 4
fi

status_update --phase markdown --message "PDF에서 인식한 본문을 추출하고 있습니다." --phase-progress 0.1
pdftotext "$PDF_PATH" "$VALIDATION_DIR/extracted.txt"
status_update --phase markdown --message "추출한 본문을 페이지별 Markdown으로 정리하고 있습니다." --phase-progress 0.4
"$ENGINE_PYTHON" "$PACKAGE_DIR/text_to_markdown.py" \
  "$VALIDATION_DIR/extracted.txt" \
  "$MARKDOWN_PATH" \
  --title "$BOOK_TITLE"
status_update --phase markdown --message "페이지 번호 없이 이어지는 Markdown을 완성했습니다." --phase-progress 1
if [[ ! -s "$MARKDOWN_PATH" ]]; then
  printf 'Markdown was not created: %s\n' "$MARKDOWN_PATH" >&2
  exit 9
fi
status_update --phase epub --message "글자 크기를 조절할 수 있는 EPUB을 만들고 있습니다." --phase-progress 0.1
"$ENGINE_PYTHON" "$PACKAGE_DIR/text_to_epub.py" \
  "$VALIDATION_DIR/extracted.txt" \
  "$EPUB_PATH" \
  --title "$BOOK_TITLE"
status_update --phase epub --message "EPUB 제작과 기본 구조 검증을 완료했습니다." --phase-progress 1
if [[ ! -s "$EPUB_PATH" ]]; then
  printf 'EPUB was not created: %s\n' "$EPUB_PATH" >&2
  exit 10
fi
status_update --phase validation --message "쪽수와 한글 추출 결과를 마지막으로 확인하고 있습니다." --phase-progress 0.15
HANGUL_COUNT="$("$RUNTIME_PYTHON" -c 'import re,sys,pathlib; print(len(re.findall(r"[가-힣]", pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore"))))' "$VALIDATION_DIR/extracted.txt")"
if [[ "$HANGUL_COUNT" -lt 1 ]]; then
  printf 'No extractable Hangul was found in the finished PDF\n' >&2
  exit 5
fi

MIDDLE_PAGE="$(( (PDF_PAGES + 1) / 2 ))"
pdftoppm -f 1 -l 1 -singlefile -png -r 96 "$PDF_PATH" "$VALIDATION_DIR/first" >/dev/null
pdftoppm -f "$MIDDLE_PAGE" -l "$MIDDLE_PAGE" -singlefile -png -r 96 "$PDF_PATH" "$VALIDATION_DIR/middle" >/dev/null
pdftoppm -f "$PDF_PAGES" -l "$PDF_PAGES" -singlefile -png -r 96 "$PDF_PATH" "$VALIDATION_DIR/last" >/dev/null
status_update --phase validation --message "첫 장·중간 장·마지막 장을 렌더링해 확인했습니다." --phase-progress 0.75

{
  printf 'images=%s\n' "$IMAGE_COUNT"
  printf 'pdf_pages=%s\n' "$PDF_PAGES"
  printf 'markdown=%s\n' "$MARKDOWN_PATH"
  printf 'extractable_hangul=%s\n' "$HANGUL_COUNT"
  pdfinfo "$PDF_PATH"
} > "$VALIDATION_DIR/validation.txt"
status_update --phase validation --message "PDF·Markdown·EPUB 결과 검증을 완료했습니다." --phase-progress 1

/usr/bin/open -R "$PDF_PATH" "$EPUB_PATH"
status_update \
  --state complete \
  --phase complete \
  --message "${PDF_PAGES}쪽 PDF·Markdown·EPUB을 모두 완성했습니다." \
  --current "$PDF_PAGES" \
  --total "$PDF_PAGES" \
  --phase-progress 1 \
  --pdf-path "$PDF_PATH" \
  --markdown-path "$MARKDOWN_PATH" \
  --epub-path "$EPUB_PATH" \
  --run-dir "$RUN_DIR" \
  --error ""
notify "완료: ${SAFE_TITLE} PDF·EPUB (${PDF_PAGES}쪽)"
printf 'output=%s\nmarkdown=%s\nepub=%s\npages=%s\nhangul=%s\n' "$PDF_PATH" "$MARKDOWN_PATH" "$EPUB_PATH" "$PDF_PAGES" "$HANGUL_COUNT"
