from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import frappe
from PIL import Image, ImageOps

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VALID_PDF_PRESETS = {"/screen", "/ebook", "/printer", "/prepress"}


def _cfg(key: str, default):
    value = frappe.conf.get(key)
    return default if value is None else value


def _enabled() -> bool:
    return int(_cfg("attachment_compression_enabled", 1)) == 1


def _compress_above_bytes() -> int:
    try:
        mb = float(_cfg("attachment_compress_above_mb", 1))
    except (TypeError, ValueError):
        mb = 1.0
    return max(0, int(mb * 1024 * 1024))


def compress_file_doc_event(doc, method=None):
    """Fallback File DocType hook for upload paths that bypass after_file_upload."""
    if getattr(doc.flags, "file_compressor_checked", False):
        return doc
    return compress_uploaded_file(doc)


def compress_uploaded_file(doc):
    """Compress supported uploads before Frappe saves the File document."""
    if getattr(doc.flags, "file_compressor_checked", False):
        return doc

    doc.flags.file_compressor_checked = True

    if not _enabled():
        return doc

    content = getattr(doc, "content", None)
    file_name = (getattr(doc, "file_name", None) or "").strip()

    if not content or not file_name:
        return doc

    if isinstance(content, str):
        content = content.encode()

    original_size = len(content)
    if original_size < _compress_above_bytes():
        return doc

    extension = Path(file_name).suffix.lower()
    if extension not in SUPPORTED_IMAGE_EXTENSIONS and extension != ".pdf":
        return doc

    try:
        if extension in SUPPORTED_IMAGE_EXTENSIONS:
            compressed = _compress_image(content, extension)
        else:
            compressed = _compress_pdf(content)

        if compressed and len(compressed) < original_size:
            compressed_size = len(compressed)

            doc.content = compressed
            doc._content = compressed
            doc.file_size = compressed_size

            if getattr(frappe, "form_dict", None) is not None:
                frappe.form_dict.file_size = compressed_size

            doc.flags.file_compressor_applied = True
            doc.flags.file_compressor_original_size = original_size
            doc.flags.file_compressor_final_size = compressed_size

    except Exception:
        frappe.log_error(
            title="Attachment Compression Failed",
            message=frappe.get_traceback(),
        )

    return doc


def _compress_image(content: bytes, extension: str) -> bytes:
    quality = int(_cfg("attachment_image_quality", 75))
    quality = min(95, max(20, quality))
    max_width = int(_cfg("attachment_max_width", 1920))
    max_height = int(_cfg("attachment_max_height", 1920))

    with Image.open(io.BytesIO(content)) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        output = io.BytesIO()

        if extension in {".jpg", ".jpeg"}:
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
        else:
            image.save(
                output,
                format="PNG",
                optimize=True,
                compress_level=9,
            )

        result = output.getvalue()
        return result if result and len(result) < len(content) else content


def _compress_pdf(content: bytes) -> bytes:
    """Compress PDF using Ghostscript when available, otherwise PyMuPDF."""
    gs = shutil.which("gs")

    if gs:
        try:
            result = _compress_pdf_ghostscript(content, gs)
            if result and len(result) < len(content):
                return result
        except Exception:
            frappe.log_error(
                title="Ghostscript PDF Compression Failed",
                message=frappe.get_traceback(),
            )

    # Frappe Cloud fallback: no OS package required.
    return _compress_pdf_pymupdf(content)


def _compress_pdf_ghostscript(content: bytes, gs: str) -> bytes:
    preset = str(_cfg("attachment_pdf_quality", "/ebook"))
    if preset not in VALID_PDF_PRESETS:
        preset = "/ebook"

    in_path = None
    out_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as src:
            src.write(content)
            in_path = src.name

        fd, out_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        command = [
            gs,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={preset}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            "-dSAFER",
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
            "-dColorImageDownsampleType=/Bicubic",
            "-dColorImageResolution=150",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dGrayImageResolution=150",
            "-dMonoImageDownsampleType=/Subsample",
            "-dMonoImageResolution=300",
            f"-sOutputFile={out_path}",
            in_path,
        ]

        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )

        with open(out_path, "rb") as handle:
            result = handle.read()

        return result if result and len(result) < len(content) else content

    finally:
        for path in (in_path, out_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def _compress_pdf_pymupdf(content: bytes) -> bytes:
    """Pure-Python Frappe Cloud fallback.

    First performs structural PDF optimization. If that does not materially
    reduce the file and aggressive mode is enabled, it rebuilds pages as
    compressed JPEG page images at configurable DPI.
    """
    import fitz

    # Pass 1: lossless / structural optimization.
    source = fitz.open(stream=content, filetype="pdf")
    try:
        optimized = io.BytesIO()
        source.save(
            optimized,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )
        optimized_bytes = optimized.getvalue()
    finally:
        source.close()

    if optimized_bytes and len(optimized_bytes) < len(content) * 0.90:
        return optimized_bytes

    aggressive = int(_cfg("attachment_pdf_aggressive_fallback", 1)) == 1
    if not aggressive:
        return optimized_bytes if len(optimized_bytes) < len(content) else content

    dpi = int(_cfg("attachment_pdf_raster_dpi", 140))
    dpi = max(72, min(220, dpi))
    jpeg_quality = int(_cfg("attachment_pdf_jpeg_quality", 68))
    jpeg_quality = max(30, min(90, jpeg_quality))

    source = fitz.open(stream=content, filetype="pdf")
    output = fitz.open()

    try:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)

        for page in source:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            jpg = pix.tobytes("jpeg", jpg_quality=jpeg_quality)

            rect = page.rect
            new_page = output.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(rect, stream=jpg)

        rebuilt = output.tobytes(
            garbage=4,
            deflate=True,
            deflate_images=True,
            clean=True,
        )
    finally:
        output.close()
        source.close()

    candidates = [content]
    if optimized_bytes:
        candidates.append(optimized_bytes)
    if rebuilt:
        candidates.append(rebuilt)

    return min(candidates, key=len)
