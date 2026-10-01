app_name = "file_compressor"
app_title = "File Compressor"
app_publisher = "Azarudeen21"
app_description = "Automatic attachment compression for ERPNext/Frappe v16"
app_email = "admin@example.com"
app_license = "MIT"

# Frappe v16 calls the write_file hook at the final filesystem-write stage.
# Compressing here guarantees the bytes written to storage are the optimized bytes.
write_file = "file_compressor.storage.write_file"
