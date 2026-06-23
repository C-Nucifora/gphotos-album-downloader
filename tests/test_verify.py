import os
import tempfile
import unittest

from gphotos_dl.state import STATUS_OK, STATUS_SUSPECT
from gphotos_dl.verify import classify_fidelity, read_image_meta

try:
    from PIL import Image  # noqa: F401

    HAS_PIL = True
except Exception:
    HAS_PIL = False


class ClassifyTests(unittest.TestCase):
    def test_small_and_no_exif_is_suspect(self):
        self.assertEqual(
            classify_fidelity(1200, 1600, has_exif=False, max_edge=1600),
            STATUS_SUSPECT,
        )

    def test_small_but_has_exif_is_ok(self):
        self.assertEqual(
            classify_fidelity(1200, 1600, has_exif=True, max_edge=1600), STATUS_OK
        )

    def test_large_is_ok_even_without_exif(self):
        self.assertEqual(
            classify_fidelity(4000, 3000, has_exif=False, max_edge=1600), STATUS_OK
        )

    def test_unknown_dimensions_never_suspect(self):
        self.assertEqual(
            classify_fidelity(None, None, has_exif=False, max_edge=1600), STATUS_OK
        )

    def test_unknown_exif_is_ok(self):
        self.assertEqual(
            classify_fidelity(800, 600, has_exif=None, max_edge=1600), STATUS_OK
        )


class ReadMetaTests(unittest.TestCase):
    def test_missing_file_returns_unknowns(self):
        self.assertEqual(read_image_meta("/no/such/file.jpg"), (None, None, None))

    @unittest.skipUnless(HAS_PIL, "Pillow not installed")
    def test_reads_dimensions(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.jpg")
            Image.new("RGB", (320, 240), "blue").save(path)
            w, h, has_exif = read_image_meta(path)
            self.assertEqual((w, h), (320, 240))
            self.assertIn(has_exif, (False, True, None))


if __name__ == "__main__":
    unittest.main()
