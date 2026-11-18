import warnings
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
CONTENT_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def read_image(file, field="photo"):
    """Return the raw bytes and a trusted extension for a verified JPG, PNG, or WebP upload."""
    if file.size > MAX_IMAGE_BYTES or file.size == 0:
        raise ValidationError({field: "Choose a photo under 5 MB."})
    raw = file.read(MAX_IMAGE_BYTES + 1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as img:
                fmt = img.format
                img.verify()
        return raw, IMAGE_TYPES[fmt]
    except (
        OSError,
        ValueError,
        KeyError,
        UnidentifiedImageError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValidationError({field: "Use a JPG, PNG, or WebP photo."}) from exc
