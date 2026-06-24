import types
import unittest

from gphotos_dl.gpwc_api import item_kind, parse_share_url


class ParseShareUrlTests(unittest.TestCase):
    def test_full_share_url(self):
        album, key = parse_share_url(
            "https://photos.google.com/share/AF1QipTOKEN/photo/AF1QipX?key=MYKEY"
        )
        self.assertEqual(album, "AF1QipTOKEN")
        self.assertEqual(key, "MYKEY")

    def test_album_only(self):
        album, key = parse_share_url("https://photos.google.com/share/AF1QipTOKEN?key=MYKEY")
        self.assertEqual(album, "AF1QipTOKEN")
        self.assertEqual(key, "MYKEY")

    def test_no_key(self):
        album, key = parse_share_url("https://photos.google.com/share/AF1QipTOKEN")
        self.assertEqual(album, "AF1QipTOKEN")
        self.assertIsNone(key)

    def test_not_a_share_url(self):
        album, key = parse_share_url("https://photos.google.com/photo/AF1QipX")
        self.assertIsNone(album)


class ItemKindTests(unittest.TestCase):
    def test_video(self):
        self.assertEqual(item_kind(types.SimpleNamespace(video_duration=1234)), "video")

    def test_photo(self):
        self.assertEqual(item_kind(types.SimpleNamespace(video_duration=None)), "photo")

    def test_motion_photo_counts_as_photo(self):
        item = types.SimpleNamespace(video_duration=None, live_photo_duration=500)
        self.assertEqual(item_kind(item), "photo")


if __name__ == "__main__":
    unittest.main()
