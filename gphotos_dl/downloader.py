"""Download the currently-open item (photo or video), with the research
mitigations and the reliability fixes learned from a real 655-item run.

Key behaviours:
  * Pause+mute any playing video and blur the focused element before pressing
    Shift+D, so a focused/playing player can't swallow the keystroke.
  * Wait only a short *event* timeout for the download to START (a real one
    starts in ~1-2s); the file transfer itself (save_as) then runs as long as
    needed for large videos. This makes a misfired Shift+D fail in seconds
    instead of minutes.
  * Fallback to the toolbar / "More options -> Download" control on later
    attempts, with role/text/case-insensitive selectors.
  * On final failure, capture the live DOM (item aria-label, whether a <video>
    is mounted, and the visible control labels) into the record note and an
    optional debug file, so selectors can be fixed against reality.

Failures are recorded (not fatal); a later run resumes them with --retry-failed.
"""

from __future__ import annotations

import json
import os
import random
import re
import time

from .state import STATUS_FAILED, STATUS_OK, Record
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


_DOWNLOAD_TEXT = re.compile(r"download", re.IGNORECASE)
_MORE_TEXT = re.compile(r"more options", re.IGNORECASE)

_BACKOFF_BASE_S = 1.5
_BACKOFF_CAP_S = 20.0

# Capture the lightbox state at a failure so we can fix selectors from reality.
_FAILURE_PROBE_JS = """() => {
  const item = document.querySelector(
    '[aria-label^="Video - "], [aria-label^="Photo - "]');
  const labels = Array.from(
      document.querySelectorAll('button, [role="button"], [role="menuitem"]'))
    .map(b => b.getAttribute('aria-label') || b.getAttribute('title')
              || (b.textContent || '').trim())
    .filter(s => s && s.length > 0 && s.length < 40);
  return {
    item_label: item ? item.getAttribute('aria-label') : null,
    has_video: !!document.querySelector('video'),
    controls: Array.from(new Set(labels)).slice(0, 40),
  };
}"""


def _default_ext(media_type: str | None) -> str:
    return ".mp4" if media_type == "video" else ".jpg"


def prepare_for_download(page) -> None:
    """Blur the focused element (incl. a video player) and pause+mute videos so
    Shift+D reliably reaches Google Photos' global download handler."""
    try:
        page.evaluate(
            "() => {"
            " const a = document.activeElement;"
            " if (a && ['INPUT','TEXTAREA','VIDEO'].includes(a.tagName)) a.blur();"
            " document.querySelectorAll('video').forEach(v => {"
            "   try { v.muted = true; v.pause(); } catch (e) {} });"
            " }"
        )
    except Exception:
        pass


def _trigger_shiftd(page) -> None:
    page.keyboard.press("Shift+D")


def _click_if_visible(getter) -> bool:
    try:
        loc = getter().first
        if loc.count() and loc.is_visible():
            loc.click(timeout=2_000)
            return True
    except Exception:
        pass
    return False


def _trigger_menu(page) -> bool:
    """Best-effort: trigger a download via a toolbar button or the More-options
    menu. Returns True if a plausible control was clicked."""
    # 1) A direct Download control (toolbar icon or button).
    for getter in (
        lambda: page.get_by_role("button", name=_DOWNLOAD_TEXT),
        lambda: page.locator('[aria-label*="Download" i]'),
        lambda: page.locator('[title*="Download" i]'),
    ):
        if _click_if_visible(getter):
            return True

    # 2) Open the More-options (three-dot) menu.
    opened = False
    for getter in (
        lambda: page.get_by_role("button", name=_MORE_TEXT),
        lambda: page.locator('[aria-label*="More options" i]'),
        lambda: page.locator('[aria-label*="More" i][role="button"]'),
    ):
        if _click_if_visible(getter):
            opened = True
            break
    if not opened:
        return False
    page.wait_for_timeout(250)  # let the menu render

    # 3) Click the Download menu item (auto-waits for it to appear).
    for getter in (
        lambda: page.get_by_role("menuitem", name=_DOWNLOAD_TEXT),
        lambda: page.locator('[role="menuitem"]:has-text("Download")'),
        lambda: page.locator('[role="menuitem"]:has-text("download")'),
    ):
        try:
            getter().first.click(timeout=2_000)
            return True
        except Exception:
            continue
    return False


