# gphotos-album-downloader

[![CI](https://github.com/C-Nucifora/gphotos-album-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/C-Nucifora/gphotos-album-downloader/actions/workflows/ci.yml)

Mass-download **original-quality** photos from a large **shared** Google Photos
album by driving the web UI with [Playwright](https://playwright.dev/python/).

It exists because the two obvious routes fail:

- **Native "Download all"** breaks on large albums with *"Download is too large."*
- **The official Photos Library API** re-encodes "original quality" images,
  compresses RAW, transcodes video, and **strips EXIF/GPS** for media you didn't
  upload — so it can't reproduce faithful originals.

This tool instead does what *you* would do by hand, just automated and resumable:
open each photo in the lightbox and press **Shift+D** (the "download this
original" shortcut). It **does not add anything to your own library**.

---

## ⚠️ Read this first — what "original" really means

Independent research went into this tool; some limits are imposed by Google and
**no scraper can get around them**:

1. **Fidelity is capped by what the album owner uploaded.** If they backed up in
   *Storage saver* / *High quality*, there is no untouched original to fetch —
   you get their already-compressed copy. You can never get higher resolution
   than what Google stores.
2. **Shared albums may have GPS/location stripped by Google's sharing pipeline**,
   by default, regardless of this tool.
3. **Speed silently destroys fidelity.** If you download too fast (or before
   Google has prepared the original), it hands back a resized ~1600px copy with
   EXIF stripped — and the download still "succeeds." This tool defends against
   that with a per-photo **dwell** and a post-download **fidelity check** that
   flags likely previews as `suspect` (see below). If you see suspects, raise
   `--dwell` and re-run with `--retry-suspect`.
4. It relies on **undocumented Google Photos UI behavior** (the Shift+D
   shortcut, lightbox URLs). Google can change these at any time; selectors are
   kept ARIA/role-based to be as resilient as possible, but breakage is possible.

Even with these caveats, the lightbox download path is **strictly better than
the official API** for faithful originals.

---

## Getting full-resolution / RAW originals (`--save-to-library`)

For a **shared album you don't own**, Google serves the normal download as a
**recompressed JPEG derivative** — e.g. a 24MP Sony `.ARW` comes back as a
~300KB JPEG named `DSC0001.ARW.jpg`, full-dimension but heavily compressed. This
is Google's doing and **no download timing or API setting fixes it**.

The only way to get the true original is to **Save the shared photo into your
own library first**, then download *that* copy. `--save-to-library` automates it:
for each photo it clicks **Save**, finds the new library item, and downloads the
original (e.g. the real 24MB `.ARW`). Videos already come full-res from the
share, so they download directly (use `--skip-videos` to ignore them).

```bash
gphotos-dl "<album-url>" --out ~/Pictures/uqr-raws --save-to-library
```

> ### ⚠️ This mode writes to your Google account and (will) delete from it
> - **It copies every shared photo into YOUR library.** ~900 RAWs ≈ **20+GB**
>   against your Google storage quota.
> - **Storage management — Option A (auto-empty Trash):** to stay under your
>   quota, the batched cleanup deletes each downloaded copy from **your personal
>   library** and then **EMPTIES YOUR GOOGLE PHOTOS TRASH** between batches.
>   **Emptying Trash is global and irreversible — it permanently deletes
>   _everything_ currently in your Trash, including items this tool never
>   touched.** Make sure your Trash holds nothing you want before running.
> - It **never** deletes anything from the shared album — only from your own
>   library/Trash.
>
> *(Status: save → download-original is implemented. The batched auto-delete +
> auto-empty-Trash cleanup is being added next and is gated behind this same
> mode; until then, saved copies remain in your library and you should
> bulk-delete them yourself.)*

---

## Install

Requires Python 3.10+ (tested on 3.14). A virtual environment is recommended
(and required on Homebrew Python due to PEP 668).

```bash
cd ~/Documents/dev/personal/gphotos-album-downloader
python3 -m venv .venv
source .venv/bin/activate

pip install .               # installs the gphotos-dl CLI + deps (playwright, tqdm, Pillow)
playwright install chromium # one-time browser download (~150 MB)
```

> **Editing the code?** Either re-run `pip install .` after changes, or run it
> in place with `python -m gphotos_dl ...` from the project root (no install
> needed). Avoid `pip install -e .` here: editable installs can *silently* fail
> to register on Python 3.13+/3.14, and a plain-path `.pth` is suppressed inside
> conda-initialized shells — both leave `gphotos-dl` unable to import
> `gphotos_dl`. A regular `pip install .` always works.
>
> If `pip install playwright` ever fails on a brand-new Python release (wheels
> can lag), use Python 3.12 or 3.13 for the runtime. The pure-logic test suite
> runs on any Python with no third-party deps.

## Usage

```bash
gphotos-dl "https://photos.google.com/share/AF1Q...." --out ~/Pictures/the-album
```

- **First run:** a real Chrome window opens. Log in to Google, wait until the
  album is visible, then press **Enter** in the terminal. Your session is saved
  to the profile dir, so later runs skip the login.
- The tool opens the first photo, then walks the album with `Shift+D` +
  `ArrowRight`, saving each original into `--out` and logging it to
  `manifest.jsonl`.
- Progress shows in a `tqdm` bar with live `downloaded/skipped/suspect/failed`
  counts. It stops automatically at the end of the album.

### Resume

Just run the **same command again**. Already-downloaded (`ok`) photos are
skipped via the manifest; the run picks up where it left off. Safe to Ctrl-C.

```bash
gphotos-dl "<album-url>" --out ~/Pictures/the-album --retry-suspect   # redo flagged previews
gphotos-dl "<album-url>" --out ~/Pictures/the-album --retry-failed    # redo failures (walk)
gphotos-dl "<album-url>" --out ~/Pictures/the-album --targeted        # fast retry of failures
```

Walk mode steps through every item (skipping done ones cheaply) and is needed to
**discover** items — including any beyond where a run was interrupted. `--targeted`
is the fast path for **retrying known failures**: it jumps straight to the URLs the
manifest already recorded, with no walking, but won't find items never reached. Use
`--targeted` to clear failures quickly, then a normal walk to finish the album.

### Useful flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--out DIR` | `./downloads` | where files + `manifest.jsonl` go |
| `--profile DIR` | `./.gphotos-profile` | Chromium profile holding your login |
| `--dwell SEC` | `2.5` | wait before each download (raise to 5+ if you get suspects) |
| `--min-delay`/`--max-delay` | `0.8`/`2.0` | randomized gap between items (rate-limit friendly) |
| `--download-timeout SEC` | `30` | wait for a download to **start** after Shift+D (the file transfer then runs as long as needed) |
| `--max-retries N` | `3` | attempts per item (Shift+D, then menu fallback) |
| `--prefix STR` | `""` | prepend verbatim to every filename, e.g. `uqr-` → `uqr-IMG_1234.jpg` |
| `--cleanup` | off | tidy names: strip unsafe chars/copy-suffixes, collapse separators |
| `--sequential` | off | rename to zero-padded numbers in order (`0001.jpg`, `0002.mov`, …) |
| `--suspect-max-edge PX` | `1600` | long-edge threshold for the preview heuristic |
| `--retry-suspect` / `--retry-failed` | off | re-attempt those statuses on resume |
| `--targeted` | off | fast retry: jump straight to manifest-recorded failed/suspect URLs (skips the walk) |
| `--debug` | off | on each failure, dump the live DOM (item label + control labels) to `<out>/debug` |
| `--limit N` | `0` | stop after N items (great for a test run) |
| `--start-open` | off | skip auto-open; use if you've opened an item manually |
| `--assume-logged-in` | off | skip the login wait |

### Photos vs videos

Each item is detected as a **photo** or **video** from its lightbox aria-label.
Videos download via the same Shift+D path (original quality, subject to Google's
shared-album limits), are **paused + muted** the moment the tool lands on them,
and are counted separately in the live status line (`photos:N videos:M`) and the
final summary (which reports average download time per type). Motion/Live photos
are treated as photos (a single combined file).

### The manifest

`<out>/manifest.jsonl` — one JSON line per item:

```json
{"photo_id": "AF1Qip...", "status": "ok", "filename": "IMG_1234.jpg",
 "media_type": "photo", "bytes": 5242880, "width": 4032, "height": 3024,
 "has_exif": true, "attempts": 1, "seconds": 3.1, "ts": "2026-06-24T...Z"}
```

`status` ∈ `ok` · `suspect` (looks resized) · `failed` (all attempts failed) ·
`skipped`. Failed records carry a `note` with the captured DOM so you can see
why; re-run with `--retry-failed` to retry them. It's your record of
completeness and the engine for resume.

## Troubleshooting

- **"profile is already in use"** — close any Chrome window using `--profile`,
  or a previous run of this tool.
- **Lots of `suspect` files** — Google is serving previews; raise `--dwell`
  (e.g. `--dwell 6`) and re-run with `--retry-suspect`.
- **"Could not open the first photo"** — open any album photo manually in the
  window, then re-run with `--start-open`.
- **Stops too early** — likely the Google large-album lazy-load stall. Re-run;
  resume skips done items, and a fresh page load usually gets further.

## Development

```bash
python3 -m unittest discover -s tests   # pure-logic tests, no browser needed
```

Browser-driving code (`browser`/`lightbox`/`downloader`) is exercised manually
against a real album; the dependency-free logic (`urls`/`navigation`/`state`/
`verify`) is unit-tested.

## Legal / responsible use

Download only from albums shared with you and that you're permitted to copy.
This automates actions you could perform manually in your own browser session;
use it within Google's Terms of Service and applicable copyright law.
