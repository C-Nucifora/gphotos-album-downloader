"""One-shot diagnostic for the save-to-library workflow.

Shared-album photos download as recompressed JPEGs; only after "Save"-ing a
shared photo into your own library does the download yield the true original
(e.g. a 24MB Sony .ARW). But saving creates a NEW library item with a NEW photo
id, so the pipeline must *discover* that id to open and download the library
copy.

This probe clicks the "Save" control on the open shared photo and captures how
Google exposes the new library id — via a URL change and/or the ids returned in
the save's internal `batchexecute` response — plus the visible control labels,
so the full pipeline can be built against real behaviour rather than guesses.
"""

from __future__ import annotations

import re

from .urls import photo_id_from_url

_ID_RE = re.compile(r"AF1Qip[\w-]{20,}")

# Candidate ways to find the "Save" control (user reports it as text "save" in
# the top-right toolbar next to Share).
_SAVE_GETTERS = [
    lambda page: page.get_by_role("button", name=re.compile(r"^\s*save\s*$", re.I)),
    lambda page: page.get_by_text(re.compile(r"^\s*save\s*$", re.I)),
    lambda page: page.locator('[aria-label*="save" i]'),
]

_CONTROLS_JS = (
    "() => Array.from(document.querySelectorAll('button,[role=\"button\"]'))"
    ".map(b => b.getAttribute('aria-label') || (b.textContent || '').trim())"
    ".filter(s => s && s.length < 30)"
    ".filter((v, i, a) => a.indexOf(v) === i).slice(0, 30)"
)


def find_and_click_save(page) -> bool:
    """Click the Save-to-library control; return whether something was clicked."""
    for getter in _SAVE_GETTERS:
        try:
            loc = getter(page).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=3_000)
                return True
        except Exception:
            continue
    return False


def probe_save(page) -> dict:
    """Click Save on the current shared photo and report how the new library
    item is exposed. Returns a JSON-serialisable dict."""
    shared_id = photo_id_from_url(page.url)
    shared_url = page.url
    captured: list[dict] = []

    def on_response(resp):
        try:
            if "batchexecute" in resp.url:
                body = resp.text()
                ids = [i for i in dict.fromkeys(_ID_RE.findall(body)) if i != shared_id]
                if ids:
                    captured.append({"url": resp.url.split("?")[0], "new_ids": ids[:8]})
        except Exception:
            pass

    page.on("response", on_response)
    clicked = find_and_click_save(page)
    page.wait_for_timeout(4_000)
    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass

    try:
        controls = page.evaluate(_CONTROLS_JS)
    except Exception:
        controls = []

    return {
        "shared_id": shared_id,
        "shared_url": shared_url,
        "clicked_save": clicked,
        "url_after_save": page.url,
        "url_changed": page.url != shared_url,
        "candidate_new_library_ids": captured,
        "visible_controls": controls,
    }
