#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import img2pdf
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from status_store import update_status


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
DEFAULT_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/System/Library/Fonts/Supplemental/NotoSansGothic-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
FONT_NAME = "KoreanOCRFont"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Surya Korean OCR and add an invisible Unicode text layer to ordered page images."
    )
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("--surya-bin", type=Path)
    parser.add_argument("--results-json", type=Path)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--backend", default="llamacpp")
    parser.add_argument("--status-file", type=Path)
    return parser.parse_args()


def report_status(args: argparse.Namespace, phase: str, message: str, progress: float | None = None) -> None:
    if not args.status_file:
        return
    update_status(
        args.status_file.expanduser(),
        state="running",
        phase=phase,
        message=message,
        phase_progress=progress,
    )


def resolve_images(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory not found: {input_dir}")
    images = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise SystemExit(f"No supported page images found in: {input_dir}")
    if len({p.stem for p in images}) != len(images):
        raise SystemExit("Image stems must be unique because Surya keys results by stem")
    return images


def resolve_font(explicit_font: Path | None) -> Path:
    if explicit_font:
        if not explicit_font.is_file():
            raise SystemExit(f"Font not found: {explicit_font}")
        return explicit_font
    for candidate in DEFAULT_FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    raise SystemExit("No Korean font found. Pass --font with an embeddable Korean TTF/OTF file")


def plain_text(fragment: str) -> str:
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"(?i)</(?:p|div|li|h[1-6])>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    lines = [re.sub(r"\s+", " ", line).strip() for line in html.unescape(fragment).splitlines()]
    return re.sub(r"\s+", " ", " ".join(line for line in lines if line)).strip()


def run_surya(args: argparse.Namespace, input_dir: Path, results_root: Path) -> Path:
    surya_bin = args.surya_bin or (Path(shutil.which("surya_ocr")) if shutil.which("surya_ocr") else None)
    if not surya_bin or not surya_bin.is_file():
        raise SystemExit("surya_ocr not found. Run install_surya_macos.sh or pass --surya-bin")

    environment = os.environ.copy()
    environment["SURYA_INFERENCE_BACKEND"] = args.backend
    environment.pop("SURYA_INFERENCE_KEEP_ALIVE", None)
    report_status(args, "ocr", "Surya 2가 각 페이지의 한글을 분석하고 있습니다.", 0.05)
    subprocess.run(
        [str(surya_bin), str(input_dir), "--output_dir", str(results_root)],
        check=True,
        env=environment,
    )

    report_status(args, "ocr", "한글 OCR 분석을 완료했습니다.", 1.0)
    expected = results_root / input_dir.name / "results.json"
    if expected.is_file():
        return expected
    matches = list(results_root.rglob("results.json"))
    if len(matches) != 1:
        raise SystemExit(f"Could not identify Surya results.json under {results_root}")
    return matches[0]


def create_background(images: list[Path], dpi: int, output_path: Path) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = []
    for image_path in images:
        with Image.open(image_path) as image:
            sizes.append(image.size)
    layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
    output_path.write_bytes(img2pdf.convert([str(p) for p in images], layout_fun=layout))
    return sizes


def create_overlay(
    data: dict,
    images: list[Path],
    sizes: list[tuple[int, int]],
    dpi: int,
    font_path: Path,
    output_path: Path,
) -> tuple[int, int]:
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_path)))
    pdf = canvas.Canvas(str(output_path), pageCompression=1)
    hangul = 0
    latin = 0

    for image_path, (pixel_width, pixel_height) in zip(images, sizes):
        page_width = pixel_width / dpi * 72
        page_height = pixel_height / dpi * 72
        pixel_to_point = 72 / dpi
        pdf.setPageSize((page_width, page_height))
        page_result = data.get(image_path.stem, [{}])[0]

        for block in page_result.get("blocks", []):
            if block.get("skipped") or block.get("error") or not block.get("html"):
                continue
            text = plain_text(block["html"])
            if not text:
                continue
            hangul += len(re.findall(r"[가-힣]", text))
            latin += len(re.findall(r"[A-Za-z]", text))

            x0, y0, x1, y1 = block["bbox"]
            left = x0 * pixel_to_point
            top = page_height - y0 * pixel_to_point
            max_width = max(1.0, (x1 - x0) * pixel_to_point)
            block_height = max(1.0, (y1 - y0) * pixel_to_point)
            font_size = min(6.5, max(3.5, block_height * 0.55))
            natural_width = max(0.1, pdfmetrics.stringWidth(text, FONT_NAME, font_size))
            horizontal_scale = min(100.0, max(1.0, max_width / natural_width * 100.0))

            text_object = pdf.beginText()
            text_object.setTextOrigin(left, top - font_size)
            text_object.setFont(FONT_NAME, font_size)
            text_object.setHorizScale(horizontal_scale)
            text_object.setTextRenderMode(3)
            text_object.textLine(text)
            pdf.drawText(text_object)
        pdf.showPage()
    pdf.save()
    return hangul, latin


