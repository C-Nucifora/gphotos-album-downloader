import unittest

from gphotos_dl.urls import (
    clean_url,
    is_lightbox_url,
    photo_id_from_url,
    strip_account_segment,
)


class PhotoIdTests(unittest.TestCase):
    def test_plain_photo_url(self):
        self.assertEqual(
            photo_id_from_url("https://photos.google.com/photo/AF1QipABC"),
            "AF1QipABC",
        )

    def test_account_segment_url(self):
        self.assertEqual(
            photo_id_from_url("https://photos.google.com/u/0/photo/AF1QipABC"),
            "AF1QipABC",
        )

    def test_album_scoped_url(self):
        self.assertEqual(
            photo_id_from_url(
                "https://photos.google.com/album/AF1QipALBUM/photo/AF1QipPHOTO"
            ),
            "AF1QipPHOTO",
        )

    def test_share_url_with_query(self):
        self.assertEqual(
            photo_id_from_url(
                "https://photos.google.com/share/TOK/photo/AF1QipXYZ?key=secret"
            ),
            "AF1QipXYZ",
        )

    def test_non_photo_urls_return_none(self):
        self.assertIsNone(photo_id_from_url("https://photos.google.com/"))
        self.assertIsNone(photo_id_from_url("https://photos.google.com/share/TOK"))
        self.assertIsNone(photo_id_from_url(""))
        self.assertIsNone(photo_id_from_url("https://accounts.google.com/signin"))


class CleanUrlTests(unittest.TestCase):
    def test_strips_account_segment(self):
        self.assertEqual(
            strip_account_segment("https://photos.google.com/u/3/photo/X"),
            "https://photos.google.com/photo/X",
        )

    def test_clean_drops_query_and_account(self):
        a = "https://photos.google.com/u/0/photo/X?key=1#frag"
        b = "https://photos.google.com/photo/X"
        self.assertEqual(clean_url(a), clean_url(b))

    def test_clean_empty(self):
        self.assertEqual(clean_url(""), "")

    def test_is_lightbox_url(self):
        self.assertTrue(is_lightbox_url("https://photos.google.com/photo/X"))
        self.assertFalse(is_lightbox_url("https://photos.google.com/"))


if __name__ == "__main__":
    unittest.main()
