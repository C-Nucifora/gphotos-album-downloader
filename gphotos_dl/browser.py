"""Persistent Chromium context + login handling.

Headed, persistent context keyed to a stable ``user_data_dir`` so the user logs
in to Google once and the cookies persist across runs. ``accept_downloads``
defaults to True on persistent contexts but we set it explicitly. We never touch
raw CDP ``setDownloadBehavior`` — mixing that with Playwright's own download
handling is the documented cause of ``Download.save_as: canceled`` failures.
"""

from __future__ import annotations

import os
import sys

PHOTOS_HOME = "https://photos.google.com"

# Reduce the most obvious automation fingerprint; helps avoid Google login walls.
# --mute-audio guarantees silence even if a video re-arms autoplay mid-walk.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
    "--mute-audio",
]


class ProfileLockedError(RuntimeError):
    """Raised when the Chromium profile is already in use by another process."""


def launch_context(playwright, *, profile_dir: str, headless: bool = False):
    """Launch and return a persistent Chromium context."""
    os.makedirs(profile_dir, exist_ok=True)
    lock = os.path.join(profile_dir, "SingletonLock")
    try:
        return playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=headless,
            accept_downloads=True,
            no_viewport=True,
            args=_LAUNCH_ARGS,
            locale="en-US",
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        if os.path.exists(lock):
            raise ProfileLockedError(
                f"The browser profile at {profile_dir!r} is already in use. "
                "Close any Chrome/Chromium window using this profile (or a "
                "previous run of this tool) and try again."
            ) from exc
        raise


def get_page(context):
    """Return the context's initial page, creating one if needed."""
    return context.pages[0] if context.pages else context.new_page()


def _looks_signed_out(url: str) -> bool:
    return "accounts.google.com" in url or "/signin" in url or "ServiceLogin" in url


def ensure_logged_in(page, *, assume_logged_in: bool = False) -> None:
    """Make sure the session is authenticated, prompting for manual login.

    On a fresh profile this opens the Google sign-in page; the user logs in in
    the visible window, then presses Enter in the terminal. On subsequent runs
    the persisted cookies mean we sail straight through with no prompt.
    """
    page.goto(PHOTOS_HOME, wait_until="domcontentloaded")
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    if assume_logged_in:
        return

    if not _looks_signed_out(page.url):
        return  # cookies already valid

    print(
        "\n>>> Please log in to Google in the browser window that just opened.\n"
        ">>> Once your Google Photos library is visible, return here and press "
        "Enter to continue...",
        file=sys.stderr,
    )
    try:
        input()
    except EOFError:
        # Non-interactive stdin: give the user a fixed window to log in.
        page.wait_for_timeout(60_000)
