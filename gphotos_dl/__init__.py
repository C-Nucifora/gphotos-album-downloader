"""gphotos_dl - mass-download original-quality photos from a large shared
Google Photos album by driving the web UI with Playwright.

The package is split into dependency-free logic modules (``urls``,
``navigation``, ``state``, ``verify`` heuristics) that can be unit-tested
without a browser, and Playwright glue modules (``browser``, ``lightbox``,
``downloader``) wired together by ``cli``.
"""

__version__ = "0.1.0"
