"""Download the currently-open photo, with every research mitigation applied.

Primary path: focus the lightbox, dwell briefly (so Google serves the original
rather than a resized preview), then press Shift+D *inside* an
``expect_download`` block and ``save_as`` immediately (files are deleted when
the context closes). Navigation is the caller's job and happens only after this
returns, so an in-flight download is never cancelled by an ArrowRight.

Fallback path (later attempts): the toolbar / "More options -> Download" menu,
for the cases where the keyboard shortcut produced no download event.

Failures are retried with exponential backoff and, if still unresolved, recorded
as ``failed`` so the run continues and a later run can retry them.
"""

from __future__ import annotations

import os
import random
import re
import time

from .state import STATUS_FAILED, Record
from .urls import photo_id_from_url
from .verify import classify_fidelity, read_image_meta

try:  # keep the module importable without Playwright (for unit tests)
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout
except Exception:  # pragma: no cover
    class PWError(Exception):
        pass

    class PWTimeout(Exception):
        pass


_DOWNLOAD_BUTTON_SELECTORS = [
    '[aria-label="Download - Shift+D"]',
    '[aria-label^="Download" i]',
]
_MORE_OPTIONS_SELECTORS = [
    '[aria-label="More options"]',
    '[aria-label*="More options" i]',
]
# CSS fallbacks. Primary match uses get_by_role (case-insensitive) below; these
# include lower-case variants because ``:has-text`` is case-sensitive.
_DOWNLOAD_MENUITEM_SELECTORS = [
    '[role="menuitem"]:has-text("Download")',
    '[role="menuitem"]:has-text("download")',
    'li:has-text("Download")',
    'li:has-text("download")',
]
_DOWNLOAD_TEXT = re.compile(r"download", re.IGNORECASE)

_BACKOFF_BASE_S = 1.5
_BACKOFF_CAP_S = 30.0


def ensure_focus(page) -> None:
    """Move focus out of any text input so keyboard shortcuts reach the app."""
    try:
        page.evaluate(
            "() => { const a = document.activeElement;"
            " if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA')) a.blur(); }"
        )
    except Exception:
        pass


def _trigger_shiftd(page) -> None:
    page.keyboard.press("Shift+D")


def _trigger_menu(page) -> bool:
    """Best-effort: trigger a download via the toolbar/menu. Returns True if a
    plausible control was clicked."""
    for selector in _DOWNLOAD_BUTTON_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2_000)
                return True
        except Exception:
            continue

    opened = False
    for selector in _MORE_OPTIONS_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2_000)
                opened = True
                break
        except Exception:
            continue
    if not opened:
        return False

    # Primary: role-based, case-insensitive name match.
    try:
        item = page.get_by_role("menuitem", name=_DOWNLOAD_TEXT).first
        if item.count() and item.is_visible():
            item.click(timeout=2_000)
            return True
    except Exception:
        pass

    for selector in _DOWNLOAD_MENUITEM_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2_000)
                return True
        except Exception:
            continue
    return False


def _backoff(attempt: int) -> None:
    delay = min(_BACKOFF_BASE_S * (2 ** (attempt - 1)), _BACKOFF_CAP_S)
    time.sleep(delay + random.uniform(0, 0.5))


def _attempt_download(page, *, timeout_ms: int, use_menu: bool):
    with page.expect_download(timeout=timeout_ms) as dl_info:
        if use_menu:
            if not _trigger_menu(page):
                raise PWError("no download control found in menu")
        else:
            # Fire-and-forget: success/failure is decided by whether the
            # download event arrives before timeout, handled by the caller.
            _trigger_shiftd(page)
    return dl_info.value


def download_current(
    page,
    *,
    out_dir: str,
    manifest,
    dwell_s: float,
    timeout_ms: int,
    max_retries: int,
    suspect_max_edge: int,
) -> Record:
    """Download the open photo and return a manifest Record (not yet appended)."""
    url = page.url
    photo_id = photo_id_from_url(url) or url

    ensure_focus(page)
    if dwell_s > 0:
        time.sleep(dwell_s)

    note: str | None = None
    attempts = 0
    for attempt in range(1, max_retries + 1):
        attempts = attempt
        try:
            download = _attempt_download(
                page, timeout_ms=timeout_ms, use_menu=(attempt > 1)
            )
            failure = download.failure()
            if failure:
                note = f"download reported failure: {failure}"
                _backoff(attempt)
                continue

            suggested = download.suggested_filename or f"{photo_id}.jpg"
            filename = manifest.reserve_filename(suggested)
            dest = os.path.join(out_dir, filename)
            download.save_as(dest)  # waits for the transfer to complete
        except PWTimeout:
            note = "timed out waiting for the download event"
            _backoff(attempt)
            continue
        except PWError as exc:
            note = f"playwright error: {exc}"
            _backoff(attempt)
            continue
        except Exception as exc:  # pragma: no cover - defensive
            note = f"unexpected error: {exc}"
            _backoff(attempt)
            continue

        width, height, has_exif = read_image_meta(dest)
        size = os.path.getsize(dest) if os.path.exists(dest) else None
        status = classify_fidelity(width, height, has_exif, max_edge=suspect_max_edge)
        return Record(
            photo_id=photo_id,
            status=status,
            filename=filename,
            url=url,
            bytes=size,
            width=width,
            height=height,
            has_exif=has_exif,
            attempts=attempt,
        )

    return Record(
        photo_id=photo_id,
        status=STATUS_FAILED,
        url=url,
        attempts=attempts,
        note=note,
    )
