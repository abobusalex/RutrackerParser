from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rutracker_tui.models import TopicDetails
from rutracker_tui.storage import Storage
from rutracker_tui.tui import RutrackerApp


class TuiTest(unittest.IsolatedAsyncioTestCase):
    async def test_table_gets_initial_focus(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            storage = Storage(db_path)
            try:
                storage.upsert_topic_details(
                    TopicDetails(
                        id=1,
                        title="Ubuntu ISO",
                        url="https://example.test/t=1",
                        magnet="magnet:?xt=urn:btih:test",
                    )
                )
            finally:
                storage.close()

            app = RutrackerApp(db_path=db_path, base_url="https://example.test/forum/")
            async with app.run_test() as pilot:
                table = app.query_one("#results")
                self.assertTrue(table.has_focus)
                await pilot.press("down")
                self.assertTrue(table.has_focus)

    async def test_search_focus_returns_to_table(self):
        with TemporaryDirectory() as temp_dir:
            app = RutrackerApp(db_path=Path(temp_dir) / "test.sqlite3")
            async with app.run_test() as pilot:
                await pilot.press("/")
                self.assertTrue(app.query_one("#query").has_focus)
                await pilot.press("escape")
                self.assertTrue(app.query_one("#results").has_focus)


if __name__ == "__main__":
    unittest.main()
