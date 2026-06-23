import os
import tempfile
import unittest

from gphotos_dl.state import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SUSPECT,
    Manifest,
    Record,
    dedupe_filename,
)


class DedupeTests(unittest.TestCase):
    def test_free_name_unchanged(self):
        self.assertEqual(dedupe_filename("a.jpg", set()), "a.jpg")

    def test_collision_appends_counter(self):
        self.assertEqual(dedupe_filename("a.jpg", {"a.jpg"}), "a (1).jpg")

    def test_multiple_collisions(self):
        used = {"a.jpg", "a (1).jpg"}
        self.assertEqual(dedupe_filename("a.jpg", used), "a (2).jpg")

    def test_case_insensitive(self):
        self.assertEqual(dedupe_filename("A.JPG", {"a.jpg"}), "A (1).JPG")


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "manifest.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_then_reload(self):
        with Manifest(self.path) as m:
            m.append(Record(photo_id="AAA", status=STATUS_OK, filename="a.jpg"))
            m.append(Record(photo_id="BBB", status=STATUS_FAILED))

        m2 = Manifest(self.path)
        self.assertEqual(m2.status_of("AAA"), STATUS_OK)
        self.assertEqual(m2.status_of("BBB"), STATUS_FAILED)
        self.assertIn("a.jpg", m2.used_filenames)

    def test_should_skip_rules(self):
        with Manifest(self.path) as m:
            m.append(Record(photo_id="ok", status=STATUS_OK))
            m.append(Record(photo_id="sus", status=STATUS_SUSPECT))
            m.append(Record(photo_id="fail", status=STATUS_FAILED))

        m2 = Manifest(self.path)
        self.assertTrue(m2.should_skip("ok"))
        self.assertFalse(m2.should_skip("new"))
        self.assertTrue(m2.should_skip("sus"))
        self.assertFalse(m2.should_skip("sus", retry_suspect=True))
        self.assertTrue(m2.should_skip("fail"))
        self.assertFalse(m2.should_skip("fail", retry_failed=True))

    def test_last_record_wins(self):
        with Manifest(self.path) as m:
            m.append(Record(photo_id="X", status=STATUS_FAILED))
            m.append(Record(photo_id="X", status=STATUS_OK, filename="x.jpg"))
        m2 = Manifest(self.path)
        self.assertEqual(m2.status_of("X"), STATUS_OK)
        self.assertTrue(m2.should_skip("X"))

    def test_reserve_filename_avoids_collision(self):
        m = Manifest(self.path)
        first = m.reserve_filename("photo.jpg")
        second = m.reserve_filename("photo.jpg")
        self.assertEqual(first, "photo.jpg")
        self.assertEqual(second, "photo (1).jpg")

    def test_scan_dir_seeds_used_filenames(self):
        # A file landed on disk but its record was never appended (crash window).
        with open(os.path.join(self.tmp.name, "orphan.jpg"), "w") as fh:
            fh.write("x")
        m = Manifest(self.path, scan_dir=self.tmp.name)
        # The manifest file itself must not be treated as a reserved photo name.
        self.assertIn("orphan.jpg", m.used_filenames)
        self.assertNotIn(os.path.basename(self.path), m.used_filenames)
        # Reserving the same name now avoids overwriting the orphan.
        self.assertEqual(m.reserve_filename("orphan.jpg"), "orphan (1).jpg")

    def test_tolerates_torn_final_line(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(Record(photo_id="AAA", status=STATUS_OK).to_json() + "\n")
            fh.write('{"photo_id": "BBB", "status":')  # truncated by a hard kill
        m = Manifest(self.path)
        self.assertEqual(m.status_of("AAA"), STATUS_OK)
        self.assertIsNone(m.status_of("BBB"))


if __name__ == "__main__":
    unittest.main()
