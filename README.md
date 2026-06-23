# gphotos-album-downloader

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

> **Editing the code?** Run it in place with `python -m gphotos_dl ...` from the
> project root (no install needed) — this always works. The standard editable
> install (`pip install -e .`) can *silently* fail to register on Python
> 3.13+/3.14, leaving the `gphotos-dl` command unable to import `gphotos_dl`.
> If you hit that, add the project root as a plain path file (this is what makes
> live edits reflect through the console script):
> ```bash
> echo "$PWD" > "$(python -c 'import site; print(site.getsitepackages()[0])')/gphotos_dl_dev.pth"
> ```
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
gphotos-dl "<album-url>" --out ~/Pictures/the-album --retry-failed    # redo failures
```

### Useful flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--out DIR` | `./downloads` | where photos + `manifest.jsonl` go |
| `--profile DIR` | `./.gphotos-profile` | Chromium profile holding your login |
| `--dwell SEC` | `2.5` | wait before each download (raise to 5+ if you get suspects) |
| `--min-delay`/`--max-delay` | `0.8`/`2.0` | randomized gap between photos (rate-limit friendly) |
| `--download-timeout SEC` | `120` | per-photo download timeout |
| `--max-retries N` | `3` | attempts per photo (Shift+D, then menu fallback) |
| `--suspect-max-edge PX` | `1600` | long-edge threshold for the preview heuristic |
| `--retry-suspect` / `--retry-failed` | off | re-attempt those statuses on resume |
| `--limit N` | `0` | stop after N photos (great for a test run) |
| `--start-open` | off | skip auto-open; use if you've opened a photo manually |
| `--assume-logged-in` | off | skip the login wait |

### The manifest

`<out>/manifest.jsonl` — one JSON line per photo:

```json
{"photo_id": "AF1Qip...", "status": "ok", "filename": "IMG_1234.jpg",
 "bytes": 5242880, "width": 4032, "height": 3024, "has_exif": true,
 "attempts": 1, "ts": "2026-06-23T...Z"}
```

`status` ∈ `ok` · `suspect` (looks resized) · `failed` (all attempts failed) ·
`skipped`. It's your record of completeness and the engine for resume.

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