def merge_pdf(background_path: Path, overlay_path: Path, output_path: Path) -> None:
    background = PdfReader(str(background_path))
    overlay = PdfReader(str(overlay_path))
    if len(background.pages) != len(overlay.pages):
        raise SystemExit("Background and OCR overlay page counts differ")

    writer = PdfWriter()
    for background_page, overlay_page in zip(background.pages, overlay.pages):
        background_page.merge_page(overlay_page, over=True)
        writer.add_page(background_page)
    writer.add_metadata({
        "/Title": output_path.stem,
        "/Producer": "Surya OCR 2 + img2pdf + ReportLab + pypdf",
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output_file:
        writer.write(output_file)


def build_pdf(args: argparse.Namespace, images: list[Path], results_json: Path, work_dir: Path) -> None:
    data = json.loads(results_json.read_text(encoding="utf-8"))
    missing = [p.stem for p in images if p.stem not in data]
    if missing:
        raise SystemExit(f"Surya results are missing image keys: {', '.join(missing)}")

    background_path = work_dir / "background.pdf"
    overlay_path = work_dir / "overlay.pdf"
    report_status(args, "pdf", "원본 페이지 이미지를 PDF로 묶고 있습니다.", 0.15)
    sizes = create_background(images, args.dpi, background_path)
    report_status(args, "pdf", "인식한 한글을 검색 가능한 텍스트 층으로 만들고 있습니다.", 0.5)
    hangul, latin = create_overlay(data, images, sizes, args.dpi, resolve_font(args.font), overlay_path)
    report_status(args, "pdf", "이미지와 텍스트 층을 하나의 PDF로 합치고 있습니다.", 0.8)
    merge_pdf(background_path, overlay_path, args.output_pdf.resolve())

    final_pdf = PdfReader(str(args.output_pdf.resolve()))
    if len(final_pdf.pages) != len(images):
        raise SystemExit("Final PDF page count does not match the image count")
    report_status(args, "pdf", "검색 가능한 PDF를 완성했습니다.", 1.0)
    print(f"output={args.output_pdf.resolve()}")
    print(f"pages={len(images)}")
    print(f"hangul_chars={hangul}")
    print(f"latin_chars={latin}")


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    args.output_pdf = args.output_pdf.resolve()
    images = resolve_images(input_dir)

    with tempfile.TemporaryDirectory(prefix="surya-korean-ocr-") as temporary:
        temporary_path = Path(temporary)
        if args.results_json:
            results_json = args.results_json.resolve()
        else:
            results_root = args.results_dir.resolve() if args.results_dir else temporary_path / "surya-results"
            results_root.mkdir(parents=True, exist_ok=True)
            results_json = run_surya(args, input_dir, results_root)
        build_pdf(args, images, results_json, temporary_path)


if __name__ == "__main__":
    main()
