"""Per-media-type download metrics (photos vs videos).

Aggregates successful/failed counts and download durations by media type so the
status line can show ``photos:N videos:M`` and the final summary can report the
average download time per type. Pure/stdlib-only so it unit-tests without a
browser.
"""

from __future__ import annotations


class TypeMetrics:
    """Tallies downloads by media type ('photo' / 'video')."""

    def __init__(self) -> None:
        self._d: dict[str, dict[str, float]] = {}
        self.skipped = 0   # already done (in manifest)
        self.filtered = 0  # excluded by --skip-videos / --skip-photos

    def _bucket(self, media_type: str | None) -> dict[str, float]:
        key = media_type or "photo"
        return self._d.setdefault(
            key, {"count": 0, "failed": 0, "suspect": 0, "seconds": 0.0}
        )

    def record_success(
        self, media_type: str | None, *, seconds: float | None = None, suspect: bool = False
    ) -> None:
        b = self._bucket(media_type)
        b["count"] += 1
        b["seconds"] += seconds or 0.0
        if suspect:
            b["suspect"] += 1

    def record_failure(self, media_type: str | None) -> None:
        self._bucket(media_type)["failed"] += 1

    def record_skip(self) -> None:
        self.skipped += 1

    def record_filtered(self) -> None:
        self.filtered += 1

    @property
    def total_failed(self) -> int:
        return int(sum(b["failed"] for b in self._d.values()))

    @property
    def total_suspect(self) -> int:
        return int(sum(b["suspect"] for b in self._d.values()))

    def postfix(self) -> dict[str, int]:
        """Compact dict for a tqdm postfix, e.g. {'photos': 42, 'videos': 3}."""
        out: dict[str, int] = {}
        for media_type in ("photo", "video"):
            b = self._d.get(media_type)
            if b:
                out[media_type + "s"] = int(b["count"])
        for media_type, b in self._d.items():
            if media_type not in ("photo", "video") and b["count"]:
                out[media_type] = int(b["count"])
        if self.total_failed:
            out["failed"] = self.total_failed
        if self.skipped:
            out["skipped"] = self.skipped
        if self.filtered:
            out["filtered"] = self.filtered
        return out

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        for media_type in sorted(self._d):
            b = self._d[media_type]
            count = int(b["count"])
            avg = (b["seconds"] / count) if count else 0.0
            suspect = int(b["suspect"])
            suspect_note = f", {suspect} suspect" if suspect else ""
            lines.append(
                f"{media_type}: {count} saved{suspect_note}, "
                f"{int(b['failed'])} failed, avg {avg:.1f}s/item"
            )
        if self.skipped:
            lines.append(f"skipped (already done): {self.skipped}")
        if self.filtered:
            lines.append(f"filtered out (--skip-videos/--skip-photos): {self.filtered}")
        return lines
