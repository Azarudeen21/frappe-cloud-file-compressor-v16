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


def compress_uploaded_file(doc):
    """Compress supported uploads before Frappe saves the File document."""
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

        # Never replace the upload with a larger or empty result.
        if compressed and len(compressed) < original_size:
            doc.content = compressed
            # Keep alternate internal content attribute consistent when present.
            if hasattr(doc, "_content"):
                doc._content = compressed

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
            # Keep alpha/transparency for PNG.
            image.save(
                output,
                format="PNG",
                optimize=True,
                compress_level=9,
            )

        result = output.getvalue()
        return result if result and len(result) < len(content) else content


def _compress_pdf(content: bytes) -> bytes:
    gs = shutil.which("gs")
    if not gs:
        # Image compression can still work even if Ghostscript is absent.
        frappe.log_error(
            title="PDF Compression Skipped",
            message="Ghostscript executable 'gs' was not found.",
        )
        return content

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
