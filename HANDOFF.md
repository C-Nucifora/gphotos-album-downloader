# HANDOFF — gphotos-album-downloader

Continuation notes for picking this up in a fresh session (e.g. after a machine
restart). Read this, then `README.md`, then `docs/superpowers/specs/2026-06-23-gphotos-album-downloader-design.md`.

## What this is

A Python CLI that mass-downloads original-quality photos from a large **shared**
Google Photos album by driving the web UI with Playwright (lightbox + `Shift+D`
+ `ArrowRight`), resumable via a JSONL manifest. Does **not** add to the user's
library. Background: native "Download all" fails on big albums; the official API
strips EXIF.

## Status: built, unit-tested, and runnable. NOT yet run against a live album.

Done and **verified**:
- Full package implemented (`gphotos_dl/`), approach "C — hardened hybrid".
- 31 unit tests pass (`python3 -m unittest discover -s tests`), including the
  Pillow-backed one. Pure-logic tests need no third-party deps.
- `.venv` created with Python 3.14.5; `pip install -e .` succeeded
  (playwright 1.60, Pillow 12.2, tqdm). `playwright install chromium` done
  (`chromium-1223`), and a headless launch smoke test passed.
- `gphotos-dl --help` / `--version` work; all modules import without errors.

**NOT done** (needs a real Google account + a real shared album — the user must
drive this):
- End-to-end run against a live shared album. This is the real test and where
  selector/timing tweaks are likely needed (see "Likely first fixes").
- Tuning `--dwell` so downloads are originals, not `suspect` previews.

## How to run (after restart)

```bash
cd ~/dev/gphotos-album-downloader
source .venv/bin/activate          # venv already has all deps + chromium
gphotos-dl "<shared-album-url>" --out ~/Pictures/the-album --limit 5
```
Use `--limit 5` for the first smoke test. First run opens a Chrome window —
log in to Google, then press Enter in the terminal. Inspect the 5 files: are
they full-resolution with EXIF? Check `manifest.jsonl` statuses.

## Likely first fixes (where live testing will bite)

These are the brittle, unverifiable-without-a-live-session spots. If something
breaks, look here first:

1. **`open_first_photo` selectors** (`lightbox.py`) — grid tiles are
   `a[href*="/photo/"]`. If Google's grid uses non-anchor tiles, this fails;
   fall back to `--start-open` (open a photo by hand) and/or add a selector.
2. **`goto_next` / next-arrow click** (`lightbox.py`) — keypress may not
   register; the click fallback uses `[aria-label*="next" i]`. Confirm the real
   aria-label against the live DOM (`page.pause()` / Playwright inspector).
3. **Menu-download fallback selectors** (`downloader.py`) — `More options` /
   `Download` menu item labels. Verify against the live toolbar.
4. **`suspect` flagging** — if real originals get flagged, raise `--dwell` or
   `--suspect-max-edge`. If previews slip through as `ok`, lower the edge or
   tighten the heuristic in `verify.classify_fidelity`.
5. **Login detection** (`browser.ensure_logged_in`) — heuristic; if it prompts
   when already logged in (or vice versa), tune `_looks_signed_out`.

Best debugging tool: `PWDEBUG=1` or add `page.pause()` to step through the live
DOM and read real selectors.

## Design decisions already locked (don't re-litigate)

- Approach **C** (hardened hybrid), not pure arrow-walk or grid-enumeration.
- **Resume & skip duplicates** via manifest; **always-visible** browser;
  **manifest log** kept. (User chose all three.)
- Concurrency is intentionally **1** (rate-limit safety).
- Project lives at `~/dev/gphotos-album-downloader`; **push to GitHub later**.
- Git: no Claude co-author/trailers (user's global rule); commit email
  `cgnucifora@proton.me` (this is NOT a UQR repo, so not the gmail address).

## Known hard limits (document, don't try to "fix")

- "Original" is capped by the album owner's upload quality.
- Shared albums may have GPS stripped by Google's pipeline.
- Relies on undocumented Google UI; can break on Google deploys.

## Repo map

```
gphotos_dl/{urls,navigation,state,verify,browser,lightbox,downloader,cli}.py
tests/                         # 31 unittest tests, no browser needed
docs/superpowers/specs/2026-06-23-gphotos-album-downloader-design.md
README.md  requirements.txt  pyproject.toml  .gitignore
.venv/                         # gitignored; deps + chromium installed
```

## Suggested next steps for the new session

1. Smoke-test with `--limit 5` against the real album; inspect files + manifest.
2. Fix any selector/timing issues from the live DOM (see "Likely first fixes").
3. Tune `--dwell` until no `suspect` files.
4. Full run; verify completeness via the manifest counts.
5. When happy: `git remote add origin <gh-url> && git push -u origin main`.
6. Optional hardening: a `--verify` pass that re-checks all `ok` files, and
   richer video/motion-photo handling.
