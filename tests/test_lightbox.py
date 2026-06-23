import unittest

from gphotos_dl.lightbox import media_type_from_aria


class MediaTypeFromAriaTests(unittest.TestCase):
    def test_video(self):
        self.assertEqual(
            media_type_from_aria("Video - Portrait - Jul 12, 2023, 3:04:05 PM"),
            "video",
        )

    def test_photo(self):
        self.assertEqual(
            media_type_from_aria("Photo - Landscape - Jul 12, 2023, 3:04:05 PM"),
            "photo",
        )

    def test_case_insensitive_token(self):
        self.assertEqual(media_type_from_aria("video - x"), "video")

    def test_none_and_unknown(self):
        self.assertIsNone(media_type_from_aria(None))
        self.assertIsNone(media_type_from_aria(""))
        self.assertIsNone(media_type_from_aria("Something else entirely"))


if __name__ == "__main__":
    unittest.main()
