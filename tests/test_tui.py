from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prompt_toolkit.output import DummyOutput

from rutracker_tui.models import TopicDetails
from rutracker_tui.storage import Storage
from rutracker_tui.tui import RutrackerApp, _clean_log, _truncate


class TuiStateTest(unittest.TestCase):
    def test_selection_moves_inside_bounds(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                self.assertEqual(len(app.rows), 2)
                app.move_selection(1)
                self.assertEqual(app.selected_index, 1)
                app.move_selection(10)
                self.assertEqual(app.selected_index, 1)
                app.move_selection(-10)
                self.assertEqual(app.selected_index, 0)
            finally:
                app.storage.close()

    def test_filters_are_testable_without_terminal(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                app.toggle_magnet()
                self.assertTrue(app.magnet_only)
                self.assertEqual(len(app.rows), 1)
                app.toggle_seed_filter()
                self.assertEqual(app.min_seeders, 1)
                app.clear_filters()
                self.assertFalse(app.magnet_only)
                self.assertIsNone(app.min_seeders)
                self.assertEqual(app.query, "")
            finally:
                app.storage.close()

    def test_log_cleanup_is_plain(self):
        self.assertEqual(_clean_log("⏳ HTTP 521 на https://example.test"), "HTTP 521")
        self.assertEqual(_truncate("abcdef", 4), "abc…")

    def test_prompt_toolkit_application_builds(self):
        with TemporaryDirectory() as temp_dir:
            app = RutrackerApp(db_path=Path(temp_dir) / "test.sqlite3")
            application = app._build_application(output=DummyOutput())
            self.assertIsNotNone(application.layout)


def _app_with_topics(db_path: Path) -> RutrackerApp:
    storage = Storage(db_path)
    storage.upsert_topic_details(
        TopicDetails(
            id=1,
            title="Ubuntu ISO",
            url="https://example.test/t=1",
            magnet="magnet:?xt=urn:btih:test",
            seeders=10,
        )
    )
    storage.upsert_topic_details(
        TopicDetails(
            id=2,
            title="Debian ISO",
            url="https://example.test/t=2",
            seeders=0,
        )
    )
    app = RutrackerApp(db_path=db_path, base_url="https://example.test/forum/")
    app.storage = storage
    return app


if __name__ == "__main__":
    unittest.main()
