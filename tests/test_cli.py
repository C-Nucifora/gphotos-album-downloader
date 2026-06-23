import types
import unittest

from gphotos_dl.cli import _type_skipped


def _args(skip_videos=False, skip_photos=False):
    return types.SimpleNamespace(skip_videos=skip_videos, skip_photos=skip_photos)


class TypeSkipTests(unittest.TestCase):
    def test_skip_videos(self):
        self.assertTrue(_type_skipped("video", _args(skip_videos=True)))
        self.assertFalse(_type_skipped("photo", _args(skip_videos=True)))

    def test_skip_photos(self):
        self.assertTrue(_type_skipped("photo", _args(skip_photos=True)))
        self.assertFalse(_type_skipped("video", _args(skip_photos=True)))

    def test_neither_skipped_by_default(self):
        self.assertFalse(_type_skipped("photo", _args()))
        self.assertFalse(_type_skipped("video", _args()))


if __name__ == "__main__":
    unittest.main()
