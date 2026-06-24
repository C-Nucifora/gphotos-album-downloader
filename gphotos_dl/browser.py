"""Persistent Chromium context + login handling.

Headed, persistent context keyed to a stable ``user_data_dir`` so the user logs
in to Google once and the cookies persist across runs. ``accept_downloads``
defaults to True on persistent contexts but we set it explicitly. We never touch
raw CDP ``setDownloadBehavior`` — mixing that with Playwright's own download
handling is the documented cause of ``Download.save_as: canceled`` failures.
"""

from __future__ import annotations

import os
import re
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


def export_cookies_txt(context, out_path: str) -> int:
    """Write the context's cookies to a Netscape cookies.txt (for the gpwc API
    backend), reusing the already-authenticated Playwright profile so no manual
    browser-extension export is needed. Returns the number of cookies written."""
    cookies = context.cookies()
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c.get("domain", "")
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = int(c.get("expires") or 0)
        if expires < 0:
            expires = 0  # session cookie; gpwc loads with ignore_expires
        lines.append(
            "\t".join([domain, include_sub, path, secure, str(expires),
                       c.get("name", ""), c.get("value", "")])
        )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(cookies)


def _looks_signed_out(url: str) -> bool:
    return "accounts.google.com" in url or "/signin" in url or "ServiceLogin" in url


def _appears_signed_in(page) -> bool:
    """Best-effort: is the Google account actually signed in on this page?

    Shared albums render while logged out (and don't redirect to a sign-in URL),
    so a URL check alone is insufficient. We look for the account control that
    only appears when signed in, and for a visible "Sign in" affordance that
    only appears when signed out.
    """
    if _looks_signed_out(page.url):
        return False
    try:
        if page.locator('a[href*="SignOutOptions"], [aria-label*="Google Account" i]').count() > 0:
            return True
    except Exception:
        pass
    try:
        for getter in (
            lambda: page.get_by_role("link", name=re.compile(r"\bsign in\b", re.I)),
            lambda: page.get_by_role("button", name=re.compile(r"\bsign in\b", re.I)),
        ):
            loc = getter().first
            if loc.count() and loc.is_visible():
                return False
    except Exception:
        pass
    # No positive account control and no visible "Sign in": treat as uncertain ->
    # signed out, so save-to-library prompts rather than failing silently.
    return False


def _wait_for_login(page) -> None:
    print(
        "\n>>> Please sign in to Google in the browser window that just opened.\n"
        ">>> Once your Google Photos library (your account) is visible, return "
        "here and press Enter to continue...",
        file=sys.stderr,
    )
    try:
        input()
    except EOFError:
        # Non-interactive stdin: give the user a fixed window to log in.
        page.wait_for_timeout(60_000)


def interactive_login(page) -> None:
    """One-time explicit sign-in: open Photos and wait for the user to log in."""
    page.goto(PHOTOS_HOME, wait_until="domcontentloaded")
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass
    _wait_for_login(page)
    print("Login saved to the profile. Re-run without --login.", file=sys.stderr)


def ensure_logged_in(page, *, assume_logged_in: bool = False, require_login: bool = False) -> None:
    """Make sure the session is authenticated, prompting for manual login.

    ``require_login`` (used by save-to-library, which truly needs sign-in) uses a
    strict signed-in check and prompts unless we can confirm an account. Without
    it (walk/targeted on a public share) we only prompt when the URL clearly
    shows a signed-out state, so public-share downloads never block on login.
    """
    page.goto(PHOTOS_HOME, wait_until="domcontentloaded")
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    if assume_logged_in:
        return

    if require_login:
        if _appears_signed_in(page):
            return
    elif not _looks_signed_out(page.url):
        return

    _wait_for_login(page)
