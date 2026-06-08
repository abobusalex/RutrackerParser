from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rutracker_tui.models import Forum, TopicDetails, TopicFile, TopicSummary
from rutracker_tui.storage import Storage


class StorageTest(unittest.TestCase):
    def test_upsert_and_search_topics(self):
        with TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.sqlite3")
            try:
                self.assertTrue(storage.is_empty())
                storage.upsert_forums([Forum(id=1, title="Linux", url="https://example.test/f=1")])
                storage.upsert_topic_summaries(
                    [
                        TopicSummary(
                            id=42,
                            forum_id=1,
                            title="Ubuntu ISO",
                            url="https://example.test/t=42",
                            size_text="4.7 GB",
                            size_bytes=5046586572,
                            seeders=15,
                            leechers=2,
                        )
                    ]
                )
                rows = storage.search_topics("ubuntu", min_seeders=10, magnet_only=False)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["id"], 42)
                self.assertEqual(rows[0]["forum_title"], "Linux")
                self.assertFalse(storage.is_empty())
                forums = storage.list_forums()
                self.assertEqual(forums[0]["id"], 1)
                self.assertEqual(forums[0]["indexed_topics"], 1)
            finally:
                storage.close()

    def test_topic_details_replace_files(self):
        with TemporaryDirectory() as temp_dir:
            storage = Storage(Path(temp_dir) / "test.sqlite3")
            try:
                storage.upsert_topic_details(
                    TopicDetails(
                        id=7,
                        title="Release",
                        url="https://example.test/t=7",
                        magnet="magnet:?xt=urn:btih:test",
                        files=[TopicFile(path="old.iso", size_text="1 GB", size_bytes=1073741824)],
                    )
                )
                storage.upsert_topic_details(
                    TopicDetails(
                        id=7,
                        title="Release",
                        url="https://example.test/t=7",
                        magnet="magnet:?xt=urn:btih:test",
                        files=[TopicFile(path="new.iso", size_text="2 GB", size_bytes=2147483648)],
                    )
                )
                topic = storage.get_topic(7)
                files = storage.topic_files(7)
                self.assertEqual(topic["magnet"], "magnet:?xt=urn:btih:test")
                self.assertEqual(len(files), 1)
                self.assertEqual(files[0].path, "new.iso")
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
