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
    """Compress supported uploads before Frappe saves the File document.

    Important for Frappe v16:
    handler.upload_file() passes the original upload size in frappe.form_dict.
    File.validate() can later copy that value into File.file_size, so after
    compression we must update both the document and form_dict metadata.
    """
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

            # Replace the bytes Frappe will save.
            doc.content = compressed
            doc._content = compressed

            # Keep File metadata correct.
            doc.file_size = compressed_size

            # Frappe v16 File.validate() reads frappe.form_dict.file_size,
            # which normally still contains the ORIGINAL browser upload size.
            # Update it so the stored File record reflects the compressed file.
            if getattr(frappe, "form_dict", None) is not None:
                frappe.form_dict.file_size = compressed_size

            # Helpful request-local flags for debugging/support.
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
    gs = shutil.which("gs")
    if not gs:
        frappe.log_error(
            title="PDF Compression Skipped",
            message="Ghostscript executable 'gs' was not found in the running container.",
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
