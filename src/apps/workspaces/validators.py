"""
Upload validators for user-supplied files. Split out from models.py so
the same functions can be unit-tested and reused (e.g. from forms) without
importing the whole models module.

Context: Workspace.logo is a plain ImageField with no size/dimension cap.
Django's ImageField already rejects anything Pillow can't parse as an
image (so a .exe renamed to .png is refused), and Pillow itself refuses
to decode a decompression-bomb-sized image by default (Image.MAX_IMAGE_PIXELS,
~89 million pixels) — but neither of those stops someone from uploading a
huge *file* (e.g. a legitimately-encoded but enormous PNG/TIFF) that's
still well under the pixel-count ceiling. That's a real resource-abuse
vector for a field that's writable by any workspace owner and gets read
back on every public report/proposal share page, so it gets an explicit
cap here.
"""

from django.core.exceptions import ValidationError

MAX_LOGO_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB — generous for a logo, small enough to matter


def validate_logo_file_size(file):
    if file.size > MAX_LOGO_UPLOAD_BYTES:
        raise ValidationError(
            f"That image is too large ({file.size / (1024 * 1024):.1f} MB) — "
            f"logos are limited to {MAX_LOGO_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
