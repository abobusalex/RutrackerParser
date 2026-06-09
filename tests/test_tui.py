from pathlib import Path
from tempfile import TemporaryDirectory
import asyncio
import unittest

from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from rutracker_tui.models import Forum, TopicDetails
from rutracker_tui.storage import Storage
from rutracker_tui.tui import PAGE_SIZE, RutrackerApp, _clean_date, _clean_log, _progress_bar, _truncate


class TuiStateTest(unittest.TestCase):
    def test_selection_moves_inside_bounds(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                self.assertEqual(len(app.rows), 2)
                self.assertEqual(app.logs, [])
                app.switch_pane("topics")
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
                app.cycle_sort()
                self.assertEqual(app.sort_code, "4")
                app.toggle_sort_direction()
                self.assertFalse(app.sort_desc)
                app.move_category(1)
                self.assertEqual(app.selected_category, "Софт")
                app.clear_filters()
                self.assertEqual(app.sort_code, "10")
                self.assertTrue(app.sort_desc)
                self.assertEqual(app.category_index, 0)
                self.assertEqual(app.query, "")
            finally:
                app.storage.close()

    def test_log_cleanup_is_plain(self):
        self.assertEqual(_clean_log("⏳ HTTP 521 на https://example.test"), "HTTP 521")
        self.assertEqual(_truncate("abcdef", 4), "abc…")
        self.assertEqual(_progress_bar(50, width=10), "[#####.....]")
        self.assertIsNone(_clean_date("54 GarfieldX 2026"))
        self.assertEqual(_clean_date("01.02.2026"), "01.02.2026")

    def test_progress_log_updates_sync_state(self):
        app = RutrackerApp()
        app.log("progress 3/286 1.0% | Аниме / OVA | page 2 | 12 topics, queued 20 | elapsed 00:00:07")
        self.assertEqual(app.sync_percent, 1.0)
        self.assertEqual(app.sync_elapsed, "00:00:07")
        self.assertEqual(app.sync_branch, "Аниме / OVA")
        self.assertIn("3/286 1.0%", app.logs[-1])

    def test_prompt_toolkit_application_builds(self):
        with TemporaryDirectory() as temp_dir:
            app = RutrackerApp(db_path=Path(temp_dir) / "test.sqlite3")
            application = app._build_application(output=DummyOutput())
            self.assertIsNotNone(application.layout)

    def test_table_hotkeys_are_disabled_while_search_has_focus(self):
        with TemporaryDirectory() as temp_dir:
            app = RutrackerApp(db_path=Path(temp_dir) / "test.sqlite3")
            application = app._build_application(output=DummyOutput())
            application.layout.focus(app.search_field)
            self.assertTrue(app._search_has_focus())
            self.assertFalse(app._normal_hotkeys_enabled())
            application.layout.focus(app.topic_control)
            self.assertFalse(app._search_has_focus())
            self.assertTrue(app._normal_hotkeys_enabled())

    def test_topics_are_paged_and_do_not_render_ids(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3", count=PAGE_SIZE + 2)
            try:
                app.refresh_results()
                app.switch_pane("topics")
                self.assertEqual(app.current_page, 1)
                app.move_topic(PAGE_SIZE)
                self.assertEqual(app.current_page, 2)
                text = "".join(fragment for _, fragment in app._topics_text())
                self.assertNotIn("1000", text)
                self.assertIn("Title", text)
            finally:
                app.storage.close()

    def test_banner_shows_title_and_single_line_magnet(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                text = app._selected_banner_text()
                lines = text.splitlines()
                self.assertEqual(lines[0], "💾 Ubuntu ISO")
                self.assertEqual(lines[1], "🧲 magnet:?xt=urn:btih:test0")
            finally:
                app.storage.close()

    def test_details_show_plain_url_and_compact_meta(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                text = app._details_text()
                self.assertIn("https://example.test/t=1000", text)
                self.assertNotIn("link:", text)
                self.assertNotIn("forum:", text)
                self.assertNotIn("category:", text)
                self.assertIn("🌱 10 | 🪱 0 | 📦 - | 📅 - | 📌 no", text)
                self.assertIn("ascii:", text)
                self.assertIn("@@", text)
                self.assertNotIn("id:", text)
                self.assertNotIn("downloads:", text)
            finally:
                app.storage.close()

    def test_categories_show_emojis(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                text = "".join(fragment for _, fragment in app._categories_text())
                self.assertIn("🌐 Все", text)
                self.assertIn("💾 Софт", text)
            finally:
                app.storage.close()

    def test_footer_has_section_page_and_position(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                footer = app._footer_text()
                self.assertIn("раздел 1/", footer)
                self.assertIn("стр 1/", footer)
                self.assertIn("pos 1/", footer)
            finally:
                app.storage.close()

    def test_fullscreen_details_scrolls_and_uses_full_text(self):
        with TemporaryDirectory() as temp_dir:
            app = _app_with_topics(Path(temp_dir) / "test.sqlite3")
            try:
                app.refresh_results()
                app.open_fullscreen()
                self.assertTrue(app.fullscreen)
                self.assertIn("🧲 magnet:?xt=urn:btih:test0", app._selected_banner_text())
                app.scroll_details(1)
                self.assertEqual(app.detail_scroll, 1)
                app.close_fullscreen()
                self.assertFalse(app.fullscreen)
            finally:
                app.storage.close()


class TuiInputTest(unittest.IsolatedAsyncioTestCase):
    async def test_letters_are_inserted_in_search_instead_of_hotkeys(self):
        with TemporaryDirectory() as temp_dir:
            app = RutrackerApp(db_path=Path(temp_dir) / "test.sqlite3")
            app.storage = Storage(app.db_path)
            try:
                with create_pipe_input() as pipe_input:
                    application = app._build_application(output=DummyOutput(), input=pipe_input)
                    task = asyncio.create_task(application.run_async())
                    await asyncio.sleep(0.05)
                    pipe_input.send_text("/f\r")
                    await asyncio.sleep(0.1)
                    application.exit()
                    await task
                self.assertEqual(app.query, "f")
                self.assertIsNone(app.selected_category)
            finally:
                app.storage.close()


def _app_with_topics(db_path: Path, count: int = 2) -> RutrackerApp:
    storage = Storage(db_path)
    storage.upsert_forums([Forum(id=1, title="Software", url="https://example.test/f=1", category="Софт")])
    for index in range(count):
        storage.upsert_topic_details(
            TopicDetails(
                id=1000 + index,
                forum_id=1,
                title="Ubuntu ISO" if index == 0 else f"Debian ISO {index}",
                url=f"https://example.test/t={1000 + index}",
                magnet=f"magnet:?xt=urn:btih:test{index}",
                seeders=10 - index if index < 10 else 0,
                description="Описание релиза\n" * 4,
                first_image_ascii="@@" if index == 0 else None,
            )
        )
    app = RutrackerApp(db_path=db_path, base_url="https://example.test/forum/")
    app.storage = storage
    return app


if __name__ == "__main__":
    unittest.main()
