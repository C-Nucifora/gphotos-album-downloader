"""Save-to-library workflow: get the true original (e.g. 24MB Sony .ARW) for a
shared photo that the normal shared download only serves as a recompressed JPEG.

Mechanism (verified against the live UI): clicking "Save" on a shared photo
copies it into your own library as a NEW item with a NEW photo id. Downloading
*that* library copy yields the original. So per photo we:

  1. click Save on the shared-album page and capture the new library id from the
     internal `batchexecute` response,
  2. open ``photos.google.com/photo/<new id>`` on a second page (your library)
     and download it there (full original).

This module is the non-destructive core. Removing the saved copies and emptying
Trash to reclaim storage is handled separately (and is opt-in/loud, since
emptying Trash is global and destructive).
"""

from __future__ import annotations

import re

from .urls import is_lightbox_url, photo_id_from_url

_ID_RE = re.compile(r"AF1Qip[\w-]{20,}")

LIBRARY_PHOTO_URL = "https://photos.google.com/photo/{}"

# "Save" control in the shared lightbox (user-reported: text "Save", top-right).
_SAVE_GETTERS = [
    lambda page: page.get_by_role("button", name=re.compile(r"^\s*save\s*$", re.I)),
    lambda page: page.get_by_text(re.compile(r"^\s*save\s*$", re.I)),
    lambda page: page.locator('[aria-label*="save" i]'),
]


def click_save(page, *, timeout_ms: int = 6_000) -> bool:
    """Click the Save-to-library control; return whether something was clicked.

    Polls for up to ``timeout_ms`` because the lightbox toolbar isn't rendered
    immediately after opening/navigating (this is why the very first item used to
    fail with 'Save control not found' even though the control was present).
    """
    for _ in range(max(1, timeout_ms // 300)):
        for getter in _SAVE_GETTERS:
            try:
                loc = getter(page).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=3_000)
                    return True
            except Exception:
                continue
        page.wait_for_timeout(300)
    return False


def save_and_get_library_id(share_page, *, timeout_ms: int = 10_000):
    """Click Save on the open shared photo and return ``(library_id, clicked)``.

    ``library_id`` is the new library photo id parsed from the save's
    `batchexecute` response, or None. ``clicked`` is whether a Save control was
    actually found and clicked — if False, the most likely cause is not being
    signed in (the Save control is absent when logged out).
    """
    shared_id = photo_id_from_url(share_page.url)
    new_ids: list[str] = []

    def on_response(resp):
        try:
            if "batchexecute" in resp.url:
                for found in dict.fromkeys(_ID_RE.findall(resp.text())):
                    if found != shared_id and found not in new_ids:
                        new_ids.append(found)
        except Exception:
            pass

    share_page.on("response", on_response)
    try:
        clicked = click_save(share_page)
        if not clicked:
            return (None, False)
        for _ in range(max(1, timeout_ms // 200)):
            if new_ids:
                break
            share_page.wait_for_timeout(200)
    finally:
        try:
            share_page.remove_listener("response", on_response)
        except Exception:
            pass

    return (new_ids[0] if new_ids else None, True)


EMPTY_TRASH_URL = "https://photos.google.com/trash"

# Delete control in the OWNED library lightbox (move the saved copy to Trash).
_DELETE_GETTERS = [
    lambda p: p.get_by_role("button", name=re.compile(r"move to trash|delete", re.I)),
    lambda p: p.locator('[aria-label*="Move to trash" i]'),
    lambda p: p.locator('[aria-label="Delete" i]'),
]
_CONFIRM_GETTERS = [
    lambda p: p.get_by_role("button", name=re.compile(r"move to trash|delete", re.I)),
]
# Empty-trash control. We ONLY ever click a control whose label clearly says so
# — never a generic button — because emptying Trash is global and irreversible.
_EMPTY_TRASH_GETTERS = [
    lambda p: p.get_by_role("button", name=re.compile(r"empty trash|empty bin|delete all", re.I)),
    lambda p: p.locator('[aria-label*="Empty trash" i]'),
    lambda p: p.locator('[aria-label*="Empty bin" i]'),
]
_CONFIRM_EMPTY_GETTERS = [
    lambda p: p.get_by_role("button", name=re.compile(r"empty trash|empty bin|delete all|delete", re.I)),
]


def _click_first_visible(page, getters, *, timeout_ms: int = 4_000) -> bool:
    for _ in range(max(1, timeout_ms // 300)):
        for getter in getters:
            try:
                loc = getter(page).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=2_500)
                    return True
            except Exception:
                continue
        page.wait_for_timeout(300)
    return False


def delete_open_library_item(lib_page) -> bool:
    """Move the currently-open OWNED library item to Trash. Best-effort.

    Only ever operates on the library page (an item you own); it never touches
    the shared album. Failing to delete just leaves the copy in your library
    (storage not reclaimed) — it is never destructive to the shared album.
    """
    clicked = _click_first_visible(lib_page, _DELETE_GETTERS, timeout_ms=3_000)
    if not clicked:
        try:
            lib_page.keyboard.press("#")  # documented Google Photos 'delete' shortcut
        except Exception:
            return False
    lib_page.wait_for_timeout(700)
    _click_first_visible(lib_page, _CONFIRM_GETTERS, timeout_ms=2_000)  # confirm if asked
    lib_page.wait_for_timeout(700)
    return True


def empty_trash(lib_page, *, controls_sink=None) -> bool:
    """Navigate to Trash and empty it. Returns whether an Empty-trash control was
    clicked.

    SAFETY: only clicks a control whose accessible name explicitly matches
    'empty trash' / 'empty bin' / 'delete all'. If no such control is found, it
    clicks NOTHING and returns False (and reports the visible controls via
    ``controls_sink`` so the selector can be fixed) — it will never click a
    generic/unknown control.
    """
    try:
        lib_page.goto(EMPTY_TRASH_URL, wait_until="domcontentloaded")
        lib_page.wait_for_timeout(1_500)
    except Exception:
        return False

    if not _click_first_visible(lib_page, _EMPTY_TRASH_GETTERS, timeout_ms=4_000):
        if controls_sink is not None:
            try:
                controls_sink(lib_page.evaluate(
                    "() => Array.from(document.querySelectorAll('button,[role=\"button\"]'))"
                    ".map(b => b.getAttribute('aria-label') || (b.textContent || '').trim())"
                    ".filter(s => s && s.length < 40)"
                    ".filter((v, i, a) => a.indexOf(v) === i).slice(0, 40)"))
            except Exception:
                pass
        return False

    lib_page.wait_for_timeout(800)
    _click_first_visible(lib_page, _CONFIRM_EMPTY_GETTERS, timeout_ms=3_000)  # confirm dialog
    lib_page.wait_for_timeout(1_500)
    return True


def open_library_item(lib_page, library_id: str, *, timeout_ms: int = 15_000) -> bool:
    """Open the saved copy in the library page. Returns True if it landed on a
    single-photo lightbox view we can download from."""
    try:
        lib_page.goto(LIBRARY_PHOTO_URL.format(library_id), wait_until="domcontentloaded")
        lib_page.wait_for_timeout(1_200)
    except Exception:
        return False
    return is_lightbox_url(lib_page.url) and photo_id_from_url(lib_page.url) is not None
