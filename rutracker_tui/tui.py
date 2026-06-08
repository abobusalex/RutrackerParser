from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import httpx
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from .config import BASE_URL, default_db_path
from .crawler import RutrackerCrawler, SyncOptions, options_from_env
from .parser import parse_size
from .storage import SORTS, Storage


MAX_ROWS = 300


class RutrackerApp:
    def __init__(self, db_path: Path = default_db_path(), base_url: str = BASE_URL):
        self.db_path = db_path
        self.base_url = base_url
        self.storage: Storage | None = None
        self.rows: list[Any] = []
        self.selected_index = 0
        self.query = ""
        self.sort_codes = ["1", "2", "4", "10", "11", "7"]
        self.sort_code = "1"
        self.sort_desc = True
        self.categories = ["Все"]
        self.category_index = 0
        self.max_size_text = ""
        self.logs: list[str] = []
        self.stats = {
            "forums": 0,
            "topics": 0,
            "crawled_topics": 0,
            "magnets": 0,
            "files": 0,
        }
        self.syncing = False
        self.search_field = TextArea(
            height=1,
            prompt="search> ",
            multiline=False,
            accept_handler=self._submit_search,
        )
        self.table_control = FormattedTextControl(self._table_text, focusable=True)
        self.app: Application[None] | None = None

    def run(self) -> None:
        self.storage = Storage(self.db_path)
        try:
            self.refresh_results()
            self._build_application().run()
        finally:
            if self.storage:
                self.storage.close()

    def refresh_results(self) -> None:
        if not self.storage:
            return
        max_size = parse_size(self.max_size_text)[1] if self.max_size_text else None
        self.rows = self.storage.search_topics(
            query=self.query,
            max_size_bytes=max_size,
            category=self.selected_category,
            sort_code=self.sort_code,
            sort_desc=self.sort_desc,
            limit=MAX_ROWS,
        )
        self.selected_index = min(self.selected_index, max(0, len(self.rows) - 1))
        self._update_stats()
        self._invalidate()

    def move_selection(self, delta: int) -> None:
        if not self.rows:
            self.selected_index = 0
            return
        self.selected_index = max(0, min(len(self.rows) - 1, self.selected_index + delta))
        self._invalidate()

    @property
    def selected_category(self) -> str | None:
        category = self.categories[self.category_index] if self.categories else "Все"
        return None if category == "Все" else category

    def cycle_sort(self) -> None:
        index = self.sort_codes.index(self.sort_code)
        self.sort_code = self.sort_codes[(index + 1) % len(self.sort_codes)]
        self.log(f"sort {SORTS[self.sort_code][1]}")
        self.refresh_results()

    def toggle_sort_direction(self) -> None:
        self.sort_desc = not self.sort_desc
        self.log(f"direction {'desc' if self.sort_desc else 'asc'}")
        self.refresh_results()

    def cycle_category(self) -> None:
        self._load_categories()
        self.category_index = (self.category_index + 1) % len(self.categories)
        self.log(f"category {self.categories[self.category_index]}")
        self.refresh_results()

    def clear_filters(self) -> None:
        self.query = ""
        self.search_field.text = ""
        self.sort_code = "1"
        self.sort_desc = True
        self.category_index = 0
        self.max_size_text = ""
        self.log("filters cleared")
        self.refresh_results()

    def log(self, message: str) -> None:
        clean_message = _clean_log(message)
        if clean_message:
            self.logs.append(clean_message)
            self.logs = self.logs[-8:]
            self._invalidate()

    def _build_application(self, output: Any | None = None, input: Any | None = None) -> Application[None]:
        body = VSplit(
            [
                Window(self.table_control, wrap_lines=False),
                Window(width=1, char="│"),
                Window(FormattedTextControl(self._details_text), wrap_lines=True, width=48),
            ]
        )
        root = HSplit(
            [
                Window(FormattedTextControl(self._header_text), height=2),
                self.search_field,
                Window(height=1, char="─"),
                body,
                Window(height=1, char="─"),
                Window(FormattedTextControl(self._log_text), height=8, wrap_lines=True),
                Window(FormattedTextControl(self._footer_text), height=1),
            ]
        )
        layout = Layout(root, focused_element=self.table_control)
        self.app = Application(
            layout=layout,
            key_bindings=self._key_bindings(),
            full_screen=True,
            output=output,
            input=input,
        )
        return self.app

    def _key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()
        table_mode = Condition(self._table_hotkeys_enabled)
        search_mode = Condition(self._search_has_focus)

        @bindings.add("c-c")
        def _(event: Any) -> None:
            event.app.exit()

        @bindings.add("q", filter=table_mode)
        def _(event: Any) -> None:
            event.app.exit()

        @bindings.add("up", filter=table_mode)
        def _(event: Any) -> None:
            self.move_selection(-1)

        @bindings.add("down", filter=table_mode)
        def _(event: Any) -> None:
            self.move_selection(1)

        @bindings.add("pageup", filter=table_mode)
        def _(event: Any) -> None:
            self.move_selection(-10)

        @bindings.add("pagedown", filter=table_mode)
        def _(event: Any) -> None:
            self.move_selection(10)

        @bindings.add("/", filter=table_mode)
        def _(event: Any) -> None:
            event.app.layout.focus(self.search_field)

        @bindings.add("escape", filter=search_mode)
        def _(event: Any) -> None:
            event.app.layout.focus(self.table_control)

        @bindings.add("r", filter=table_mode)
        def _(event: Any) -> None:
            self.refresh_results()

        @bindings.add("o", filter=table_mode)
        def _(event: Any) -> None:
            self.cycle_sort()

        @bindings.add("d", filter=table_mode)
        def _(event: Any) -> None:
            self.toggle_sort_direction()

        @bindings.add("g", filter=table_mode)
        def _(event: Any) -> None:
            self.cycle_category()

        @bindings.add("c", filter=table_mode)
        def _(event: Any) -> None:
            self.clear_filters()

        @bindings.add("s", filter=table_mode)
        def _(event: Any) -> None:
            if not self.syncing:
                event.app.create_background_task(self._sync())

        return bindings

    def _submit_search(self, _: Any) -> bool:
        self.query = self.search_field.text.strip()
        self.refresh_results()
        if self.app:
            self.app.layout.focus(self.table_control)
        return True

    async def _sync(self) -> None:
        self.syncing = True
        self.log("sync started")
        options = options_from_env(self.db_path, self.base_url, workers=4, delay=1.0)
        crawler = RutrackerCrawler(
            SyncOptions(
                db_path=options.db_path,
                base_url=options.base_url,
                workers=options.workers,
                delay=options.delay,
                username=options.username,
                password=options.password,
                retries=2,
                retry_backoff=2.0,
            ),
            log=self.log,
        )
        try:
            await crawler.run()
            self.log("sync done")
        except httpx.HTTPStatusError as exc:
            self.log(_short_http_error(exc))
        except httpx.HTTPError as exc:
            self.log(f"network error: {type(exc).__name__}")
        except Exception as exc:
            self.log(f"sync error: {type(exc).__name__}")
        finally:
            await crawler.close()
            self.syncing = False
            self.refresh_results()

    def _search_has_focus(self) -> bool:
        if self.app is None:
            return False
        try:
            return self.app.layout.has_focus(self.search_field)
        except Exception:
            return False

    def _table_hotkeys_enabled(self) -> bool:
        return not self._search_has_focus()

    def _header_text(self) -> HTML:
        status = "syncing" if self.syncing else "ready"
        filters = []
        if self.query:
            filters.append(f"query={self.query}")
        if self.selected_category:
            filters.append(f"group={self.selected_category}")
        filters.append(f"sort={SORTS[self.sort_code][1]}")
        filters.append("desc" if self.sort_desc else "asc")
        filter_text = " | ".join(filters) if filters else "no filters"
        return HTML(f"<b>RuTracker</b>  {status}  |  rows {len(self.rows)}  |  topics {self.stats['topics']}\n{filter_text}")

    def _table_text(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = [
            ("class:header", "ID       M  Seeds  Size       Title\n"),
        ]
        if not self.rows:
            fragments.append(("", "Нет данных. s — синхронизация.\n"))
            return fragments
        for index, row in enumerate(self.rows):
            marker = ">" if index == self.selected_index else " "
            magnet = "M" if row["magnet"] else "."
            title = _truncate(row["title"], 64)
            size = _truncate(row["size_text"] or "-", 10)
            line = f"{marker}{row['id']:<8} {magnet:<2} {row['seeders'] or 0:<6} {size:<10} {title}\n"
            style = "reverse" if index == self.selected_index else ""
            fragments.append((style, line))
        return fragments

    def _details_text(self) -> str:
        row = self._selected_row()
        if row is None:
            return "Нет данных.\n\ns синхр\n/ поиск\nq выход"
        files = self.storage.topic_files(row["id"]) if self.storage else []
        file_preview = "\n".join(f"- {item.path} ({item.size_text or '-'})" for item in files[:8])
        magnet = "yes" if row["magnet"] else "no"
        description = _truncate((row["description"] or "").replace("\n", " "), 500)
        return (
            f"{row['title']}\n\n"
            f"id: {row['id']}\n"
            f"forum: {row['forum_title'] or '-'}\n"
            f"seeds: {row['seeders'] or 0}  leech: {row['leechers'] or 0}\n"
            f"size: {row['size_text'] or '-'}\n"
            f"date: {row['registered_at'] or '-'}\n"
            f"magnet: {magnet}\n\n"
            f"files:\n{file_preview or '-'}\n\n"
            f"{description}"
        )

    def _log_text(self) -> str:
        return "\n".join(self.logs[-8:])

    def _footer_text(self) -> str:
        if self._search_has_focus():
            return "enter применить  esc назад"
        return "q выход  / поиск  s синхр  r обновить  o сортировка  d порядок  g раздел  c сброс"

    def _selected_row(self) -> Any | None:
        if not self.rows:
            return None
        return self.rows[self.selected_index]

    def _update_stats(self) -> None:
        if not self.storage:
            return
        self.stats = self.storage.stats()
        self._load_categories()

    def _load_categories(self) -> None:
        if not self.storage:
            return
        current = self.categories[self.category_index] if self.categories else "Все"
        categories = ["Все"] + [row["category"] for row in self.storage.list_categories()]
        self.categories = categories
        self.category_index = categories.index(current) if current in categories else 0

    def _invalidate(self) -> None:
        if self.app is None:
            return
        try:
            get_app().invalidate()
        except Exception:
            self.app.invalidate()


def _truncate(value: str, length: int) -> str:
    return value if len(value) <= length else value[: max(0, length - 1)] + "…"


def _short_http_error(exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    if status_code == 521:
        return "HTTP 521"
    if status_code == 429:
        return "HTTP 429: rate limit"
    return f"HTTP {status_code}"


def _clean_log(message: str) -> str:
    message = re.sub(r"https?://\S+", "", message)
    message = message.replace("⏳", "").replace("⚠️", "").replace("🌐", "").replace("🗺️", "")
    message = re.sub(r"\s+", " ", message).strip()
    if "521" in message:
        return "HTTP 521"
    if "429" in message:
        return "HTTP 429: rate limit"
    return message
