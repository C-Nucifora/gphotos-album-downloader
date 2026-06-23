"""Pure multi-signal end-of-album detection.

Research finding: comparing the lightbox URL before/after a single ArrowRight
is NOT a reliable end signal on its own. Large albums (>500) hit a lazy-load
stall that looks exactly like the end, arrow keypresses occasionally fail to
register, and the URL updates asynchronously. So we combine signals:

  * the lightbox URL stopped changing after *hardened* navigation attempts
    (key press, retried, then a click on the next-arrow), AND/OR
  * we have arrived at a photo id we have already seen (true loop-back to the
    first photo, or a stall that keeps returning the same id).

This module holds only the decision logic; the browser-driving navigation that
produces ``url_changed`` lives in ``lightbox``. Keeping it pure makes the
stop condition unit-testable without a browser.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .urls import photo_id_from_url


class StopReason(enum.Enum):
    CONTINUE = "continue"
    URL_STABLE = "url_stable"          # navigation produced no URL change
    REVISITED = "revisited"            # arrived at an id we have already processed
    NOT_A_PHOTO = "not_a_photo"        # navigation left the lightbox entirely


@dataclass
class NavigationTracker:
    """Tracks visited photo ids and decides when to stop the walk."""

    seen_ids: set[str] = field(default_factory=set)
    order: list[str] = field(default_factory=list)

    def __contains__(self, photo_id: str) -> bool:
        return photo_id in self.seen_ids

    def mark_seen(self, photo_id: str) -> None:
        if photo_id and photo_id not in self.seen_ids:
            self.seen_ids.add(photo_id)
            self.order.append(photo_id)

    def evaluate(self, *, new_url: str, url_changed: bool) -> StopReason:
        """Decide whether to stop, given the post-navigation state.

        ``url_changed`` is the verdict from hardened navigation: True only if
        the lightbox URL actually moved to a different photo. ``new_url`` is
        the current lightbox URL after the navigation attempt.
        """
        if not url_changed:
            return StopReason.URL_STABLE

        new_id = photo_id_from_url(new_url)
        if new_id is None:
            # Navigation left the single-photo view (e.g. bounced to the grid
            # or a sign-in interstitial). Treat as end rather than loop blindly.
            return StopReason.NOT_A_PHOTO

        if new_id in self.seen_ids:
            return StopReason.REVISITED

        return StopReason.CONTINUE