def _backoff(attempt: int) -> None:
    delay = min(_BACKOFF_BASE_S * (2 ** (attempt - 1)), _BACKOFF_CAP_S)
    time.sleep(delay + random.uniform(0, 0.5))


def _attempt_download(page, *, event_timeout_ms: int, use_menu: bool):
    with page.expect_download(timeout=event_timeout_ms) as dl_info:
        if use_menu:
            if not _trigger_menu(page):
                raise PWError("no download control found in menu")
        else:
            _trigger_shiftd(page)  # fire-and-forget; timeout decides success
    return dl_info.value


def _capture_failure_context(page) -> dict:
    try:
        return page.evaluate(_FAILURE_PROBE_JS)
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc)}


def _write_debug(debug_dir: str, photo_id: str, payload: dict) -> None:
    try:
        os.makedirs(debug_dir, exist_ok=True)
        safe = photo_id.replace("/", "_")[:80]
        with open(os.path.join(debug_dir, f"{safe}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def download_current(
    page,
    *,
    out_dir: str,
    manifest,
    dwell_s: float,
    event_timeout_ms: int,
    max_retries: int,
    suspect_max_edge: int,
    media_type: str = "photo",
    prefix: str = "",
    cleanup: bool = False,
    sequential: bool = False,
    debug_dir: str | None = None,
    photo_id: str | None = None,
) -> Record:
    """Download the open item and return a manifest Record (not yet appended).

    ``photo_id`` may be supplied to key the record on a different id than the
    current page's URL — used by save-to-library mode, where the file is fetched
    from the library copy but must be recorded under the shared-album id so
    resume works.
    """
    url = page.url
    photo_id = photo_id or photo_id_from_url(url) or url

    prepare_for_download(page)
    if dwell_s > 0:
        time.sleep(dwell_s)

    note: str | None = None
    attempts = 0
    started = time.monotonic()
    for attempt in range(1, max_retries + 1):
        attempts = attempt
        try:
            download = _attempt_download(
                page, event_timeout_ms=event_timeout_ms, use_menu=(attempt > 1)
            )
            failure = download.failure()
            if failure:
                note = f"download reported failure: {failure}"
                _backoff(attempt)
                continue

            suggested = download.suggested_filename or f"{photo_id}{_default_ext(media_type)}"
            filename = manifest.reserve(
                suggested,
                photo_id=photo_id,
                prefix=prefix,
                cleanup=cleanup,
                sequential=sequential,
                default_ext=_default_ext(media_type),
            )
            dest = os.path.join(out_dir, filename)
            download.save_as(dest)  # waits for the full transfer to complete
        except PWTimeout:
            note = "timed out waiting for the download to start"
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

        seconds = round(time.monotonic() - started, 2)
        # EXIF/dimension fidelity check only applies to still images.
        if media_type == "photo":
            width, height, has_exif = read_image_meta(dest)
            status = classify_fidelity(width, height, has_exif, max_edge=suspect_max_edge)
        else:
            width = height = has_exif = None
            status = STATUS_OK
        size = os.path.getsize(dest) if os.path.exists(dest) else None
        return Record(
            photo_id=photo_id,
            status=status,
            filename=filename,
            url=url,
            media_type=media_type,
            bytes=size,
            width=width,
            height=height,
            has_exif=has_exif,
            attempts=attempt,
            seconds=seconds,
        )

    # All attempts failed: capture the DOM so we can fix selectors from reality.
    context = _capture_failure_context(page)
    if debug_dir:
        _write_debug(debug_dir, photo_id, {"url": url, "note": note, **context})
    note = f"{note}; dom={json.dumps(context, ensure_ascii=False)[:600]}"
    return Record(
        photo_id=photo_id,
        status=STATUS_FAILED,
        url=url,
        media_type=media_type,
        attempts=attempts,
        seconds=round(time.monotonic() - started, 2),
        note=note,
    )
