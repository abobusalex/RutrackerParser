import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rutracker_tui.crawler import RutrackerCrawler, SyncOptions, _retryable_status
from rutracker_tui.models import Forum


class CrawlerTest(unittest.TestCase):
    def test_retryable_cloudflare_and_rate_statuses(self):
        self.assertTrue(_retryable_status(521))
        self.assertTrue(_retryable_status(429))
        self.assertTrue(_retryable_status(503))
        self.assertFalse(_retryable_status(404))

    def test_forum_progress_log_contains_percent_and_branch(self):
        with TemporaryDirectory() as temp_dir:
            crawler = RutrackerCrawler(SyncOptions(db_path=Path(temp_dir) / "test.sqlite3", base_url="https://example.test/"))
            try:
                message = crawler._forum_progress(
                    Forum(id=1, title="OVA", url="https://example.test/f=1", category="Аниме"),
                    forum_index=3,
                    total_forums=286,
                    page_index=2,
                    state="12 topics",
                )
                self.assertIn("progress 3/286", message)
                self.assertIn("Аниме / OVA", message)
                self.assertIn("elapsed", message)
            finally:
                crawler.storage.close()

    def test_topic_progress_log_contains_worker_counters(self):
        with TemporaryDirectory() as temp_dir:
            crawler = RutrackerCrawler(SyncOptions(db_path=Path(temp_dir) / "test.sqlite3", base_url="https://example.test/"))
            try:
                crawler._active_topics = 3
                crawler._saved_topics = 10
                crawler._skipped_topics = 4
                crawler._failed_topics = 2
                message = crawler._topic_progress(queued=25)
                self.assertIn("active=3", message)
                self.assertIn("queued=25", message)
                self.assertIn("saved=10", message)
                self.assertIn("skipped=4", message)
                self.assertIn("failed=2", message)
            finally:
                crawler.storage.close()


if __name__ == "__main__":
    unittest.main()
