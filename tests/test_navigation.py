import unittest

from gphotos_dl.navigation import NavigationTracker, StopReason

PHOTO_A = "https://photos.google.com/photo/AAA"
PHOTO_B = "https://photos.google.com/photo/BBB"
GRID = "https://photos.google.com/share/TOK"


class TrackerTests(unittest.TestCase):
    def test_mark_and_contains(self):
        t = NavigationTracker()
        self.assertNotIn("AAA", t)
        t.mark_seen("AAA")
        self.assertIn("AAA", t)
        self.assertEqual(t.order, ["AAA"])

    def test_mark_is_idempotent(self):
        t = NavigationTracker()
        t.mark_seen("AAA")
        t.mark_seen("AAA")
        self.assertEqual(t.order, ["AAA"])

    def test_url_stable_means_stop(self):
        t = NavigationTracker()
        self.assertIs(
            t.evaluate(new_url=PHOTO_A, url_changed=False), StopReason.URL_STABLE
        )

    def test_new_photo_continues(self):
        t = NavigationTracker()
        t.mark_seen("AAA")
        self.assertIs(
            t.evaluate(new_url=PHOTO_B, url_changed=True), StopReason.CONTINUE
        )

    def test_revisited_photo_stops(self):
        t = NavigationTracker()
        t.mark_seen("AAA")
        self.assertIs(
            t.evaluate(new_url=PHOTO_A, url_changed=True), StopReason.REVISITED
        )

    def test_left_photo_view_stops(self):
        t = NavigationTracker()
        self.assertIs(
            t.evaluate(new_url=GRID, url_changed=True), StopReason.NOT_A_PHOTO
        )


if __name__ == "__main__":
    unittest.main()
