"""Command-line entry point: wire the pieces together into the download loop.

Two modes:
  * walk (default) - open the album lightbox and step through every item,
    downloading new ones and cheaply skipping already-done ones, until the end.
  * --targeted - jump straight to the URLs of items already recorded
    failed/suspect in the manifest (fast retry), skipping the whole walk.

Both record to a resumable JSONL manifest and are safe to Ctrl-C and resume.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

from . import __version__, browser, downloader, lightbox
from .metrics import TypeMetrics
from .navigation import NavigationTracker, StopReason
from .state import STATUS_FAILED, STATUS_SUSPECT, Manifest, Record
from .urls import is_lightbox_url, photo_id_from_url


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gphotos-dl",
        description=(
            "Mass-download original-quality photos and videos from a large "
            "shared Google Photos album by driving the web UI with Playwright. "
            "Does NOT add anything to your own library."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("album_url", help="URL of the shared Google Photos album")
    p.add_argument("--out", default="./downloads", help="directory to save files into")
    p.add_argument(
        "--profile",
        default="./.gphotos-profile",
        help="Chromium user-data dir that persists your Google login",
    )
    p.add_argument(
        "--dwell",
        type=float,
        default=2.5,
        help="seconds to wait before each download so Google serves the "
        "original instead of a resized preview (raise if you get 'suspect' files)",
    )
    p.add_argument("--min-delay", type=float, default=0.8, help="min seconds between items")
    p.add_argument("--max-delay", type=float, default=2.0, help="max seconds between items")
    p.add_argument(
        "--download-timeout",
        type=float,
        default=30.0,
        help="seconds to wait for a download to START after Shift+D (a real one "
        "starts in 1-2s); the file transfer itself then runs as long as needed",
    )
    p.add_argument(
        "--nav-timeout",
        type=float,
        default=8.0,
        help="seconds to wait for the lightbox to advance to the next photo",
    )
    p.add_argument("--max-retries", type=int, default=3, help="download attempts per item")
    p.add_argument(
        "--prefix",
        default="",
        help="string prepended verbatim to every filename, e.g. 'uqr-'",
    )
    p.add_argument(
        "--cleanup",
        action="store_true",
        help="tidy filenames: strip unsafe chars/copy-suffixes, collapse separators",
    )
    p.add_argument(
        "--sequential",
        action="store_true",
        help="rename downloads to zero-padded numbers in order (0001.jpg, ...)",
    )
    p.add_argument(
        "--targeted",
        action="store_true",
        help="retry only items already recorded failed/suspect by jumping "
        "directly to their saved URLs (fast; won't discover items never reached)",
    )
    p.add_argument(
        "--suspect-max-edge",
        type=int,
        default=1600,
        help="images with long edge <= this AND no EXIF are flagged 'suspect'",
    )
    p.add_argument(
        "--retry-suspect",
        action="store_true",
        help="re-download items previously flagged 'suspect'",
    )
    p.add_argument(
        "--retry-failed",
        action="store_true",
        help="re-attempt items previously recorded 'failed'/'skipped' (walk mode)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="on each failure, write the live DOM (item label, controls) to <out>/debug",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="stop after N items this run (0 = no limit); handy for a test run",
    )
    p.add_argument(
        "--start-open",
        action="store_true",
        help="a photo is already open in the lightbox; skip auto-opening the first",
    )
    p.add_argument(
        "--assume-logged-in",
        action="store_true",
        help="skip the login wait (use when the profile is already authenticated)",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="run without a visible window (NOT recommended; downloads are flakier)",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _load_tqdm():
    try:
        from tqdm import tqdm

        return tqdm
    except Exception:
        class _Fallback:  # minimal stand-in if tqdm is missing
            def __init__(self, *a, **k):
                self.n = 0

            def update(self, x=1):
                self.n += x
                if self.n % 25 == 0:
                    print(f"  ...{self.n} items processed", file=sys.stderr)

            def set_postfix(self, **k):
                pass

            def write(self, msg):
                print(msg, file=sys.stderr)

            def close(self):
                pass

        return _Fallback


def _resume_hint(args) -> str:
    return (
        f"Resume any time with the same command:\n"
        f"  gphotos-dl {args.album_url!r} --out {args.out!r} --profile {args.profile!r}"
    )


def _process_download(
    page,
    *,
    photo_id,
    args,
    out_dir,
    manifest,
    event_timeout_ms,
    debug_dir,
    metrics,
    bar,
    fallback_kind="photo",
):
    """Detect type, pause video, download the open item, record it, tally."""
    kind = lightbox.media_type(page) or fallback_kind
    lightbox.pause_videos(page)
    record = downloader.download_current(
        page,
        out_dir=out_dir,
        manifest=manifest,
        dwell_s=args.dwell,
        event_timeout_ms=event_timeout_ms,
        max_retries=args.max_retries,
        suspect_max_edge=args.suspect_max_edge,
        media_type=kind,
        prefix=args.prefix,
        cleanup=args.cleanup,
        sequential=args.sequential,
        debug_dir=debug_dir,
    )
    manifest.append(record)
    if record.status == STATUS_FAILED:
        metrics.record_failure(record.media_type)
        bar.write(f"  failed ({kind}): {photo_id} — {record.note}")
    else:
        metrics.record_success(
            record.media_type,
            seconds=record.seconds,
            suspect=(record.status == STATUS_SUSPECT),
        )
        if record.status == STATUS_SUSPECT:
            bar.write(
                f"  suspect (looks resized): {record.filename} "
                f"[{record.width}x{record.height}] — raise --dwell and re-run "
                "with --retry-suspect"
            )
    return record


def _run_walk(page, args, out_dir, manifest, metrics, tqdm, event_timeout_ms, nav_timeout_ms, debug_dir):
    """Step through the whole album lightbox, downloading new items."""
    tracker = NavigationTracker()
    bar = tqdm(total=None, unit="item", desc="Downloading")
    try:
        processed = 0
        while True:
            photo_id = photo_id_from_url(page.url)
            if photo_id is None:
                bar.write("Left the photo view; stopping.")
                break
            if photo_id in tracker:
                bar.write("Returned to an already-seen photo; stopping.")
                break

            skip = manifest.should_skip(
                photo_id,
                retry_suspect=args.retry_suspect,
                retry_failed=args.retry_failed,
            )
            if skip:
                # Already done: walk past it — no media probe, no pause, no dwell,
                # and (below) no inter-item delay.
                metrics.record_skip()
            else:
                _process_download(
                    page,
                    photo_id=photo_id,
                    args=args,
                    out_dir=out_dir,
                    manifest=manifest,
                    event_timeout_ms=event_timeout_ms,
                    debug_dir=debug_dir,
                    metrics=metrics,
                    bar=bar,
                )

            tracker.mark_seen(photo_id)
            processed += 1
            bar.update(1)
            bar.set_postfix(**metrics.postfix())

            if args.limit and processed >= args.limit:
                bar.write(f"Reached --limit of {args.limit}; stopping.")
                break

            try:
                changed = lightbox.goto_next(page, timeout_ms=nav_timeout_ms)
            except Exception as exc:
                bar.write(f"Navigation error: {exc}; stopping (progress saved).")
                break
            reason = tracker.evaluate(new_url=page.url, url_changed=changed)
            if reason is StopReason.URL_STABLE:
                bar.write("Reached the end of the album (no further items).")
                break
            if reason is StopReason.REVISITED:
                bar.write("Looped back to a seen item; reached the end.")
                break
            if reason is StopReason.NOT_A_PHOTO:
                bar.write("Navigation left the album; stopping.")
                break

            if not skip:  # throttle only after a real download
                time.sleep(random.uniform(args.min_delay, args.max_delay))
    finally:
        bar.close()


def _run_targeted(page, args, out_dir, manifest, metrics, tqdm, event_timeout_ms, debug_dir):
    """Jump directly to each manifest-recorded failed/suspect item's URL."""
    targets = manifest.targets(retry_suspect=args.retry_suspect)
    if args.limit:
        targets = targets[: args.limit]
    if not targets:
        print(
            "Targeted mode: no failed/suspect items with a saved URL to retry. "
            "(Run a normal walk first to discover/record items.)",
            file=sys.stderr,
        )
        return

    print(f"Targeted retry of {len(targets)} item(s).", file=sys.stderr)
    bar = tqdm(total=len(targets), unit="item", desc="Retrying")
    try:
        for target in targets:
            try:
                page.goto(target["url"], wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
            except Exception as exc:
                _record_targeted_failure(manifest, metrics, bar, target, f"goto failed: {exc}")
                bar.update(1)
                bar.set_postfix(**metrics.postfix())
                continue

            pid = photo_id_from_url(page.url)
            if pid is None or not is_lightbox_url(page.url):
                _record_targeted_failure(
                    manifest, metrics, bar, target,
                    f"deep-link did not open the item (landed on {page.url})",
                )
                bar.update(1)
                bar.set_postfix(**metrics.postfix())
                continue

            _process_download(
                page,
                photo_id=pid,
                args=args,
                out_dir=out_dir,
                manifest=manifest,
                event_timeout_ms=event_timeout_ms,
                debug_dir=debug_dir,
                metrics=metrics,
                bar=bar,
                fallback_kind=target.get("media_type") or "photo",
            )
            bar.update(1)
            bar.set_postfix(**metrics.postfix())
            time.sleep(random.uniform(args.min_delay, args.max_delay))
    finally:
        bar.close()


def _record_targeted_failure(manifest, metrics, bar, target, note):
    record = Record(
        photo_id=target["photo_id"],
        status=STATUS_FAILED,
        url=target["url"],
        media_type=target.get("media_type"),
        note=note,
    )
    manifest.append(record)
    metrics.record_failure(target.get("media_type"))
    bar.write(f"  failed: {target['photo_id']} — {note}")


def run(args) -> int:
    from playwright.sync_api import sync_playwright

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.jsonl")
    profile_dir = os.path.abspath(args.profile)
    tqdm = _load_tqdm()

    event_timeout_ms = int(args.download_timeout * 1000)
    nav_timeout_ms = int(args.nav_timeout * 1000)
    debug_dir = os.path.join(out_dir, "debug") if args.debug else None

    with sync_playwright() as pw:
        try:
            context = browser.launch_context(pw, profile_dir=profile_dir, headless=args.headless)
        except browser.ProfileLockedError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            return 2

        page = browser.get_page(context)
        try:
            browser.ensure_logged_in(page, assume_logged_in=args.assume_logged_in)

            print(f"Opening album: {args.album_url}", file=sys.stderr)
            try:
                page.goto(args.album_url, wait_until="domcontentloaded")
            except Exception as exc:
                raise RuntimeError(f"Failed to load the album page: {exc}") from exc
            page.wait_for_timeout(2_000)

            manifest = Manifest(manifest_path, scan_dir=out_dir)
            metrics = TypeMetrics()
            try:
                if args.targeted:
                    _run_targeted(
                        page, args, out_dir, manifest, metrics, tqdm,
                        event_timeout_ms, debug_dir,
                    )
                else:
                    if not args.start_open:
                        lightbox.open_first_photo(page)
                    _run_walk(
                        page, args, out_dir, manifest, metrics, tqdm,
                        event_timeout_ms, nav_timeout_ms, debug_dir,
                    )
            finally:
                manifest.close()

            print("\n--- Summary ---", file=sys.stderr)
            print("This run:", file=sys.stderr)
            for line in metrics.summary_lines():
                print(f"  {line}", file=sys.stderr)
            print(f"Manifest totals (all runs): {manifest.counts()}", file=sys.stderr)
            print(f"Files saved to: {out_dir}", file=sys.stderr)
            if metrics.total_suspect:
                print(
                    "Some files look like resized previews. Raise --dwell (e.g. 5) "
                    "and re-run with --retry-suspect.",
                    file=sys.stderr,
                )
            if metrics.total_failed:
                print(
                    f"{metrics.total_failed} item(s) failed — re-run with --targeted "
                    "(fast) or --retry-failed to retry them (add --debug to capture why).",
                    file=sys.stderr,
                )
            return 0
        finally:
            context.close()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nInterrupted. Progress is saved.", file=sys.stderr)
        print(_resume_hint(args), file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # backstop: Playwright errors are not RuntimeError
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
        print(_resume_hint(args), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
