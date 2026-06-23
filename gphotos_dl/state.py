"""Append-only JSONL manifest + resume logic + filename de-duplication.

The manifest is the source of truth for resume. Each downloaded item appends
one JSON line; the *last* line for a given photo id wins. A run can be Ctrl-C'd
at any point and resumed: every record is flushed+fsynced as it is written, so
the manifest always reflects completed work.

Status values:
    ok       - downloaded and looks like a genuine original
    suspect  - downloaded, but looks like a resized preview (small + no EXIF)
    failed   - all download attempts failed
    skipped  - intentionally not downloaded (e.g. unsupported item)

Dependency-free (stdlib only) so it unit-tests without a browser.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

STATUS_OK = "ok"
STATUS_SUSPECT = "suspect"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class Record:
    photo_id: str
    status: str
    filename: str | None = None
    url: str | None = None
    media_type: str | None = None
    bytes: int | None = None
    width: int | None = None
    height: int | None = None
    has_exif: bool | None = None
    attempts: int = 0
    seconds: float | None = None
    note: str | None = None
    ts: str | None = None

    def to_json(self) -> str:
        data = asdict(self)
        if data.get("ts") is None:
            data["ts"] = datetime.now(timezone.utc).isoformat()
        return json.dumps(data, ensure_ascii=False)


# Characters that are illegal in filenames on common filesystems.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# A trailing OS/Google "copy" marker like " (1)" or "(12)".
_COPY_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")
# Runs of separators to collapse.
_SEPS = re.compile(r"[\s._-]*[\s_-][\s._-]*")


def tidy_stem(stem: str) -> str:
    """Clean a filename stem: drop filesystem-illegal chars, a trailing copy
    marker, and collapse separator runs to single underscores.

    'IMG 1234 (1)' -> 'IMG_1234'   ;   'a/b:c name' -> 'abc_name'
    """
    s = _ILLEGAL.sub("", stem)
    s = _COPY_SUFFIX.sub("", s).strip()
    s = _SEPS.sub("_", s)
    s = s.strip("._-")
    return s or "image"


def build_name(
    suggested: str,
    *,
    photo_id: str,
    prefix: str = "",
    cleanup: bool = False,
    sequential: bool = False,
    seq_index: int | None = None,
    default_ext: str = ".jpg",
) -> str:
    """Compute a download filename (before de-duplication).

    Pipeline: choose base name -> sequential numbering OR cleanup of the stem ->
    prepend prefix verbatim. The extension is preserved and lower-cased.
    """
    base = suggested or f"{photo_id}{default_ext}"
    stem, ext = os.path.splitext(base)
    ext = (ext or default_ext).lower()

    if sequential and seq_index is not None:
        stem = f"{seq_index:04d}"
    elif cleanup:
        stem = tidy_stem(stem)

    return f"{prefix}{stem}{ext}"


def dedupe_filename(name: str, used: set[str]) -> str:
    """Return a filename not present in ``used``, appending `` (n)`` if needed.

    ``photo.jpg`` -> ``photo.jpg`` (free) or ``photo (1).jpg`` (taken) etc.
    Comparison is case-insensitive to be safe on macOS's default filesystem.
    """
    lowered = {u.lower() for u in used}
    if name.lower() not in lowered:
        return name
    root, ext = os.path.splitext(name)
    counter = 1
    while True:
        candidate = f"{root} ({counter}){ext}"
        if candidate.lower() not in lowered:
            return candidate
        counter += 1


class Manifest:
    """Reads existing manifest state and appends new records durably."""

    def __init__(self, path: str, scan_dir: str | None = None):
        self.path = path
        # photo_id -> last-seen record info (status, filename, url, media_type).
        # Insertion order preserves first-seen (album) order for targets().
        self._records: dict[str, dict] = {}
        self.used_filenames: set[str] = set()
        self._fh = None
        # Seed reserved names from files already on disk so a resumed run never
        # overwrites a file that exists but isn't (yet) in the manifest, e.g. a
        # download that landed but crashed before its record was appended.
        if scan_dir:
            self._scan_dir(scan_dir)
        self._load()

    def _scan_dir(self, scan_dir: str) -> None:
        manifest_name = os.path.basename(self.path)
        try:
            for name in os.listdir(scan_dir):
                if name == manifest_name:
                    continue
                if os.path.isfile(os.path.join(scan_dir, name)):
                    self.used_filenames.add(name)
        except OSError:
            pass

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a torn final line from a hard kill
                pid = rec.get("photo_id")
                if not pid:
                    continue
                self._records[pid] = rec
                fn = rec.get("filename")
                if fn:
                    self.used_filenames.add(fn)

    def status_of(self, photo_id: str) -> str | None:
        rec = self._records.get(photo_id)
        return rec.get("status") if rec else None

    def targets(self, *, retry_suspect: bool = False) -> list[dict]:
        """Items to (re)download in targeted mode: failed/skipped always,
        suspect only when ``retry_suspect``. Only those with a saved URL, in
        first-seen (album) order. Each dict has photo_id, url, media_type.
        """
        wanted = {STATUS_FAILED, STATUS_SKIPPED}
        if retry_suspect:
            wanted.add(STATUS_SUSPECT)
        out: list[dict] = []
        for pid, rec in self._records.items():
            if rec.get("status") in wanted and rec.get("url"):
                out.append(
                    {
                        "photo_id": pid,
                        "url": rec["url"],
                        "media_type": rec.get("media_type"),
                    }
                )
        return out

    def should_skip(
        self,
        photo_id: str,
        *,
        retry_suspect: bool = False,
        retry_failed: bool = False,
    ) -> bool:
        """Whether a previously-seen photo should be skipped on this run."""
        status = self.status_of(photo_id)
        if status is None:
            return False
        if status == STATUS_OK:
            return True
        if status == STATUS_SUSPECT:
            return not retry_suspect
        if status in (STATUS_FAILED, STATUS_SKIPPED):
            return not retry_failed
        return False

    def reserve_filename(self, desired: str) -> str:
        """Pick a collision-free filename and reserve it immediately."""
        name = dedupe_filename(desired, self.used_filenames)
        self.used_filenames.add(name)
        return name

    def reserve(
        self,
        suggested: str,
        *,
        photo_id: str,
        prefix: str = "",
        cleanup: bool = False,
        sequential: bool = False,
        default_ext: str = ".jpg",
    ) -> str:
        """Build the final filename (cleanup/sequential/prefix), de-dupe, reserve.

        Sequential numbers continue from the count of files already reserved, so
        a resumed run keeps numbering upward rather than colliding.
        """
        seq_index = len(self.used_filenames) + 1 if sequential else None
        name = build_name(
            suggested,
            photo_id=photo_id,
            prefix=prefix,
            cleanup=cleanup,
            sequential=sequential,
            seq_index=seq_index,
            default_ext=default_ext,
        )
        return self.reserve_filename(name)

    def append(self, record: Record) -> None:
        if self._fh is None:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")
        self._fh.write(record.to_json() + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._records[record.photo_id] = {
            "status": record.status,
            "filename": record.filename,
            "url": record.url,
            "media_type": record.media_type,
        }
        if record.filename:
            self.used_filenames.add(record.filename)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for rec in self._records.values():
            status = rec.get("status", "")
            out[status] = out.get(status, 0) + 1
        return out

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Manifest":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
