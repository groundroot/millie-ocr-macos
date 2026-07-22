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
    parser.add_argument("--target-width", type=int, default=1748)
    parser.add_argument("--target-height", type=int, default=2480)
    parser.add_argument("--trim-ratio", type=float, default=0.025)
    parser.add_argument("--raw-format", choices=("jpg", "png"), default="jpg")
    parser.add_argument("--native-script", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--retry-seconds", type=float, default=0.02)
    parser.add_argument("--max-refreshes", type=int, default=80)
    parser.add_argument("--reader-ready-seconds", type=float, default=8.0)
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
            slider_match = SLIDER_PAGE_COUNTER.search(tree)
            if slider_match:
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
            if "열린 책 창" not in str(error) and "실행 중" not in str(error):
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
            if "열린 책 창" not in str(error) and "실행 중" not in str(error):
                raise
    raise RuntimeError(f"Reader could not retain keyboard focus: {last_error}")


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


def advance_without_known_total(
    args: argparse.Namespace,
    current_page: int,
) -> State | None:
    """Advance a slider-only reader, returning None after two verified stalls."""
    expected = current_page + 1
    last_seen: tuple[int, int] | None = None
    for delivery in range(2):
        if delivery:
            activate_reader(args.app)
            time.sleep(0.12)
        initial_result = run_native(args, "press", "Right")

        for attempt in range(args.max_refreshes):
            result = initial_result if attempt == 0 else get_state_result(
                args, restore=delivery > 0
            )
            try:
                state = state_from_result(result)
            except RuntimeError as error:
                if "page counter was not found" not in str(error):
                    raise
                time.sleep(args.retry_seconds)
                continue

            observed_page, observed_total, _ = state
            last_seen = (observed_page, observed_total)
            if observed_page == expected:
                return state
            if observed_page > expected:
                raise RuntimeError(
                    f"Reader skipped a page: expected {expected}, observed {observed_page}"
                )
            if observed_page < current_page:
                raise RuntimeError(
                    f"Reader moved backwards: current {current_page}, observed {observed_page}"
                )
            time.sleep(args.retry_seconds)

    print(
        f"final_page_detected={current_page} last_seen={last_seen} verified_stalls=2",
        flush=True,
    )
    return None


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
) -> str:
    last_hash = None
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
        if attempt == 1:
            current, total, _ = get_state(args)
            if current != expected_page or (
                expected_total is not None and total != expected_total
            ):
                raise RuntimeError(
                    f"Reader moved unexpectedly during capture: {current}/{total or '?'}"
                )
        time.sleep(args.retry_seconds)
    raise RuntimeError(
        f"Page {expected_page} remained identical to the previous page after "
        f"{args.max_refreshes} refreshes (hash={last_hash})"
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

    state = rewind_and_warm_reader(args)
    args.cg_window_id = args.cg_window_id or (
        resolve_cg_window_id(args.app_pid) if args.app_pid else None
    )
    if args.cg_window_id is None:
        raise RuntimeError("밀리의서재의 화면 캡처 창 번호를 확인하지 못했습니다.")
    print(
        f"app_pid={args.app_pid} core_graphics_window={args.cg_window_id} "
        "capture_backend=core-graphics-fast accessibility=counter-only-fast",
        flush=True,
    )
    current, total, title = state
    if current != 1:
        raise RuntimeError(f"Reader rewind failed; current page is {current}")
    known_total = total if total > 0 else None
    end_page = args.end_page or known_total
    if end_page is not None and end_page < 1:
        raise SystemExit(f"Invalid end page {end_page}")
    if known_total is not None and end_page is not None and end_page > known_total:
        raise SystemExit(f"Invalid end page {end_page}; total={known_total}")

    if args.status_file:
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
            current=0,
            total=end_page or 0,
            rate=0.0,
            phase_progress=0.0 if end_page is not None else None,
        )

    manifest = {
        "app": args.app,
        "app_pid": args.app_pid,
        "cg_window_id": args.cg_window_id,
        "title": title,
        "start_page": 1,
        "end_page": end_page,
        "total_pages": known_total,
        "target_size": [args.target_width, args.target_height],
        "capture_mode": "core-graphics-fast",
        "pages": [],
    }
    jobs: dict[int, Future[str]] = {}
    completed_hashes: dict[int, str] = {}
    output_paths: dict[int, Path] = {}
    previous_raw_hash = None
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="millie-fast-capture-") as temporary:
        raw_dir = Path(temporary)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            page = 1
            while True:
                current, observed_total, title = state
                if current != page or (
                    known_total is not None and observed_total != known_total
                ):
                    raise RuntimeError(
                        f"Unexpected reader state {current}/{observed_total or '?'}; "
                        f"expected {page}/{known_total or '?'}"
                    )

                raw_path = raw_dir / f"raw_{page:04d}.{args.raw_format}"
                output_path = output_dir / f"page_{page:04d}.png"
                previous_raw_hash = capture_distinct_raw(
                    args,
                    raw_path,
                    page,
                    known_total,
                    previous_raw_hash,
                )
                output_paths[page] = output_path
                jobs[page] = executor.submit(
                    normalize_and_hash, raw_path, output_path, args
                )
                collect_finished_workers(jobs, completed_hashes)

                elapsed = max(time.perf_counter() - started, 0.001)
                capture_rate = page / elapsed
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

                if known_total is not None:
                    pressed_state = press_key(args, "Right")
                    state = wait_for_counter(
                        args, page + 1, known_total, initial_state=pressed_state
                    )
                else:
                    next_state = advance_without_known_total(args, page)
                    if next_state is None:
                        end_page = page
                        known_total = page
                        manifest["end_page"] = end_page
                        manifest["total_pages"] = end_page
                        if args.status_file:
                            update_status(
                                args.status_file.expanduser(),
                                state="running",
                                phase="capture",
                                message=f"마지막 {end_page}쪽까지 캡처했습니다.",
                                current=end_page,
                                total=end_page,
                                rate=round(capture_rate, 3),
                                phase_progress=1.0,
                            )
                        break
                    state = next_state
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
    final_files = sorted(output_dir.glob("page_*.png"))
    if len(final_files) != end_page or not (output_dir / f"page_{end_page:04d}.png").is_file():
        raise RuntimeError(
            f"Capture completeness check failed: files={len(final_files)}, "
            f"expected={end_page}, last=page_{end_page:04d}.png"
        )
    elapsed = max(time.perf_counter() - started, 0.001)
    print(f"output_dir={output_dir}")
    print(f"captured_pages={len(manifest['pages'])}")
    print(f"capture_seconds={elapsed:.2f}")
    print(f"capture_rate={len(manifest['pages']) / elapsed:.2f}pps")


if __name__ == "__main__":
    main()
