#!/usr/bin/env python3
"""Build a continuous reflowable EPUB 3 with cover and extracted visuals."""

from __future__ import annotations

import argparse
import html
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from status_store import update_status


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
VISUAL_LABELS = {"Figure", "Picture", "Diagram", "Chart", "Image", "Table", "Equation"}


@dataclass(frozen=True)
class VisualAsset:
    label: str
    filename: str
    path: Path


@dataclass(frozen=True)
class TocEntry:
    title: str
    anchor: str
    level: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_txt", type=Path)
    parser.add_argument("output_epub", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--images-dir", type=Path)
    parser.add_argument("--results-json", type=Path)
    parser.add_argument("--assets-dir", type=Path)
    parser.add_argument("--status-file", type=Path)
    return parser.parse_args()


def report_status(status_file: Path | None, message: str, progress: float) -> None:
    if status_file is None:
        return
    update_status(
        status_file.expanduser(),
        state="running",
        phase="epub",
        message=message,
        phase_progress=progress,
    )


def clean_page(page: str) -> str:
    page = page.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in page.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def plain_text(fragment: str) -> str:
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"(?i)</(?:p|div|li|h[1-6])>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    lines = [re.sub(r"\s+", " ", html.unescape(line)).strip() for line in fragment.splitlines()]
    return " ".join(line for line in lines if line).strip()


def resolve_images(images_dir: Path) -> list[Path]:
    if not images_dir.is_dir():
        raise SystemExit(f"EPUB 페이지 이미지 폴더가 없습니다: {images_dir}")
    images = sorted(path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise SystemExit(f"EPUB에 사용할 페이지 이미지가 없습니다: {images_dir}")
    return images


def chapter_marker(blocks: list[dict[str, Any]]) -> tuple[int, int, int] | None:
    """Return the CHAPTER block index, number block index, and chapter number."""
    for index, block in enumerate(blocks):
        if plain_text(str(block.get("html") or "")).upper() != "CHAPTER":
            continue
        for number_index in range(index + 1, min(index + 3, len(blocks))):
            number_text = plain_text(str(blocks[number_index].get("html") or ""))
            if re.fullmatch(r"\d{1,2}", number_text):
                return index, number_index, int(number_text)
    return None


def source_toc_pages(images: list[Path], data: dict[str, Any]) -> set[int]:
    """Locate printed contents pages so they do not duplicate EPUB navigation."""
    start: int | None = None
    for page_index, image in enumerate(images):
        blocks = (data.get(image.stem) or [{}])[0].get("blocks", [])
        texts = {plain_text(str(block.get("html") or "")).upper() for block in blocks}
        if "CONTENTS" in texts or "목차" in texts:
            start = page_index
            break
    if start is None:
        return set()

    pages: set[int] = set()
    for page_index in range(start, min(len(images), start + 12)):
        blocks = (data.get(images[page_index].stem) or [{}])[0].get("blocks", [])
        marker = chapter_marker(blocks) if isinstance(blocks, list) else None
        if page_index > start and marker is not None and marker[2] == 1:
            break
        pages.add(page_index)
    return pages


def extract_chapter_titles(
    images: list[Path],
    data: dict[str, Any],
    toc_pages: set[int],
) -> dict[int, str]:
    """Read chapter titles from the printed contents pages when available."""
    titles: dict[int, str] = {}
    active_number: int | None = None
    title_parts: list[str] = []
    waiting_for_number = False

    def finish() -> None:
        nonlocal active_number, title_parts
        title = " ".join(title_parts).strip()
        if active_number is not None and title:
            titles.setdefault(active_number, title)
        active_number = None
        title_parts = []

    for page_index in sorted(toc_pages):
        blocks = (data.get(images[page_index].stem) or [{}])[0].get("blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            text = plain_text(str(block.get("html") or ""))
            if not text:
                continue
            if text.upper() == "CHAPTER":
                finish()
                waiting_for_number = True
                continue
            if waiting_for_number and re.fullmatch(r"\d{1,2}", text):
                active_number = int(text)
                waiting_for_number = False
                continue
            if active_number is None:
                continue
            if re.match(r"^\d{1,2}\s+", text) or text.startswith("쉬어가기"):
                finish()
                continue
            if block.get("label") in {"Text", "SectionHeader"} and len(title_parts) < 3:
                title_parts.append(text)
    finish()
    return titles


def crop_white_margin(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")).convert("L")
    bounds = difference.point(lambda value: 255 if value > 14 else 0).getbbox()
    if not bounds:
        return rgb
    left, top, right, bottom = bounds
    padding = max(4, min(rgb.size) // 200)
    return rgb.crop((max(0, left - padding), max(0, top - padding), min(rgb.width, right + padding), min(rgb.height, bottom + padding)))


def save_cover(first_page: Path, assets_dir: Path) -> Path:
    cover_path = assets_dir / "cover.jpg"
    with Image.open(first_page) as source:
        cover = crop_white_margin(source)
        cover.thumbnail((1600, 2400), Image.Resampling.LANCZOS)
        cover.save(cover_path, "JPEG", quality=92, optimize=True, progressive=True)
    return cover_path


def valid_bbox(block: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int] | None:
    bbox = block.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    padding = 10
    bounds = (
        max(0, int(x0) - padding),
        max(0, int(y0) - padding),
        min(width, int(x1 + 0.999) + padding),
        min(height, int(y1 + 0.999) + padding),
    )
    left, top, right, bottom = bounds
    if right - left < 80 or bottom - top < 80:
        return None
    if (right - left) * (bottom - top) < width * height * 0.002:
        return None
    return bounds


def extract_assets(
    images: list[Path],
    data: dict[str, Any],
    assets_dir: Path,
    status_file: Path | None,
) -> tuple[Path, dict[str, dict[int, VisualAsset]], int]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    cover_path = save_cover(images[0], assets_dir)
    report_status(status_file, "첫 페이지를 EPUB 표지로 설정했습니다.", 0.18)
    visual_by_page: dict[str, dict[int, VisualAsset]] = {}
    visual_count = 0
    total = len(images)
    for page_number, image_path in enumerate(images, start=1):
        page_assets: dict[int, VisualAsset] = {}
        page_result = (data.get(image_path.stem) or [{}])[0]
        blocks = page_result.get("blocks", [])
        if page_number > 1 and isinstance(blocks, list):
            with Image.open(image_path) as source:
                source_rgb = source.convert("RGB")
                page_visual_index = 0
                for block_index, block in enumerate(blocks):
                    if not isinstance(block, dict) or block.get("label") not in VISUAL_LABELS:
                        continue
                    bounds = valid_bbox(block, source_rgb.width, source_rgb.height)
                    if bounds is None:
                        continue
                    page_visual_index += 1
                    visual_count += 1
                    label = str(block.get("label") or "Figure")
                    filename = f"{image_path.stem}_{label.lower()}_{page_visual_index:02d}.jpg"
                    output_path = assets_dir / filename
                    source_rgb.crop(bounds).save(output_path, "JPEG", quality=91, optimize=True, progressive=True)
                    page_assets[block_index] = VisualAsset(label, filename, output_path)
        visual_by_page[image_path.stem] = page_assets
        if page_number == total or page_number % 10 == 0:
            report_status(
                status_file,
                f"EPUB 이미지 추출 {page_number}/{total}쪽 · {visual_count}개 발견",
                0.18 + 0.52 * page_number / max(1, total),
            )
    return cover_path, visual_by_page, visual_count


def fallback_paragraphs(page: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", page).strip()
    return [f"<p>{html.escape(normalized)}</p>"] if normalized else []


def page_elements(
    fallback_page: str,
    image_stem: str | None,
    data: dict[str, Any],
    visual_by_page: dict[str, dict[int, VisualAsset]],
    *,
    page_index: int,
    printed_toc_pages: set[int],
    chapter_titles: dict[int, str],
    toc_entries: list[TocEntry],
) -> list[str]:
    elements: list[str] = []
    if image_stem is not None:
        page_result = (data.get(image_stem) or [{}])[0]
        blocks = page_result.get("blocks", [])
        assets = visual_by_page.get(image_stem, {})
        if isinstance(blocks, list):
            marker = chapter_marker(blocks) if page_index not in printed_toc_pages else None
            marker_indexes = {marker[0], marker[1]} if marker is not None else set()
            page_headers = {
                plain_text(str(block.get("html") or "")).upper()
                for block in blocks
                if block.get("label") == "PageHeader"
            }
            for block_index, block in enumerate(blocks):
                if marker is not None and block_index == marker[0]:
                    chapter_number = marker[2]
                    chapter_title = chapter_titles.get(chapter_number, "")
                    anchor = f"chapter-{chapter_number:02d}"
                    nav_title = f"{chapter_number:02d}. {chapter_title}" if chapter_title else f"CHAPTER {chapter_number:02d}"
                    heading = f'<span class="chapter-label">CHAPTER {chapter_number:02d}</span>'
                    if chapter_title:
                        heading += f"<br/>{html.escape(chapter_title)}"
                    elements.append(f'<h1 id="{anchor}">{heading}</h1>')
                    toc_entries.append(TocEntry(nav_title, anchor, 1))
                    continue
                if block_index in marker_indexes:
                    continue
                asset = assets.get(block_index)
                if asset is not None:
                    elements.append(
                        f'<figure><img src="images/{html.escape(asset.filename)}" alt="{html.escape(asset.label)}"/></figure>'
                    )
                    continue
                if not isinstance(block, dict) or block.get("skipped") or block.get("error"):
                    continue
                text = plain_text(str(block.get("html") or ""))
                if not text:
                    continue
                escaped = html.escape(text)
                label = block.get("label")
                if label == "SectionHeader":
                    if page_index in printed_toc_pages or text.upper() == "CHAPTER" or re.fullmatch(r"\d{1,2}", text):
                        elements.append(f"<h2>{escaped}</h2>")
                    else:
                        anchor = f"section-{page_index + 1:04d}-{block_index:02d}"
                        level = 1 if page_headers & {"PROLOGUE", "EPILOGUE"} else 2
                        nav_title = text
                        if "PROLOGUE" in page_headers:
                            nav_title = f"프롤로그 · {text}"
                        elif "EPILOGUE" in page_headers:
                            nav_title = f"에필로그 · {text}"
                        elements.append(f'<h2 id="{anchor}">{escaped}</h2>')
                        toc_entries.append(TocEntry(nav_title, anchor, level))
                elif label == "Caption":
                    elements.append(f'<p class="caption">{escaped}</p>')
                elif label == "Footnote":
                    elements.append(f'<aside class="footnote">{escaped}</aside>')
                else:
                    elements.append(f"<p>{escaped}</p>")
    return elements or fallback_paragraphs(fallback_page)


def navigation_list(entries: list[TocEntry]) -> str:
    if not entries:
        return '<ol><li><a href="content.xhtml">본문</a></li></ol>'
    output = ["<ol>"]
    parent_open = False
    nested_open = False
    for entry in entries:
        link = f'<a href="content.xhtml#{html.escape(entry.anchor)}">{html.escape(entry.title)}</a>'
        if entry.level <= 1:
            if nested_open:
                output.append("</ol></li>")
                nested_open = False
                parent_open = False
            elif parent_open:
                output.append("</li>")
                parent_open = False
            output.append(f"<li>{link}")
            parent_open = True
        else:
            if not parent_open:
                output.append('<li><a href="content.xhtml">본문</a>')
                parent_open = True
            if not nested_open:
                output.append("<ol>")
                nested_open = True
            output.append(f"<li>{link}</li>")
    if nested_open:
        output.append("</ol></li>")
    elif parent_open:
        output.append("</li>")
    output.append("</ol>")
    return "".join(output)


def merge_page_elements(target: list[str], incoming: list[str]) -> None:
    """Join a paragraph split only because the source moved to the next page."""
    if target and incoming and target[-1].startswith("<p>") and incoming[0].startswith("<p>"):
        previous_text = html.unescape(re.sub(r"<[^>]+>", "", target[-1])).strip()
        if previous_text and not re.search(r'[.!?。！？…]["”’\)\]]?$', previous_text):
            previous = target.pop()
            following = incoming.pop(0)
            following_text = html.unescape(re.sub(r"<[^>]+>", "", following)).strip()
            first_word = following_text.split(maxsplit=1)[0] if following_text else ""
            korean_continuation = (
                bool(re.search(r"[가-힣]$", previous_text))
                and len(first_word) == 1
                and first_word in "고며은는이가을를에도와과의로서만부터까지처럼보다"
            )
            if previous.endswith("-</p>"):
                target.append(previous[:-5] + following[3:])
            elif korean_continuation:
                target.append(previous[:-4] + following[3:])
            else:
                target.append(previous[:-4] + " " + following[3:])
    target.extend(incoming)


def xhtml_document(title: str, body: str, *, body_class: str = "") -> str:
    class_attribute = f' class="{html.escape(body_class)}"' if body_class else ""
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko" xml:lang="ko">
<head><title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="styles.css"/></head>
<body{class_attribute}>{body}</body>
</html>
'''


def build_epub(
    input_txt: Path,
    output_epub: Path,
    title: str,
    *,
    images_dir: Path | None = None,
    results_json: Path | None = None,
    assets_dir: Path | None = None,
    status_file: Path | None = None,
) -> tuple[int, int, Path | None]:
    text = input_txt.read_text(encoding="utf-8", errors="replace")
    pages = [clean_page(page) for page in text.split("\f")]
    while pages and not pages[-1]:
        pages.pop()
    if not pages:
        raise SystemExit("EPUB으로 만들 OCR 본문이 없습니다.")

    images: list[Path] = []
    data: dict[str, Any] = {}
    visual_by_page: dict[str, dict[int, VisualAsset]] = {}
    visual_count = 0
    cover_path: Path | None = None
    if images_dir is not None:
        images = resolve_images(images_dir.resolve())
        if len(images) != len(pages):
            raise SystemExit(f"EPUB 본문과 페이지 이미지 수가 다릅니다: {len(pages)} != {len(images)}")
        if results_json is None or not results_json.is_file():
            raise SystemExit("EPUB 내부 이미지 추출에 필요한 Surya results.json이 없습니다.")
        data = json.loads(results_json.read_text(encoding="utf-8"))
        missing = [image.stem for image in images if image.stem not in data]
        if missing:
            raise SystemExit(f"EPUB OCR 결과에 누락된 페이지가 있습니다: {', '.join(missing[:5])}")
        cover_path, visual_by_page, visual_count = extract_assets(
            images,
            data,
            (assets_dir or output_epub.parent / "epub-assets").resolve(),
            status_file,
        )

    identifier = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    elements: list[str] = []
    toc_entries: list[TocEntry] = []
    printed_toc_pages = source_toc_pages(images, data) if images else set()
    chapter_titles = extract_chapter_titles(images, data, printed_toc_pages) if images else {}
    first_body_page = 1 if cover_path is not None else 0
    for page_index in range(first_body_page, len(pages)):
        page = pages[page_index]
        image_stem = images[page_index].stem if images else None
        merge_page_elements(
            elements,
            page_elements(
                page,
                image_stem,
                data,
                visual_by_page,
                page_index=page_index,
                printed_toc_pages=printed_toc_pages,
                chapter_titles=chapter_titles,
                toc_entries=toc_entries,
            ),
        )
    content_docs = {"content.xhtml": xhtml_document(title, "\n".join(elements))}
    content_items = ['<item id="content" href="content.xhtml" media-type="application/xhtml+xml"/>']
    spine_items = ['<itemref idref="content"/>']

    report_status(status_file, f"표지와 본문 이미지 {visual_count}개를 연속 본문에 병합하고 있습니다.", 0.82)
    nav = xhtml_document(
        title,
        f'<nav epub:type="toc" id="toc"><h1>{html.escape(title)}</h1>{navigation_list(toc_entries)}</nav>',
    )
    cover_manifest = ""
    cover_spine = ""
    cover_document = ""
    if cover_path is not None:
        cover_manifest = '''<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
  <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>'''
        cover_spine = '<itemref idref="cover" linear="yes"/>'
        cover_document = xhtml_document(
            title,
            f'<section epub:type="cover"><img src="images/cover.jpg" alt="{html.escape(title)} 표지"/></section>',
            body_class="cover-page",
        )
    all_visual_assets = [asset for page in visual_by_page.values() for asset in page.values()]
    visual_manifest = "".join(
        f'<item id="visual-{index:04d}" href="images/{html.escape(asset.filename)}" media-type="image/jpeg"/>'
        for index, asset in enumerate(all_visual_assets, start=1)
    )
    package = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="ko">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:identifier id="book-id">{identifier}</dc:identifier>
  <dc:title>{html.escape(title)}</dc:title>
  <dc:language>ko</dc:language>
  <meta property="dcterms:modified">{modified}</meta>
  {'<meta name="cover" content="cover-image"/>' if cover_path is not None else ''}
</metadata>
<manifest>
  <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  <item id="styles" href="styles.css" media-type="text/css"/>
  {cover_manifest}
  {visual_manifest}
  {''.join(content_items)}
</manifest>
<spine>{cover_spine}{''.join(spine_items)}</spine>
</package>
'''
    container = '''<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
'''
    styles = '''body { font-family: -apple-system, sans-serif; line-height: 1.75; margin: 5%; }
h1 { font-size: 1.35em; margin: 0 0 2em; }
h2 { font-size: 1.18em; margin: 1.6em 0 .8em; }
.chapter-label { color: #666; font-size: .72em; letter-spacing: .08em; }
p { margin: 0 0 1em; text-align: justify; }
figure { margin: 1.5em auto; text-align: center; break-inside: avoid; }
figure img { display: block; width: auto; max-width: 100%; max-height: 90vh; margin: 0 auto; }
.caption { color: #555; font-size: .92em; text-align: center; }
.footnote { color: #555; font-size: .85em; }
.cover-page { margin: 0; padding: 0; text-align: center; }
.cover-page section, .cover-page img { display: block; width: 100%; height: auto; margin: 0 auto; }
nav ol { line-height: 1.8; }
'''

    output_epub.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("EPUB/package.opf", package, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("EPUB/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("EPUB/styles.css", styles, compress_type=zipfile.ZIP_DEFLATED)
        if cover_path is not None:
            archive.writestr("EPUB/cover.xhtml", cover_document, compress_type=zipfile.ZIP_DEFLATED)
            archive.write(cover_path, "EPUB/images/cover.jpg", compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("EPUB/content.xhtml", content_docs["content.xhtml"], compress_type=zipfile.ZIP_DEFLATED)
        for asset in all_visual_assets:
            archive.write(asset.path, f"EPUB/images/{asset.filename}", compress_type=zipfile.ZIP_DEFLATED)

    report_status(status_file, "EPUB 파일 구조와 표지·본문 이미지를 검증하고 있습니다.", 0.95)
    with zipfile.ZipFile(output_epub) as archive:
        names = set(archive.namelist())
        if archive.namelist()[0] != "mimetype" or archive.read("mimetype") != b"application/epub+zip":
            raise SystemExit("EPUB mimetype 검증에 실패했습니다.")
        if archive.testzip() is not None:
            raise SystemExit("EPUB ZIP 검증에 실패했습니다.")
        if cover_path is not None and {"EPUB/cover.xhtml", "EPUB/images/cover.jpg"} - names:
            raise SystemExit("EPUB 표지 검증에 실패했습니다.")
        for document in content_docs.values():
            for source in re.findall(r'<img src="([^"]+)"', document):
                if f"EPUB/{source}" not in names:
                    raise SystemExit(f"EPUB 본문 이미지가 누락됐습니다: {source}")
            if re.search(r">\s*\d+\s*[–-]\s*\d+쪽\s*<", document):
                raise SystemExit("EPUB 본문에 페이지 범위 제목이 남아 있습니다.")
            if "epub:type=\"pagebreak\"" in document:
                raise SystemExit("EPUB 본문에 페이지 번호 표시가 남아 있습니다.")
    report_status(status_file, f"표지와 본문 이미지 {visual_count}개가 포함된 연속 EPUB을 완성했습니다.", 1.0)
    return len(pages), visual_count, cover_path


def main() -> None:
    args = parse_args()
    pages, visuals, cover = build_epub(
        args.input_txt.resolve(),
        args.output_epub.resolve(),
        args.title.strip(),
        images_dir=args.images_dir,
        results_json=args.results_json.resolve() if args.results_json else None,
        assets_dir=args.assets_dir,
        status_file=args.status_file,
    )
    print(f"output={args.output_epub.resolve()}")
    print(f"pages={pages}")
    print(f"visual_images={visuals}")
    if cover is not None:
        print(f"cover={cover}")


if __name__ == "__main__":
    main()
