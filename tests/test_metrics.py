import unittest

from gphotos_dl.metrics import TypeMetrics


class TypeMetricsTests(unittest.TestCase):
    def test_counts_and_postfix(self):
        m = TypeMetrics()
        m.record_success("photo", seconds=2.0)
        m.record_success("photo", seconds=4.0)
        m.record_success("video", seconds=10.0)
        m.record_failure("video")
        m.record_skip()
        self.assertEqual(
            m.postfix(),
            {"photos": 2, "videos": 1, "failed": 1, "skipped": 1},
        )
        self.assertEqual(m.total_failed, 1)
        self.assertEqual(m.total_suspect, 0)

    def test_suspect_tracked(self):
        m = TypeMetrics()
        m.record_success("photo", seconds=1.0, suspect=True)
        self.assertEqual(m.total_suspect, 1)

    def test_summary_has_average(self):
        m = TypeMetrics()
        m.record_success("photo", seconds=2.0)
        m.record_success("photo", seconds=4.0)
        lines = "\n".join(m.summary_lines())
        self.assertIn("photo: 2 saved", lines)
        self.assertIn("avg 3.0s/item", lines)

    def test_empty_postfix(self):
        self.assertEqual(TypeMetrics().postfix(), {})


if __name__ == "__main__":
    unittest.main()
