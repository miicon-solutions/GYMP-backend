from django.core.files.uploadhandler import FileUploadHandler
from rest_framework.exceptions import APIException


class PayloadTooLarge(APIException):
    status_code = 413
    default_detail = "Choose a photo under 5 MB."


class BoundedUploadHandler(FileUploadHandler):
    """Abort before memory/temporary handlers store an oversized file or upload batch."""

    def __init__(self, request=None):
        super().__init__(request)
        self.total = 0
        self.file_bytes = 0

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_bytes = 0

    def receive_data_chunk(self, raw_data, start):
        self.total += len(raw_data)
        self.file_bytes += len(raw_data)
        if self.total > 6 * 1024 * 1024 or self.file_bytes > 5 * 1024 * 1024:
            raise PayloadTooLarge()
        return raw_data

    def file_complete(self, file_size):
        return None
