import unittest

from rutracker_tui.crawler import _retryable_status


class CrawlerTest(unittest.TestCase):
    def test_retryable_cloudflare_and_rate_statuses(self):
        self.assertTrue(_retryable_status(521))
        self.assertTrue(_retryable_status(429))
        self.assertTrue(_retryable_status(503))
        self.assertFalse(_retryable_status(404))


if __name__ == "__main__":
    unittest.main()
