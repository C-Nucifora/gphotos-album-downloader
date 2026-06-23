"""Driving the Google Photos lightbox: open the first photo and walk forward.

Navigation is *hardened* because research showed bare ArrowRight is flaky in an
automated browser: keypresses sometimes don't register, and the URL updates
asynchronously. Each ``goto_next`` therefore: presses ArrowRight, waits (polls)
for the cleaned URL to actually change, retries the keypress, and finally falls
back to clicking the on-screen "next" arrow before concluding the URL is stable.

Selectors are kept ARIA/role-based with fallbacks because Google's CSS class
names are obfuscated and rotate between deploys.
"""

from __future__ import annotations

from .urls import clean_url, is_lightbox_url

# JS that finds the open item's container aria-label ("Photo - ..."/"Video - ...")
# preferring a visible element, and reports whether a <video> is mounted.
_MEDIA_PROBE_JS = """() => {
  const els = document.querySelectorAll(
    '[aria-label^="Video - "], [aria-label^="Photo - "]');
  let label = null;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) { label = el.getAttribute('aria-label'); break; }
  }
  if (!label && els.length) label = els[0].getAttribute('aria-label');
  return { label, hasVideo: !!document.querySelector('video') };
}"""

# Candidate selectors for the first grid tile, most-specific first.
_FIRST_TILE_SELECTORS = [
    'a[href*="./photo/"]',
    'a[href*="/photo/"]',
]

# Candidate selectors for the lightbox "next photo" control.
_NEXT_ARROW_SELECTORS = [
    '[aria-label="View next photo"]',
    '[aria-label*="next" i][role="button"]',
    'button[aria-label*="Next" i]',
]


def open_first_photo(page, *, timeout_ms: int = 30_000) -> bool:
    """Click the first photo in the album grid to enter the lightbox.

    Returns True once the URL is a single-photo lightbox URL. Raises
    RuntimeError if no openable tile is found.
    """
    if is_lightbox_url(page.url):
        return True  # a photo is already open (e.g. --start-open)

    last_err: Exception | None = None
    for selector in _FIRST_TILE_SELECTORS:
        try:
            tile = page.locator(selector).first
            tile.wait_for(state="visible", timeout=5_000)
            tile.click()
            page.wait_for_url(lambda u: is_lightbox_url(u), timeout=timeout_ms)
            return True
        except Exception as exc:  # try the next selector
            last_err = exc
            continue

    raise RuntimeError(
        "Could not open the first photo automatically. Open any photo in the "
        "album manually, then re-run with --start-open."
    ) from last_err


def media_type_from_aria(label: str | None) -> str | None:
    """Map an item aria-label to 'photo'/'video' by its leading token.

    'Video - Portrait - Jul 12, 2023, 3:04:05 PM' -> 'video'. Returns None when
    the label is absent or unrecognised (caller falls back to other signals).
    """
    if not label:
        return None
    head = label.split(" - ", 1)[0].strip().lower()
    if head == "video":
        return "video"
    if head == "photo":
        return "photo"
    return None


def media_type(page) -> str:
    """Return 'photo' or 'video' for the currently-open lightbox item.

    Primary signal is the item-container aria-label's leading token (research-
    confirmed reliable); a mounted <video> element is corroboration. Motion
    photos are labelled 'Photo', so they are correctly counted as photos.
    Defaults to 'photo' when nothing is conclusive.
    """
    try:
        probe = page.evaluate(_MEDIA_PROBE_JS)
    except Exception:
        probe = None
    if probe:
        kind = media_type_from_aria(probe.get("label"))
        if kind:
            return kind
        if probe.get("hasVideo"):
            return "video"
    return "photo"


def pause_videos(page) -> int:
    """Pause and mute every <video> currently in the DOM. Returns how many.

    Google re-arms autoplay on each lightbox item, so this is called after every
    navigation. Pausing/muting is playback-only and never affects downloading.
    """
    try:
        return page.evaluate(
            "() => { const v = document.querySelectorAll('video');"
            " v.forEach(x => { try { x.muted = true; x.pause(); } catch (e) {} });"
            " return v.length; }"
        )
    except Exception:
        return 0


def wait_for_url_change(page, before_clean: str, *, timeout_ms: int) -> bool:
    """Poll until the cleaned lightbox URL differs from ``before_clean``."""
    deadline_steps = max(1, timeout_ms // 100)
    for _ in range(deadline_steps):
        if clean_url(page.url) != before_clean:
            return True
        page.wait_for_timeout(100)
    return clean_url(page.url) != before_clean


def _click_next_arrow(page) -> bool:
    for selector in _NEXT_ARROW_SELECTORS:
        try:
            arrow = page.locator(selector).first
            if arrow.count() == 0 or not arrow.is_visible():
                continue
            arrow.click(timeout=2_000)
            return True
        except Exception:
            continue
    return False


def goto_next(page, *, timeout_ms: int = 8_000) -> bool:
    """Advance to the next photo. Returns True if the URL actually changed.

    A False return means navigation produced no change, which the caller
    interprets (together with the photo-id check) as the end of the album.

    The first (keyboard) attempt gets the *full* timeout budget so a slow but
    genuine load is not mistaken for the end. Only if that whole budget elapses
    with no change do we escalate to clicking the on-screen next arrow — a
    single fallback mechanism rather than re-pressing the key, which could
    double-advance and skip a photo.
    """
    before = clean_url(page.url)

    # Primary: the keyboard shortcut, the normal path, with the full budget.
    page.keyboard.press("ArrowRight")
    if wait_for_url_change(page, before, timeout_ms=timeout_ms):
        return True

    # Escalation: keypresses occasionally don't register under automation, so
    # click the next arrow as a fallback.
    if _click_next_arrow(page):
        if wait_for_url_change(page, before, timeout_ms=min(timeout_ms, 3_000)):
            return True

    return clean_url(page.url) != before
