import types
import unittest
import os
import io
import tempfile
from unittest.mock import Mock, patch

from gphotos_dl.cli import _type_skipped, _process_api_batch, _run_api_download
from gphotos_dl.metrics import TypeMetrics
from gphotos_dl.state import Manifest, Record, STATUS_OK, STATUS_FAILED


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


class ApiBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manifest = Manifest(os.path.join(self.tmp.name, "manifest.jsonl"))
        self.addCleanup(self.manifest.close)
        self.metrics = TypeMetrics()
        self.args = types.SimpleNamespace(prefix="", cleanup=False, sequential=False,
                                          empty_trash=True, max_retries=2)
        self.item = types.SimpleNamespace(media_key="shared", dedup_key="dedup",
                                          video_duration=None, is_owned=False)
        self.bar = Mock()
        self.save = self._patch("save_shared_to_library")
        self.resolve = self._patch("resolve_owned_by_dedup", return_value={"dedup": "owned"})
        self.fetch = self._patch("fetch_original", return_value=(b"photo", "photo.jpg"))
        self.trash = self._patch("move_to_trash")
        sleep = patch("gphotos_dl.cli.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def _patch(self, name, **kwargs):
        patcher = patch("gphotos_dl.gpwc_api." + name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def _run(self):
        _process_api_batch(None, [self.item], "album", "auth", self.tmp.name,
                           self.manifest, self.metrics, self.bar, self.args)

    def test_owned_item_downloads_without_save_or_trash(self):
        self.item.is_owned = True
        self._run()
        self.assertEqual(self.manifest.status_of("dedup"), STATUS_OK)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "photo.jpg")))
        self.save.assert_not_called()
        self.trash.assert_not_called()

    def test_album_item_without_ownership_metadata_is_never_trashed(self):
        # Upstream gpwc AlbumItem has no is_owned attribute.
        del self.item.is_owned
        self._run()
        self.assertEqual(self.manifest.status_of("dedup"), STATUS_OK)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "photo.jpg")))
        self.trash.assert_not_called()

    def test_library_resolution_error_records_failure(self):
        self.resolve.side_effect = RuntimeError("library unavailable")
        self._run()
        self.assertEqual(self.manifest.status_of("dedup"), STATUS_FAILED)
        self.assertEqual(self.metrics.total_failed, 1)
        self.trash.assert_not_called()

    def test_transient_download_error_is_retried(self):
        self.fetch.side_effect = [RuntimeError("temporary"), (b"photo", "photo.jpg")]
        self._run()
        self.assertEqual(self.manifest.status_of("dedup"), STATUS_OK)
        with open(os.path.join(self.tmp.name, "photo.jpg"), "rb") as fh:
            self.assertEqual(fh.read(), b"photo")

    def test_video_without_server_filename_uses_video_extension(self):
        self.item.video_duration = 1
        self.fetch.return_value = (b"video", None)
        self._run()
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "dedup.mp4")))

    def test_api_rerun_retries_failed_items(self):
        self.manifest.append(Record(photo_id="dedup", status=STATUS_FAILED))
        self.manifest.close()
        self.args.out = self.tmp.name
        self.args.batch_size = 1
        self.args.retry_suspect = False
        self.args.retry_failed = False
        self.args.skip_photos = False
        self.args.skip_videos = False
        with patch("gphotos_dl.cli._load_tqdm", return_value=lambda **kwargs: self.bar), \
                patch("sys.stderr", new_callable=io.StringIO):
            result = _run_api_download(self.args, None, "album", "auth", [self.item])
        self.assertEqual(result, 0)
        self.assertEqual(Manifest(self.manifest.path).status_of("dedup"), STATUS_OK)

    def test_api_download_failure_returns_nonzero(self):
        self.fetch.side_effect = RuntimeError("offline")
        self.args.out = self.tmp.name
        self.args.batch_size = 1
        self.args.retry_suspect = False
        self.args.retry_failed = False
        self.args.skip_photos = False
        self.args.skip_videos = False
        with patch("gphotos_dl.cli._load_tqdm", return_value=lambda **kwargs: self.bar), \
                patch("sys.stderr", new_callable=io.StringIO):
            result = _run_api_download(self.args, None, "album", "auth", [self.item])
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
