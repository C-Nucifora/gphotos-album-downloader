import os
import tempfile
import unittest

from gphotos_dl.state import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SUSPECT,
    Manifest,
    Record,
    build_name,
    dedupe_filename,
    tidy_stem,
)


class TidyStemTests(unittest.TestCase):
    def test_spaces_and_copy_suffix(self):
        self.assertEqual(tidy_stem("IMG 1234 (1)"), "IMG_1234")

    def test_illegal_chars_removed(self):
        self.assertEqual(tidy_stem("a/b:c name"), "abc_name")

    def test_collapses_repeated_separators(self):
        self.assertEqual(tidy_stem("photo___name"), "photo_name")

    def test_empty_falls_back(self):
        self.assertEqual(tidy_stem("   "), "image")

    def test_dotted_names_preserved(self):
        self.assertEqual(tidy_stem("a.b.c"), "a.b.c")


class BuildNameTests(unittest.TestCase):
    def test_cleanup(self):
        self.assertEqual(
            build_name("IMG 1234 (1).JPG", photo_id="X", cleanup=True), "IMG_1234.jpg"
        )

    def test_prefix_verbatim_no_cleanup(self):
        self.assertEqual(
            build_name("IMG_1234.JPG", photo_id="X", prefix="uqr-"), "uqr-IMG_1234.jpg"
        )

    def test_sequential(self):
        self.assertEqual(
            build_name("whatever.mov", photo_id="X", sequential=True, seq_index=7),
            "0007.mov",
        )

    def test_sequential_with_prefix(self):
        self.assertEqual(
            build_name(
                "x.jpg", photo_id="X", prefix="uqr-", sequential=True, seq_index=3
            ),
            "uqr-0003.jpg",
        )

    def test_cleanup_with_prefix(self):
        self.assertEqual(
            build_name("My Photo (2).PNG", photo_id="X", cleanup=True, prefix="a_"),
            "a_My_Photo.png",
        )

    def test_empty_suggested_uses_photo_id_and_default_ext(self):
        self.assertEqual(
            build_name("", photo_id="AF1", default_ext=".mp4"), "AF1.mp4"
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

    def test_reserve_sequential_increments(self):
        m = Manifest(self.path)
        a = m.reserve("first.jpg", photo_id="1", sequential=True)
        b = m.reserve("second.mov", photo_id="2", sequential=True)
        self.assertEqual(a, "0001.jpg")
        self.assertEqual(b, "0002.mov")

    def test_reserve_cleanup_and_prefix(self):
        m = Manifest(self.path)
        name = m.reserve("My Pic (1).JPG", photo_id="1", cleanup=True, prefix="uqr-")
        self.assertEqual(name, "uqr-My_Pic.jpg")

    def test_targets_selects_failed_and_suspect(self):
        with Manifest(self.path) as m:
            m.append(Record(photo_id="ok1", status=STATUS_OK, url="u/ok1", filename="a.jpg"))
            m.append(Record(photo_id="f1", status=STATUS_FAILED, url="u/f1", media_type="video"))
            m.append(Record(photo_id="s1", status=STATUS_SUSPECT, url="u/s1"))
            m.append(Record(photo_id="f2", status=STATUS_FAILED))  # no url -> excluded

        m2 = Manifest(self.path)
        default = m2.targets()
        self.assertEqual([t["photo_id"] for t in default], ["f1"])
        self.assertEqual(default[0]["url"], "u/f1")
        self.assertEqual(default[0]["media_type"], "video")

        with_suspect = m2.targets(retry_suspect=True)
        self.assertEqual([t["photo_id"] for t in with_suspect], ["f1", "s1"])

    def test_targets_preserves_album_order(self):
        with Manifest(self.path) as m:
            m.append(Record(photo_id="b", status=STATUS_FAILED, url="u/b"))
            m.append(Record(photo_id="a", status=STATUS_FAILED, url="u/a"))
        m2 = Manifest(self.path)
        self.assertEqual([t["photo_id"] for t in m2.targets()], ["b", "a"])

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
