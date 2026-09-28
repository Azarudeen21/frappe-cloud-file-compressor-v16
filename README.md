# File Compressor for Frappe Cloud / ERPNext v16

Automatically compresses JPG, JPEG, PNG and PDF uploads before Frappe saves the File document.

## Designed for

- Frappe Framework v16
- ERPNext v16
- Frappe Cloud private bench groups

## What it does

- Compresses JPG/JPEG/PNG attachments above the configured threshold.
- Compresses PDFs using Ghostscript.
- Keeps the original upload when compression fails or produces a larger file.
- Uses the normal ERPNext attachment area. Users do not need a separate upload button.
- Does not modify DOCX, XLSX, PPTX, ZIP or other unsupported file types.

## Frappe Cloud deployment

1. In Frappe Cloud, use a Private Bench Group.
2. Open the Bench Group and add this GitHub repository as a custom app.
3. Use branch `main`.
4. Deploy/update the bench.
5. Open the target Site.
6. Install the app named `file_compressor`.

Frappe Cloud reads `pyproject.toml` and installs:

- Python dependency: Pillow
- APT dependency: ghostscript
- Frappe compatibility: v16

## Default behavior

- Compression enabled: yes
- Compress files larger than: 1 MB
- JPEG quality: 75
- Maximum image size: 1920 x 1920
- PDF preset: /ebook

## Optional Site Config

Set these values in Frappe Cloud Site Config if you want to change the defaults:

```json
{
  "attachment_compression_enabled": 1,
  "attachment_compress_above_mb": 1,
  "attachment_image_quality": 75,
  "attachment_max_width": 1920,
  "attachment_max_height": 1920,
  "attachment_pdf_quality": "/ebook"
}
```

Supported PDF presets:

- `/screen` - strongest compression / lowest quality
- `/ebook` - recommended balance
- `/printer` - higher quality
- `/prepress` - highest quality / least compression

## Notes

The app only keeps a compressed result when it is smaller than the original file. If compression fails, the original upload is preserved.

Large original uploads still need to be allowed by your Frappe Cloud/site upload-size configuration before this hook can process them.
