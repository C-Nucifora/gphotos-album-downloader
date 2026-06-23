"""Post-download fidelity check.

Research finding (the most dangerous failure mode): if you download too fast,
Google silently hands you a resized ~1600px copy with EXIF stripped instead of
the original, and the download still "succeeds". We can't always tell an
original from a preview, but a file that is both small on its long edge *and*
carries no EXIF is a strong signal of the resize trap. We flag those as
``suspect`` so the user can re-run them with a longer dwell rather than
silently archiving thumbnails.

``classify_fidelity`` is pure and unit-tested. ``read_image_meta`` lazily
imports Pillow; if Pillow (or a codec like HEIF) is unavailable it returns
unknowns, and classification then defaults to OK so we never false-flag.
"""

from __future__ import annotations

from .state import STATUS_OK, STATUS_SUSPECT

# Google's album previews render at roughly this long-edge size.
DEFAULT_SUSPECT_MAX_EDGE = 1600


def classify_fidelity(
    width: int | None,
    height: int | None,
    has_exif: bool | None,
    *,
    max_edge: int = DEFAULT_SUSPECT_MAX_EDGE,
) -> str:
    """Return ``ok`` or ``suspect`` for a downloaded image.

    Suspect only when we are confident: both dimensions are known and the long
    edge is <= ``max_edge`` AND EXIF is known-absent. Unknown dimensions or
    unknown EXIF never produce a false suspect.
    """
    if width is None or height is None:
        return STATUS_OK
    long_edge = max(width, height)
    if long_edge <= max_edge and has_exif is False:
        return STATUS_SUSPECT
    return STATUS_OK


def read_image_meta(path: str) -> tuple[int | None, int | None, bool | None]:
    """Return ``(width, height, has_exif)`` for an image file.

    Any value may be ``None`` when it cannot be determined (non-image file,
    unsupported codec, or Pillow not installed).
    """
    try:
        from PIL import Image  # lazy: keeps the package importable without Pillow
    except Exception:
        return (None, None, None)

    try:
        with Image.open(path) as img:
            width, height = img.size
            has_exif: bool | None
            try:
                exif = img.getexif()
                has_exif = bool(exif and len(exif) > 0)
            except Exception:
                has_exif = None
            return (width, height, has_exif)
    except Exception:
        return (None, None, None)
