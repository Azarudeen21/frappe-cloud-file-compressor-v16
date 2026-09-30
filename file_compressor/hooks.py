app_name = "file_compressor"
app_title = "File Compressor"
app_publisher = "Azarudeen21"
app_description = "Automatic attachment compression for ERPNext/Frappe v16"
app_email = "admin@example.com"
app_license = "MIT"

# Primary upload hook used by Frappe v16 upload_file().
after_file_upload = [
    "file_compressor.compression.compress_uploaded_file"
]

# Safety-net hook: run before validation for File inserts as well.
# This covers File records created through code paths other than upload_file().
doc_events = {
    "File": {
        "before_validate": "file_compressor.compression.compress_file_doc_event"
    }
}
