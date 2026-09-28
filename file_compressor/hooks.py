app_name = "file_compressor"
app_title = "File Compressor"
app_publisher = "Azarudeen21"
app_description = "Automatic attachment compression for ERPNext/Frappe v16"
app_email = "admin@example.com"
app_license = "MIT"

# Frappe v16 upload_file() calls this hook before saving the File document.
after_file_upload = [
    "file_compressor.compression.compress_uploaded_file"
]
