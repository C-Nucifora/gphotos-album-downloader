"""Experimental API backend: drive Google Photos' internal web API via
xob0t/google_photos_web_client (gpwc) instead of the browser UI.

Far more robust than the Playwright path — no selectors, lightbox walking,
autoplay timing, or DOM video-detection. The pipeline becomes API calls:

  parse share URL -> (album_media_key, auth_key)   [album key = /share/<token>,
                                                     auth key = ?key=]
  GetAlbumPage(album_media_key, auth_key)           enumerate every item, with
                                                    media type (video_duration)
                                                    and is_owned, paginated
  SaveSharedMediaToLibrary(...)                     batch-save shared photos
  GetDownloadToken -> CheckDownloadToken -> GET     download the true original
  MoveToTrash(...)                                  batch cleanup

Auth is a cookies.txt exported from a logged-in session (no browser at runtime).

Import-safe without gpwc installed: pure helpers work; build_client() raises a
clear install message if the dependency is missing.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_SHARE_RE = re.compile(r"/share/([^/?#]+)")


def parse_share_url(url: str) -> tuple[str | None, str | None]:
    """Return ``(album_media_key, auth_key)`` from a Google Photos share URL.

    The album media key is the ``/share/<token>`` segment; the auth key is the
    ``?key=`` query parameter. Either may be None if absent.
    """
    match = _SHARE_RE.search(url or "")
    album_media_key = match.group(1) if match else None
    auth_key = (parse_qs(urlsplit(url or "").query).get("key") or [None])[0]
    return album_media_key, auth_key


def item_kind(item) -> str:
    """'video' if the album/library item carries a video duration, else 'photo'.

    (Motion photos have ``live_photo_duration`` but no ``video_duration``, so
    they are correctly counted as photos.)
    """
    return "video" if getattr(item, "video_duration", None) else "photo"


def build_client(cookies_path: str, account_index: int = 0):
    """Build a gpwc Client from a cookies.txt, or raise a clear install error."""
    try:
        from gpwc import Client
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "The --api backend needs google_photos_web_client. Install it with:\n"
            "  pip install 'git+https://github.com/xob0t/google_photos_web_client'"
        ) from exc
    return Client(cookies_path, account_index=account_index)


def enumerate_album(client, album_media_key: str, auth_key: str | None, *, limit: int = 0) -> list:
    """Return all items in a shared album via paginated GetAlbumPage."""
    from gpwc import payloads

    items: list = []
    page_id = None
    while True:
        resp = payloads.GetAlbumPage(album_media_key, page_id, auth_key).execute(client)
        items.extend(getattr(resp.data, "items", None) or [])
        if limit and len(items) >= limit:
            return items[:limit]
        page_id = getattr(resp.data, "next_page_id", None)
        if not page_id:
            return items
