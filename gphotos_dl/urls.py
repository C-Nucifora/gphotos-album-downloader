"""Pure URL helpers for the Google Photos lightbox.

The lightbox shows one item per full-page URL. Observed patterns
(confirmed against perkeep/gphotos-cdp and vikas5914/google-photos-backup):

    https://photos.google.com/photo/<PHOTO_ID>
    https://photos.google.com/u/0/photo/<PHOTO_ID>
    https://photos.google.com/album/<ALBUM_ID>/photo/<PHOTO_ID>
    https://photos.google.com/share/<TOKEN>/photo/<PHOTO_ID>?key=...

The per-photo id is the opaque key after the final ``/photo/`` segment. We
normalise away the optional ``/u/<n>/`` account segment so the same photo
under different account indices compares equal.

No third-party imports here on purpose: this module must import without
Playwright or Pillow so the logic stays unit-testable in a bare interpreter.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

# Matches the /u/<digit>/ account segment that Google sometimes injects.
_ACCOUNT_SEGMENT = re.compile(r"/u/\d+/")

# Captures the opaque id after the final /photo/ segment.
_PHOTO_ID = re.compile(r"/photo/([^/?#]+)")


def strip_account_segment(url: str) -> str:
    """Remove the ``/u/<n>/`` account segment from a Google Photos URL."""
    return _ACCOUNT_SEGMENT.sub("/", url)


def clean_url(url: str) -> str:
    """Normalise a lightbox URL for stable comparison.

    Drops the account segment and any query/fragment, leaving scheme + host +
    path. Two URLs that point at the same photo compare equal after cleaning.
    """
    if not url:
        return ""
    no_account = strip_account_segment(url)
    parts = urlsplit(no_account)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def photo_id_from_url(url: str) -> str | None:
    """Return the opaque photo id from a lightbox URL, or ``None``.

    ``None`` means the URL is not a single-photo lightbox URL (e.g. the album
    grid, the sign-in page, or an empty string).
    """
    if not url:
        return None
    match = _PHOTO_ID.search(strip_account_segment(url))
    if not match:
        return None
    photo_id = match.group(1).strip()
    return photo_id or None


def is_lightbox_url(url: str) -> bool:
    """True if the URL is a single-photo lightbox URL."""
    return photo_id_from_url(url) is not None
