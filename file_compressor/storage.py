from __future__ import annotations

import os

import frappe
from frappe.utils import get_files_path
from frappe.utils.file_manager import get_safe_file_name

from file_compressor.compression import (
    SUPPORTED_IMAGE_EXTENSIONS,
    _compress_above_bytes,
    _compress_image,
    _compress_pdf,
    _enabled,
)


def write_file(file_doc):
    """Frappe write_file hook.

    This runs at the final write-to-storage stage in File.save_file().
    It compresses the actual bytes that are about to be written, then
    updates File metadata so the UI shows the compressed size.
    """

    content = getattr(file_doc, "_content", None)
    if not content:
        return file_doc.save_file_on_filesystem()

    if isinstance(content, str):
        content = content.encode()

    original_size = len(content)
    file_name = file_doc.file_name or ""
    extension = os.path.splitext(file_name)[1].lower()

    final_content = content

    if (
        _enabled()
        and original_size >= _compress_above_bytes()
        and (extension in SUPPORTED_IMAGE_EXTENSIONS or extension == ".pdf")
    ):
        try:
            if extension in SUPPORTED_IMAGE_EXTENSIONS:
                candidate = _compress_image(content, extension)
            else:
                candidate = _compress_pdf(content)

            if candidate and len(candidate) < original_size:
                final_content = candidate

        except Exception:
            frappe.log_error(
                title="Attachment Compression Failed At Write Stage",
                message=frappe.get_traceback(),
            )

    final_size = len(final_content)

    # Replace the exact bytes that Frappe will write.
    file_doc._content = final_content
    file_doc.content = final_content
    file_doc.file_size = final_size

    # Recalculate the hash because File.save_file() calculated it before
    # this custom write hook was called.
    try:
        from frappe.core.doctype.file.utils import get_content_hash
    except ImportError:
        from frappe.utils.file_manager import get_content_hash

    file_doc.content_hash = get_content_hash(final_content)

    # Frappe v16 validate() may otherwise restore the browser's original size.
    if getattr(frappe, "form_dict", None) is not None:
        frappe.form_dict.file_size = final_size

    safe_file_name = get_safe_file_name(file_doc.file_name)

    if file_doc.is_private:
        file_doc.file_url = f"/private/files/{safe_file_name}"
        file_path = get_files_path(safe_file_name, is_private=True)
    else:
        file_doc.file_url = f"/files/{safe_file_name}"
        file_path = get_files_path(safe_file_name, is_private=False)

    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "wb+") as handle:
        handle.write(final_content)
        handle.flush()
        os.fsync(handle.fileno())

    file_doc.flags.file_compressor_original_size = original_size
    file_doc.flags.file_compressor_final_size = final_size
    file_doc.flags.file_compressor_applied = final_size < original_size

    return {
        "file_name": os.path.basename(file_path),
        "file_url": file_doc.file_url,
    }
