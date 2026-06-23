# Design: gphotos-album-downloader

**Date:** 2026-06-23
**Status:** Implemented (v0.1.0)

## Problem

Download every original-quality photo from a large **shared** Google Photos
album, preserving EXIF as far as Google allows, **without** adding anything to
the user's own library.

- Native "Download all" fails on large albums (*"Download is too large"*).
- The official Photos Library API strips EXIF/GPS and re-encodes originals for
  media the user didn't upload, so it can't produce faithful originals.

## Approach (decided: "C — hardened hybrid")

Drive the web UI: open the lightbox, press **Shift+D** per photo, intercept the
download with Playwright, advance with **ArrowRight**, repeat until end. Every
step is hardened against the failure modes the research surfaced.

Approaches considered:
- **A — pure arrow-walk** (the naive spec): simplest, but silently saves resized
  previews and has fragile end detection on large albums.
- **B — enumerate-then-download**: scrape all photo URLs from the grid first.
  Exact total, but grid virtualization is its own brittle scraping surface.
- **C — hardened hybrid (chosen)**: arrow-walk with every mitigation baked in.

## Research findings that shaped the design

(Full sources captured in the build conversation; verified adversarially.)

1. **Speed destroys fidelity (highest-impact).** Downloading too fast returns a
   resized ~1600px copy with EXIF stripped, and the download still succeeds.
   → **Per-photo dwell** before Shift+D + **post-download fidelity check**
   flagging small-and-EXIF-less files as `suspect`.
2. **`expect_download()` + Shift+D + persistent context is *not* reliably
   reliable** (verdict: refuted/uncertain). Documented `canceled` / event-never-
   fired bugs.
   → Register listener *before* keypress (context manager), **focus the lightbox
   first**, **fully `save_as` before navigating** (navigation cancels in-flight
   downloads), **never touch raw CDP `setDownloadBehavior`**, save immediately
   (files are deleted on context close), retry with backoff, **menu-click
   fallback** on later attempts.
3. **URL-stability end detection is unreliable alone** (uncertain→refuted):
   large-album lazy-load stalls look like the end; arrow keypresses sometimes
   don't register; URL updates async.
   → **Multi-signal end**: hardened navigation (key → retry → click next-arrow,
   polling for URL change) AND a **seen photo-id** check (catches loop-back and
   stalls). Photo id parsed from URL, `/u/N/` normalized.
4. **Fidelity is ultimately capped by Google** (owner's upload quality; shared-
   album GPS stripping). Out of scope to fix; documented honestly in README.

## Architecture

Small, single-purpose modules. Dependency-free logic is separated from the
Playwright glue so the logic is unit-testable without a browser.

```
gphotos_dl/
  urls.py        # photo-id parsing, /u/N/ normalization, clean_url  (pure)
  navigation.py  # NavigationTracker + StopReason end-detection      (pure)
  state.py       # JSONL Manifest, resume/should_skip, filename dedupe (pure I/O)
  verify.py      # classify_fidelity (pure) + read_image_meta (Pillow, lazy)
  browser.py     # persistent context launch, login wait, profile lock
  lightbox.py    # open_first_photo, hardened goto_next, url-change poll
  downloader.py  # Shift+D→expect_download→save_as, menu fallback, retry/verify
  cli.py         # argparse + orchestration loop + tqdm + resume hints
```

## Data flow

`cli` launches headed persistent context → `ensure_logged_in` (manual login
once) → goto album URL → `open_first_photo` → loop:

1. `photo_id = photo_id_from_url(page.url)`; stop if `None` or already seen.
2. `manifest.should_skip?` → skip; else `download_current` → `manifest.append`.
3. `tracker.mark_seen` → `goto_next` (hardened) → `tracker.evaluate` →
   stop on `URL_STABLE` / `REVISITED` / `NOT_A_PHOTO`, else randomized delay.

## Error handling

- Per-photo retry with exponential backoff; final failure → `failed` record,
  run continues (never aborts the whole album).
- Ctrl-C safe: every record is flushed+fsynced; resume picks up via manifest.
- Profile-in-use → friendly `ProfileLockedError`.
- Suspect previews surfaced live and in the summary, with the fix (raise dwell,
  `--retry-suspect`).

## Testing

- **Unit (no browser):** `urls`, `navigation`, `state`, `verify` heuristics —
  31 tests, runnable via stdlib `unittest` with zero third-party deps.
- **Integration (manual):** browser/lightbox/downloader against a real shared
  album; cannot be unit-tested without a live Google session.

## Out of scope (YAGNI)

Video/motion-photo special handling (best-effort menu fallback or `skipped`),
parallel downloads (rate-limit risk; concurrency intentionally 1), grid
pre-enumeration (approach B), and any official-API path.
