#!/usr/bin/env python3
"""Fast, counter-verified capture for a Millie's Library reader window."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from resume_state import scan_contiguous_pages, update_resume
from status_store import update_status


DEFAULT_APP = "kr.co.millie.MillieShelf"
PAGE_COUNTER = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
FINAL_PAGE_COUNTER = re.compile(
    r"(?<!\d)(\d+)\s*/\s*\(\s*100\s*%\s*\)"
)
SLIDER_PAGE_COUNTER = re.compile(
    r"(?:slider|AXSlider|진행바)[^\n]*(?:Value:|value\s*[=:]\s*)(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
SLIDER_RANGE_COUNTER = re.compile(
    r"(?:slider|AXSlider|진행바)[^\n]*"
    r"(?:Value:|value\s*[=:]\s*)(\d+(?:\.\d+)?)[^\n]*"
    r"maximum\s*[=:]\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
KEY_CODES = {"Left": 123, "Right": 124, "Escape": 53}
CLOSE_BUTTON = re.compile(
    r"role=AXButton[^\n]*(?:name=닫기|description=닫기)", re.IGNORECASE
)
State = tuple[int, int, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a Millie's Library book from page 1 at maximum safe speed."
    )
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--app", default=DEFAULT_APP)
    parser.add_argument("--app-pid", type=int)
    parser.add_argument("--cg-window-id", type=int)
    parser.add_argument("--end-page", type=int)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--expected-total", type=int)
    parser.add_argument("--resume-file", type=Path)
    parser.add_argument("--target-width", type=int, default=1748)
    parser.add_argument("--target-height", type=int, default=2480)
    parser.add_argument("--trim-ratio", type=float, default=0.025)
    parser.add_argument("--raw-format", choices=("jpg", "png"), default="jpg")
    parser.add_argument("--native-script", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--retry-seconds", type=float, default=0.02)
    parser.add_argument("--max-refreshes", type=int, default=80)
    parser.add_argument("--reader-ready-seconds", type=float, default=8.0)
    parser.add_argument("--counter-audit-interval", type=int, default=10)
    parser.add_argument("--render-confirmations", type=int, default=3)
    parser.add_argument("--workers", type=int, default=min(4, max(2, os.cpu_count() or 2)))
    return parser.parse_args()


def run_native(
    args: argparse.Namespace, action: str, key: str | None = None
) -> dict:
    command = ["/usr/bin/osascript", str(args.native_script), action, args.app]
    if key is not None:
        command.append(str(KEY_CODES[key]))
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        if "-25211" in detail or "보조 접근" in detail or "assistive" in detail.lower():
            raise RuntimeError(
                "macOS 손쉬운 사용 권한이 필요합니다. '밀리의서재'가 아니라, 시스템 설정 > "
                "개인정보 보호 및 보안 > 손쉬운 사용에서 '밀리 OCR'을 허용해 주세요. "
                "AppleScript 실행 단축어를 사용한다면 '단축어'도 허용해야 합니다."
            )
        raise RuntimeError(detail or "밀리의서재 창을 제어하지 못했습니다.")
    lines = completed.stdout.splitlines()
    if len(lines) < 2:
        raise RuntimeError("밀리의서재 창 상태를 읽지 못했습니다.")
    try:
        args.app_pid = int(lines[0].strip())
    except ValueError as error:
        raise RuntimeError("밀리의서재 프로세스 번호를 읽지 못했습니다.") from error
    return {
        "snapshot": {
            "window": {"title": lines[1].strip()},
            "treeText": "\n".join(lines[2:]),
        }
    }


def state_from_result(result: dict) -> State:
    snapshot = result.get("snapshot", {})
    tree = snapshot.get("treeText", "")
    match = PAGE_COUNTER.search(tree)
    if match:
        current, total = map(int, match.groups())
    else:
        final_match = FINAL_PAGE_COUNTER.search(tree)
        if final_match:
            current = int(final_match.group(1))
            total = current
        else:
            slider_range_match = SLIDER_RANGE_COUNTER.search(tree)
            slider_match = SLIDER_PAGE_COUNTER.search(tree)
            if slider_range_match:
                current = max(1, int(round(float(slider_range_match.group(1)))))
                maximum = int(round(float(slider_range_match.group(2))))
                total = maximum if maximum >= current and maximum > 1 else 0
            elif slider_match:
                current = max(1, int(round(float(slider_match.group(1)))))
                total = 0
            else:
                raise RuntimeError(
                    "Reader page counter was not found; close any menu and keep one page visible"
                )
    if current < 1 or (total > 0 and total < current):
        raise RuntimeError(
            f"Invalid reader page counter: {current}/{total}"
        )
    title = snapshot.get("window", {}).get("title", "")
    return current, total, title


def activate_reader(bundle_id: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'tell application id "{bundle_id}" to activate'],
        check=True,
        capture_output=True,
        text=True,
    )


def transient_reader_error(error: RuntimeError) -> bool:
    detail = str(error)
    return any(
        marker in detail
        for marker in ("열린 책 창", "실행 중", "-1728", "가져올 수 없습니다")
    )


def resolve_cg_window_id(app_pid: int) -> int | None:
    """Resolve the real CoreGraphics window id instead of reusing an AX id."""
    script = f'''ObjC.import("CoreGraphics");
const targetPid={int(app_pid)};
const ref=$.CGWindowListCopyWindowInfo(
  $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements,
  $.kCGNullWindowID
);
let best=0, bestArea=0;
const count=Number($.CFArrayGetCount(ref));
for(let i=0;i<count;i++){{
  const item=ObjC.castRefToObject($.CFArrayGetValueAtIndex(ref,i));
  const pid=Number(ObjC.unwrap(item.objectForKey("kCGWindowOwnerPID")));
  const layer=Number(ObjC.unwrap(item.objectForKey("kCGWindowLayer")));
  if(pid!==targetPid || layer!==0) continue;
  const bounds=item.objectForKey("kCGWindowBounds");
  const width=Number(ObjC.unwrap(bounds.objectForKey("Width")));
  const height=Number(ObjC.unwrap(bounds.objectForKey("Height")));
  const area=width*height;
  if(area>bestArea){{
    bestArea=area;
    best=Number(ObjC.unwrap(item.objectForKey("kCGWindowNumber")));
  }}
}}
String(best)'''
    completed = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    try:
        window_id = int(completed.stdout.strip())
    except ValueError:
        return None
    return window_id if window_id > 0 else None


def get_state_result(args: argparse.Namespace, restore: bool = False) -> dict:
    last_error = None
    for attempt in range(3):
        try:
            return run_native(args, "focus" if restore or attempt > 0 else "state")
        except RuntimeError as error:
            last_error = error
            if not transient_reader_error(error):
                raise
            activate_reader(args.app)
            time.sleep(args.retry_seconds)
    raise RuntimeError(f"Reader window remained unavailable: {last_error}")


def get_state(args: argparse.Namespace, restore: bool = False) -> State:
    deadline = time.monotonic() + max(0.0, args.reader_ready_seconds)
    last_error: RuntimeError | None = None
    while True:
        result = get_state_result(args, restore=restore)
        try:
            return state_from_result(result)
        except RuntimeError as error:
            last_error = error
            tree = result.get("snapshot", {}).get("treeText", "")
            if "HTML content 투데이 | 밀리의서재" in tree or "0%에서 이어서 읽어볼까요?" in tree:
                raise RuntimeError(
                    "Millie's Library is showing its home screen; open the book in one-page reader mode"
                ) from error
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Reader page counter did not become available within "
                    f"{args.reader_ready_seconds:.1f}s; close menus and keep the book open "
                    f"in one-page mode (last error: {last_error})"
                ) from error
            time.sleep(max(args.retry_seconds, 0.15))


def press_key(args: argparse.Namespace, key: str) -> State:
    last_error = None
    for attempt in range(4):
        if attempt > 0:
            activate_reader(args.app)
            time.sleep(0.04 * attempt)
        try:
            result = run_native(args, "press", key)
            try:
                return state_from_result(result)
            except RuntimeError as error:
                if "page counter was not found" not in str(error):
                    raise
                return get_state(args, restore=attempt > 0)
        except RuntimeError as error:
            last_error = error
            if not transient_reader_error(error):
                raise
    raise RuntimeError(f"Reader could not retain keyboard focus: {last_error}")


def press_key_fast(args: argparse.Namespace, key: str) -> None:
    """Deliver exactly one key without the expensive accessibility-tree read."""
    last_error: RuntimeError | None = None
    for attempt in range(3):
        try:
            run_native(args, "press-fast", key)
            return
        except RuntimeError as error:
            last_error = error
            if not transient_reader_error(error):
                raise
            activate_reader(args.app)
            time.sleep(max(args.retry_seconds, 0.05) * (attempt + 1))
    raise RuntimeError(f"Reader remained unavailable during fast key delivery: {last_error}")


def focus_reader(args: argparse.Namespace) -> None:
    run_native(args, "focus")
    # Keyboard delivery can restore the window itself. Avoid clicking the page body:
    # Millie's reader occasionally treats a center click as an exit/navigation action.


def close_table_of_contents(args: argparse.Namespace) -> None:
    focus_reader(args)
    # This is the only normal-path full accessibility tree scan. Per-page state
    # reads use the counter-only native action for maximum capture throughput.
    result = run_native(args, "tree")
    tree = result.get("snapshot", {}).get("treeText", "")
    if "목차" not in tree or not CLOSE_BUTTON.search(tree):
        return
    closed = run_native(args, "close")
    if CLOSE_BUTTON.search(closed.get("snapshot", {}).get("treeText", "")):
        raise RuntimeError("The table of contents is open but its close button was not found")


def wait_for_counter(
    args: argparse.Namespace,
    expected: int,
    expected_total: int | None = None,
    initial_state: State | None = None,
) -> State:
    last_seen = None
    for attempt in range(args.max_refreshes):
        state = initial_state if attempt == 0 and initial_state is not None else get_state(args)
        current, total, _ = state
        last_seen = (current, total)
        if current == expected and (expected_total is None or total == expected_total):
            return state
        time.sleep(args.retry_seconds)
    raise RuntimeError(
        f"Reader did not reach the expected counter {expected}; last seen={last_seen}"
    )


def rewind_and_warm_reader(args: argparse.Namespace) -> State:
    close_table_of_contents(args)
    focus_reader(args)
    current, total, title = get_state(args, restore=True)
    rewind_start = current

    while current > 1:
        expected = current - 1
        pressed_state = press_key(args, "Left")
        current, total, title = wait_for_counter(
            args, expected, initial_state=pressed_state
        )
        if current <= 3 or current % 10 == 0:
            total_label = str(total) if total > 0 else "?"
            print(f"rewind={current}/{total_label}", flush=True)

    if rewind_start > 1:
        print(f"rewound={rewind_start}->1", flush=True)

    # One round trip stabilizes Millie's final pagination without fixed sleeps.
    if total > 1:
        right_state = press_key(args, "Right")
        _, warmed_total, _ = wait_for_counter(args, 2, initial_state=right_state)
        left_state = press_key(args, "Left")
        current, total, title = wait_for_counter(
            args, 1, initial_state=left_state
        )
        # Millie can publish a revised total only after returning to page 1.
        # Accept the new total here; capture will lock and verify it from page 1 onward.
        if total != warmed_total:
            print(f"pagination_total_updated={warmed_total}->{total}", flush=True)
    return current, total, title


def move_reader_to_page(args: argparse.Namespace, target_page: int) -> State:
    close_table_of_contents(args)
    focus_reader(args)
    current, total, title = get_state(args, restore=True)
    if target_page < 1 or (total > 0 and target_page > total):
        raise RuntimeError(
            f"이어갈 쪽수가 올바르지 않습니다: target={target_page}, total={total or '?'}"
        )
    while current != target_page:
        direction = "Right" if current < target_page else "Left"
        expected = current + 1 if direction == "Right" else current - 1
        pressed_state = press_key(args, direction)
        current, total, title = wait_for_counter(
            args,
            expected,
            expected_total=args.expected_total,
            initial_state=pressed_state,
        )
        if current == target_page or current % 10 == 0:
            print(f"resume_seek={current}/{total or '?'}", flush=True)
    return current, total, title


def normalize_screenshot(
    source: Path,
    destination: Path,
    target_width: int,
    target_height: int,
    trim_ratio: float,
) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        trim = max(1, round(image.height * trim_ratio))
        if image.height <= trim * 2:
            raise RuntimeError("Screenshot is too small for UI trimming")
        image = image.crop((0, trim, image.width, image.height - trim))
        scale = min(target_width / image.width, target_height / image.height)
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGB", (target_width, target_height), "white")
        left = (target_width - resized.width) // 2
        top = (target_height - resized.height) // 2
        canvas.paste(resized, (left, top))
        canvas.save(destination, format="PNG", compress_level=1)


def image_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_raw(args: argparse.Namespace, destination: Path) -> State | None:
    destination.unlink(missing_ok=True)
    completed = subprocess.run(
        [
            "/usr/sbin/screencapture",
            "-x",
            "-o",
            "-t",
            args.raw_format,
            "-l",
            str(args.cg_window_id),
            str(destination),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 and destination.is_file() and destination.stat().st_size:
        return None
    if args.app_pid:
        refreshed_window_id = resolve_cg_window_id(args.app_pid)
        if refreshed_window_id and refreshed_window_id != args.cg_window_id:
            args.cg_window_id = refreshed_window_id
            return capture_raw(args, destination)
    raise RuntimeError(
        "밀리의서재 창을 캡처하지 못했습니다. 시스템 설정 > 개인정보 보호 및 보안 > "
        "화면 및 시스템 오디오 녹음에서 '밀리 OCR' 또는 '단축어'를 허용해 주세요."
    )


def capture_distinct_raw(
    args: argparse.Namespace,
    raw_path: Path,
    expected_page: int,
    expected_total: int | None,
    previous_raw_hash: str | None,
    allow_final_page: bool = False,
) -> str | None:
    last_hash = None
    redeliveries = 0
    for attempt in range(args.max_refreshes):
        observed_state = capture_raw(args, raw_path)
        if observed_state is not None:
            current, total, _ = observed_state
            if current != expected_page or (
                expected_total is not None and total != expected_total
            ):
                raise RuntimeError(
                    f"Unexpected reader counter during capture: {current}/{total or '?'}; "
                    f"expected {expected_page}/{expected_total or '?'}"
                )
        last_hash = image_hash(raw_path)
        if previous_raw_hash is None or last_hash != previous_raw_hash:
            return last_hash

        if attempt < 1:
            time.sleep(args.retry_seconds)
            continue

        current, total, _ = get_state(args)
        previous_page = expected_page - 1
        if current < previous_page:
            # At burst speed the rendered page can lead Millie's accessibility
            # slider by several updates.  Wait for the counter to catch up before
            # treating an identical page as an unexpected jump.
            lag_refreshes = min(max(8, args.render_confirmations * 3), args.max_refreshes)
            for lag_attempt in range(lag_refreshes):
                time.sleep(max(args.retry_seconds, 0.05))
                current, total, _ = get_state(args)
                if current >= expected_page:
                    break
        if current == expected_page and (
            expected_total is None or total == expected_total
        ):
            # The counter moved but Millie may still be painting the page. Give
            # it a few short capture cycles, then accept a genuinely identical
            # blank/divider page instead of waiting for a change that cannot occur.
            for _ in range(max(1, args.render_confirmations)):
                time.sleep(args.retry_seconds)
                capture_raw(args, raw_path)
                last_hash = image_hash(raw_path)
                if last_hash != previous_raw_hash:
                    return last_hash
            print(
                f"identical_page_confirmed={expected_page} counter={current}/{total or '?'}",
                flush=True,
            )
            return last_hash

        if current == previous_page:
            if redeliveries >= 1:
                if allow_final_page:
                    print(
                        f"final_page_detected={previous_page} verified_stalls=2",
                        flush=True,
                    )
                    return None
                raise RuntimeError(
                    f"Reader did not advance from page {previous_page} after two key deliveries"
                )
            press_key_fast(args, "Right")
            redeliveries += 1
            time.sleep(args.retry_seconds)
            continue

        raise RuntimeError(
            f"Reader moved unexpectedly during capture: {current}/{total or '?'}; "
            f"expected {expected_page}/{expected_total or '?'}"
        )
    raise RuntimeError(
        f"Page {expected_page} remained identical to the previous page after "
        f"{args.max_refreshes} refreshes (hash={last_hash})"
    )


def audit_counter(
    args: argparse.Namespace, expected_page: int, expected_total: int | None
) -> None:
    """Verify a burst boundary and recover one delayed or missed key delivery.

    Millie's accessibility counter can trail the rendered page briefly.  Give it
    a wider polling window before assuming a key was dropped.  If it still shows
    the preceding page, deliver one replacement key; an overshoot is restored
    safely with Left before capture continues.
    """
    last_seen: tuple[int, int] | None = None
    audit_refreshes = min(max(8, args.render_confirmations * 2), args.max_refreshes)
    for attempt in range(audit_refreshes):
        current, total, _ = get_state(args)
        last_seen = (current, total)
        if current == expected_page and (
            expected_total is None or total == expected_total
        ):
            return
        if current > expected_page or (
            expected_total is not None and total not in {0, expected_total}
        ):
            break
        if attempt + 1 < audit_refreshes:
            time.sleep(max(args.retry_seconds, 0.05))

    observed_page, observed_total = last_seen or (0, 0)
    if observed_page == expected_page - 1 and (
        expected_total is None or observed_total in {0, expected_total}
    ):
        press_key_fast(args, "Right")
        recovery_refreshes = min(max(10, audit_refreshes), args.max_refreshes)
        for attempt in range(recovery_refreshes):
            current, total, _ = get_state(args)
            last_seen = (current, total)
            total_matches = expected_total is None or total == expected_total
            if current == expected_page and total_matches:
                print(
                    f"counter_audit_recovered={expected_page} action=redeliver-right",
                    flush=True,
                )
                return
            if current == expected_page + 1 and total_matches:
                restored_state = press_key(args, "Left")
                wait_for_counter(
                    args,
                    expected_page,
                    expected_total=expected_total,
                    initial_state=restored_state,
                )
                print(
                    f"counter_audit_recovered={expected_page} action=restore-left",
                    flush=True,
                )
                return
            if current > expected_page + 1 or (
                expected_total is not None and total not in {0, expected_total}
            ):
                break
            if attempt + 1 < recovery_refreshes:
                time.sleep(max(args.retry_seconds, 0.05))

    observed_page, observed_total = last_seen or (0, 0)
    raise RuntimeError(
        f"Counter audit failed: observed {observed_page}/{observed_total or '?'}, "
        f"expected {expected_page}/{expected_total or '?'}"
    )


def normalize_and_hash(
    raw_path: Path, output_path: Path, args: argparse.Namespace
) -> str:
    normalize_screenshot(
        raw_path,
        output_path,
        args.target_width,
        args.target_height,
        args.trim_ratio,
    )
    return image_hash(output_path)


def write_manifest(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def collect_finished_workers(
    jobs: dict[int, Future[str]], completed_hashes: dict[int, str]
) -> None:
    for page, future in list(jobs.items()):
        if future.done():
            completed_hashes[page] = future.result()
            del jobs[page]


def main() -> None:
    args = parse_args()
    if args.native_script is None:
        sibling = Path(__file__).resolve().with_name("millie_native.scpt")
        args.native_script = sibling if sibling.is_file() else sibling.with_suffix(".applescript")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.start_page < 1:
        raise SystemExit(f"Invalid start page {args.start_page}")
    existing_pages = scan_contiguous_pages(output_dir)
    expected_existing = args.start_page - 1
    if existing_pages != expected_existing:
        raise RuntimeError(
            f"이어갈 이미지 구간이 일치하지 않습니다: files=1-{existing_pages or 0}, "
            f"expected=1-{expected_existing}"
        )

    navigation_target = args.start_page
    if args.expected_total and navigation_target > args.expected_total:
        navigation_target = args.expected_total
    state = (
        rewind_and_warm_reader(args)
        if args.start_page == 1
        else move_reader_to_page(args, navigation_target)
    )
    args.cg_window_id = args.cg_window_id or (
        resolve_cg_window_id(args.app_pid) if args.app_pid else None
    )
    if args.cg_window_id is None:
        raise RuntimeError("밀리의서재의 화면 캡처 창 번호를 확인하지 못했습니다.")
    print(
        f"app_pid={args.app_pid} core_graphics_window={args.cg_window_id} "
        f"capture_backend=core-graphics-fast accessibility=verified-burst-"
        f"{max(1, args.counter_audit_interval)}",
        flush=True,
    )
    current, total, title = state
    if current != navigation_target:
        raise RuntimeError(
            f"Reader resume seek failed; current page is {current}, expected={navigation_target}"
        )
    known_total = total if total > 0 else None
    if args.expected_total:
        if known_total is not None and known_total != args.expected_total:
            raise RuntimeError(
                f"책의 전체 쪽수가 변경되었습니다: previous={args.expected_total}, current={known_total}"
            )
        known_total = args.expected_total
    end_page = args.end_page or known_total
    if end_page is not None and end_page < 1:
        raise SystemExit(f"Invalid end page {end_page}")
    if known_total is not None and end_page is not None and end_page > known_total:
        raise SystemExit(f"Invalid end page {end_page}; total={known_total}")
    if end_page is not None and args.start_page > end_page + 1:
        raise SystemExit(
            f"Invalid resume start page {args.start_page}; end={end_page}"
        )

    if args.resume_file:
        update_resume(
            args.resume_file.expanduser(),
            total_pages=end_page or known_total or 0,
            last_opened_title=title,
        )

    if args.status_file:
        if args.start_page > 1:
            initial_message = (
                f"기존 {existing_pages}쪽을 확인했습니다. {args.start_page}쪽부터 이어서 캡처합니다."
                if end_page is None or args.start_page <= end_page
                else f"기존 {existing_pages}쪽 전체를 확인했습니다. 결과 제작을 이어갑니다."
            )
        else:
            initial_message = (
                f"전체 {end_page}쪽을 확인했습니다. 고속 캡처를 시작합니다."
                if end_page is not None
                else "현재 쪽수를 확인했습니다. 마지막 쪽까지 고속 캡처합니다."
            )
        update_status(
            args.status_file.expanduser(),
            state="running",
            phase="capture",
            message=initial_message,
            book_title=title,
            current=existing_pages,
            total=end_page or 0,
            rate=0.0,
            phase_progress=(existing_pages / end_page) if end_page else None,
        )

    manifest = {
        "app": args.app,
        "app_pid": args.app_pid,
        "cg_window_id": args.cg_window_id,
        "title": title,
        "start_page": 1,
        "resumed_from_page": args.start_page if args.start_page > 1 else None,
        "end_page": end_page,
        "total_pages": known_total,
        "target_size": [args.target_width, args.target_height],
        "capture_mode": "core-graphics-verified-burst",
        "counter_audit_interval": max(1, args.counter_audit_interval),
        "pages": [],
    }
    jobs: dict[int, Future[str]] = {}
    completed_hashes: dict[int, str] = {
        page: image_hash(output_dir / f"page_{page:04d}.png")
        for page in range(1, existing_pages + 1)
    }
    output_paths: dict[int, Path] = {
        page: output_dir / f"page_{page:04d}.png"
        for page in range(1, existing_pages + 1)
    }
    previous_raw_hash = None
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="millie-fast-capture-") as temporary:
        raw_dir = Path(temporary)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            page = args.start_page
            while end_page is None or page <= end_page:
                audit_interval = max(1, args.counter_audit_interval)
                if page > 1 and page % audit_interval == 0:
                    # Verify the reader reached this page before taking its image.
                    # This prevents a late page turn from being saved under the
                    # next page number at a burst boundary.
                    audit_counter(args, page, known_total)

                raw_path = raw_dir / f"raw_{page:04d}.{args.raw_format}"
                output_path = output_dir / f"page_{page:04d}.png"
                captured_hash = capture_distinct_raw(
                    args,
                    raw_path,
                    page,
                    known_total,
                    previous_raw_hash,
                    allow_final_page=known_total is None and page > 1,
                )
                if captured_hash is None:
                    end_page = page - 1
                    known_total = end_page
                    manifest["end_page"] = end_page
                    manifest["total_pages"] = end_page
                    if args.resume_file:
                        update_resume(
                            args.resume_file.expanduser(), total_pages=end_page
                        )
                    if args.status_file:
                        elapsed = max(time.perf_counter() - started, 0.001)
                        captured_this_run = max(0, end_page - args.start_page + 1)
                        update_status(
                            args.status_file.expanduser(),
                            state="running",
                            phase="capture",
                            message=f"마지막 {end_page}쪽까지 캡처했습니다.",
                            current=end_page,
                            total=end_page,
                            rate=round(captured_this_run / elapsed, 3),
                            phase_progress=1.0,
                        )
                    break
                previous_raw_hash = captured_hash
                output_paths[page] = output_path
                jobs[page] = executor.submit(
                    normalize_and_hash, raw_path, output_path, args
                )
                collect_finished_workers(jobs, completed_hashes)

                elapsed = max(time.perf_counter() - started, 0.001)
                captured_this_run = page - args.start_page + 1
                capture_rate = captured_this_run / elapsed
                print(
                    f"captured={page}/{end_page or '?'} rate={capture_rate:.2f}pps "
                    f"file={output_path.name}",
                    flush=True,
                )
                if args.status_file:
                    update_status(
                        args.status_file.expanduser(),
                        state="running",
                        phase="capture",
                        message=f"{page}쪽을 안전하게 저장했습니다.",
                        current=page,
                        total=end_page or 0,
                        rate=round(capture_rate, 3),
                        phase_progress=(page / end_page) if end_page else None,
                        add_history=page == 1 or page == end_page or page % 10 == 0,
                    )

                if end_page is not None and page >= end_page:
                    break

                press_key_fast(args, "Right")
                page += 1

            if end_page is None:
                raise RuntimeError("Capture ended without determining the final page")
            for page in range(1, end_page + 1):
                page_hash = (
                    completed_hashes[page]
                    if page in completed_hashes
                    else jobs[page].result()
                )
                manifest["pages"].append(
                    {
                        "reader_page": page,
                        "file": output_paths[page].name,
                        "sha256": page_hash,
                    }
                )

    write_manifest(output_dir / "capture_manifest.json", manifest)
    final_pages = scan_contiguous_pages(output_dir)
    if final_pages != end_page or not (output_dir / f"page_{end_page:04d}.png").is_file():
        raise RuntimeError(
            f"Capture completeness check failed: files={final_pages}, "
            f"expected={end_page}, last=page_{end_page:04d}.png"
        )
    if args.resume_file:
        update_resume(
            args.resume_file.expanduser(),
            total_pages=end_page,
            capture_complete=True,
        )
    elapsed = max(time.perf_counter() - started, 0.001)
    captured_this_run = max(0, end_page - args.start_page + 1)
    print(f"output_dir={output_dir}")
    print(f"captured_pages={len(manifest['pages'])}")
    print(f"capture_seconds={elapsed:.2f}")
    print(f"capture_rate={captured_this_run / elapsed:.2f}pps")


if __name__ == "__main__":
    main()
