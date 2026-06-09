from __future__ import annotations

import asyncio
import math
import re
import time
from pathlib import Path
from typing import Any

import httpx
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from .config import BASE_URL, default_db_path
from .crawler import RutrackerCrawler, SyncOptions, options_from_env
from .storage import SORTS, Storage


MAX_ROWS = 500
PAGE_SIZE = 18
SPINNER = "|/-\\"
ALL_CATEGORIES = "Все"
CATEGORY_EMOJI = {
    ALL_CATEGORIES: "🌐",
    "Фильмы": "🎬",
    "Аниме": "🎌",
    "Сериалы": "📺",
    "Игры": "🎮",
    "Книги и журналы": "📚",
    "Музыка": "🎵",
    "Обучение": "🎓",
    "Прочее": "🧩",
    "Софт": "💾",
    "Спорт": "🏅",
}
PROGRESS_RE = re.compile(
    r"progress (?P<done>\d+)/(?P<total>\d+) (?P<percent>\d+(?:\.\d+)?)% \| "
    r"(?P<branch>.*?) \| page (?P<page>\d+) \| (?P<state>.*?) \| elapsed (?P<elapsed>\d{2}:\d{2}:\d{2})"
)
TOPIC_PROGRESS_RE = re.compile(
    r"topic-progress active=(?P<active>\d+) queued=(?P<queued>\d+) "
    r"saved=(?P<saved>\d+) skipped=(?P<skipped>\d+) failed=(?P<failed>\d+)"
)
MONTH_WORDS_RE = (
    "янв|января|фев|февраля|мар|марта|апр|апреля|мая|май|июн|июня|июл|июля|"
    "авг|августа|сен|сентября|окт|октября|ноя|ноября|дек|декабря|"
    "jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
    "aug|august|sep|september|oct|october|nov|november|dec|december"
)


class RutrackerApp:
    def __init__(self, db_path: Path = default_db_path(), base_url: str = BASE_URL):
        self.db_path = db_path
        self.base_url = base_url
        self.storage: Storage | None = None
        self.rows: list[Any] = []
        self.categories: list[dict[str, Any]] = [{"category": ALL_CATEGORIES, "topics": 0, "forums": 0}]
        self.category_index = 0
        self.selected_index = 0
        self.active_pane = "categories"
        self.query = ""
        self.sort_codes = ["10", "4", "7", "11", "2", "1"]
        self.sort_code = "10"
        self.sort_desc = True
        self.logs: list[str] = []
        self.stats = {"forums": 0, "topics": 0, "crawled_topics": 0, "magnets": 0, "files": 0}
        self.syncing = False
        self.spinner_index = 0
        self.sync_percent = 0.0
        self.sync_elapsed = "00:00:00"
        self.sync_branch = ""
        self.sync_state = ""
        self.sync_started_at: float | None = None
        self.sync_workers = 8
        self.sync_active = 0
        self.sync_queued = 0
        self.sync_saved = 0
        self.sync_skipped = 0
        self.sync_failed = 0
        self._last_live_refresh = 0.0
        self.fullscreen = False
        self.detail_scroll = 0
        self.search_field = TextArea(
            height=1,
            prompt="🔎 search> ",
            multiline=False,
            accept_handler=self._submit_search,
        )
        self.category_control = FormattedTextControl(self._categories_text, focusable=True)
        self.topic_control = FormattedTextControl(self._topics_text, focusable=True)
        self.detail_control = FormattedTextControl(self._details_text, focusable=True)
        self.fullscreen_control = FormattedTextControl(self._full_details_text, focusable=True)
        self.banner_control = FormattedTextControl(self._selected_banner_text)
        self.app: Application[None] | None = None

    @property
    def selected_category(self) -> str | None:
        if not self.categories:
            return None
        category = self.categories[self.category_index]["category"]
        return None if category == ALL_CATEGORIES else category

    @property
    def current_page(self) -> int:
        return self.selected_index // PAGE_SIZE + 1 if self.rows else 0

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(len(self.rows) / PAGE_SIZE))

    def run(self) -> None:
        self.storage = Storage(self.db_path)
        try:
            self.refresh_results(reset_selection=True)
            self._build_application().run()
        finally:
            if self.storage:
                self.storage.close()

    def refresh_results(self, reset_selection: bool = False) -> None:
        if not self.storage:
            return
        self._update_stats()
        self.rows = self.storage.search_topics(
            query=self.query,
            category=self.selected_category,
            magnet_only=True,
            sort_code=self.sort_code,
            sort_desc=self.sort_desc,
            limit=MAX_ROWS,
        )
        if reset_selection:
            self.selected_index = 0
        self.selected_index = min(self.selected_index, max(0, len(self.rows) - 1))
        self._invalidate()

    def move_selection(self, delta: int) -> None:
        if self.active_pane == "categories":
            self.move_category(delta)
            return
        self.move_topic(delta)

    def move_category(self, delta: int) -> None:
        if not self.categories:
            return
        self.category_index = max(0, min(len(self.categories) - 1, self.category_index + delta))
        self.refresh_results(reset_selection=True)

    def move_topic(self, delta: int) -> None:
        if not self.rows:
            self.selected_index = 0
            return
        self.selected_index = max(0, min(len(self.rows) - 1, self.selected_index + delta))
        self.detail_scroll = 0
        self._invalidate()

    def switch_pane(self, pane: str) -> None:
        self.active_pane = pane
        if self.app:
            self.app.layout.focus(self.category_control if pane == "categories" else self.topic_control)
        self._invalidate()

    def cycle_sort(self) -> None:
        index = self.sort_codes.index(self.sort_code)
        self.sort_code = self.sort_codes[(index + 1) % len(self.sort_codes)]
        self.log(f"sort: {SORTS[self.sort_code][1]}")
        self.refresh_results(reset_selection=True)

    def toggle_sort_direction(self) -> None:
        self.sort_desc = not self.sort_desc
        self.log(f"order: {'desc' if self.sort_desc else 'asc'}")
        self.refresh_results(reset_selection=True)

    def clear_filters(self) -> None:
        self.query = ""
        self.search_field.text = ""
        self.sort_code = "10"
        self.sort_desc = True
        self.category_index = 0
        self.log("reset")
        self.refresh_results(reset_selection=True)

    def open_fullscreen(self) -> None:
        if self._selected_row() is None:
            return
        self.fullscreen = True
        self.detail_scroll = 0
        if self.app:
            self.app.layout.focus(self.fullscreen_control)
        self._invalidate()

    def close_fullscreen(self) -> None:
        self.fullscreen = False
        self.detail_scroll = 0
        if self.app:
            self.app.layout.focus(self.topic_control)
        self._invalidate()

    def scroll_details(self, delta: int) -> None:
        lines = self._selected_details_text(full=True).splitlines()
        self.detail_scroll = max(0, min(max(0, len(lines) - 1), self.detail_scroll + delta))
        self._invalidate()

    def log(self, message: str) -> None:
        self._apply_progress(message)
        clean_message = _clean_log(message)
        if clean_message:
            self.logs.append(clean_message)
            self.logs = self.logs[-6:]
            self._invalidate()

    def _build_application(self, output: Any | None = None, input: Any | None = None) -> Application[None]:
        normal_body = VSplit(
            [
                Window(self.category_control, width=30, wrap_lines=False),
                Window(width=1, char="│"),
                Window(self.topic_control, wrap_lines=False),
                Window(width=1, char="│"),
                Window(self.detail_control, wrap_lines=True, width=56),
            ]
        )
        body = HSplit(
            [
                ConditionalContainer(
                    normal_body,
                    filter=Condition(lambda: not self.fullscreen),
                ),
                ConditionalContainer(
                    Window(self.fullscreen_control, wrap_lines=False),
                    filter=Condition(lambda: self.fullscreen),
                ),
            ]
        )
        root = HSplit(
            [
                Window(FormattedTextControl(self._header_text), height=3),
                self.search_field,
                Window(height=1, char="─"),
                Window(self.banner_control, height=2, wrap_lines=False),
                Window(height=1, char="─"),
                body,
                Window(height=1, char="─"),
                Window(FormattedTextControl(self._log_text), height=6, wrap_lines=True),
                Window(FormattedTextControl(self._footer_text), height=1),
            ]
        )
        layout = Layout(root, focused_element=self.category_control)
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
        normal_mode = Condition(lambda: self._normal_hotkeys_enabled() and not self.fullscreen)
        fullscreen_mode = Condition(lambda: self._normal_hotkeys_enabled() and self.fullscreen)
        search_mode = Condition(self._search_has_focus)

        @bindings.add("c-c")
        def _(event: Any) -> None:
            event.app.exit()

        @bindings.add("q", filter=normal_mode)
        def _(event: Any) -> None:
            event.app.exit()

        @bindings.add("q", filter=fullscreen_mode)
        def _(event: Any) -> None:
            event.app.exit()

        @bindings.add("up", filter=normal_mode)
        def _(event: Any) -> None:
            self.move_selection(-1)

        @bindings.add("down", filter=normal_mode)
        def _(event: Any) -> None:
            self.move_selection(1)

        @bindings.add("pageup", filter=normal_mode)
        def _(event: Any) -> None:
            self.move_selection(-PAGE_SIZE)

        @bindings.add("pagedown", filter=normal_mode)
        def _(event: Any) -> None:
            self.move_selection(PAGE_SIZE)

        @bindings.add("up", filter=fullscreen_mode)
        def _(event: Any) -> None:
            self.scroll_details(-1)

        @bindings.add("down", filter=fullscreen_mode)
        def _(event: Any) -> None:
            self.scroll_details(1)

        @bindings.add("pageup", filter=fullscreen_mode)
        def _(event: Any) -> None:
            self.scroll_details(-PAGE_SIZE)

        @bindings.add("pagedown", filter=fullscreen_mode)
        def _(event: Any) -> None:
            self.scroll_details(PAGE_SIZE)

        @bindings.add("left", filter=normal_mode)
        def _(event: Any) -> None:
            self.switch_pane("categories")

        @bindings.add("right", filter=normal_mode)
        def _(event: Any) -> None:
            self.switch_pane("topics")

        @bindings.add("enter", filter=normal_mode)
        def _(event: Any) -> None:
            if self.active_pane == "categories":
                self.switch_pane("topics")
            else:
                self.open_fullscreen()

        @bindings.add("enter", filter=fullscreen_mode)
        def _(event: Any) -> None:
            self.close_fullscreen()

        @bindings.add("v", filter=normal_mode)
        def _(event: Any) -> None:
            self.open_fullscreen()

        @bindings.add("v", filter=fullscreen_mode)
        def _(event: Any) -> None:
            self.close_fullscreen()

        @bindings.add("/", filter=normal_mode)
        def _(event: Any) -> None:
            event.app.layout.focus(self.search_field)

        @bindings.add("escape", filter=search_mode)
        def _(event: Any) -> None:
            self.switch_pane("topics")

        @bindings.add("escape", filter=fullscreen_mode)
        def _(event: Any) -> None:
            self.close_fullscreen()

        @bindings.add("r", filter=normal_mode)
        def _(event: Any) -> None:
            self.refresh_results()

        @bindings.add("o", filter=normal_mode)
        def _(event: Any) -> None:
            self.cycle_sort()

        @bindings.add("d", filter=normal_mode)
        def _(event: Any) -> None:
            self.toggle_sort_direction()

        @bindings.add("c", filter=normal_mode)
        def _(event: Any) -> None:
            self.clear_filters()

        @bindings.add("s", filter=normal_mode)
        def _(event: Any) -> None:
            if not self.syncing:
                event.app.create_background_task(self._sync())

        return bindings

    def _submit_search(self, _: Any) -> bool:
        self.query = self.search_field.text.strip()
        self.refresh_results(reset_selection=True)
        self.switch_pane("topics")
        return True

    async def _sync(self) -> None:
        self.syncing = True
        self.sync_started_at = time.monotonic()
        self._last_live_refresh = 0.0
        self.sync_percent = 0.0
        self.sync_branch = ""
        self.sync_state = "starting"
        self.sync_active = 0
        self.sync_queued = 0
        self.sync_saved = 0
        self.sync_skipped = 0
        self.sync_failed = 0
        self.log("sync started")
        animation_task = asyncio.create_task(self._animate_sync())
        options = options_from_env(self.db_path, self.base_url, workers=self.sync_workers, delay=0.7)
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
            animation_task.cancel()
            await asyncio.gather(animation_task, return_exceptions=True)
            await crawler.close()
            self.syncing = False
            self.refresh_results()

    async def _animate_sync(self) -> None:
        while self.syncing:
            self.spinner_index = (self.spinner_index + 1) % len(SPINNER)
            if self.sync_started_at is not None:
                self.sync_elapsed = _format_elapsed(int(time.monotonic() - self.sync_started_at))
            now = time.monotonic()
            if now - self._last_live_refresh >= 1.0:
                self._last_live_refresh = now
                self.refresh_results()
            self._invalidate()
            await asyncio.sleep(0.12)

    def _search_has_focus(self) -> bool:
        if self.app is None:
            return False
        try:
            return self.app.layout.has_focus(self.search_field)
        except Exception:
            return False

    def _normal_hotkeys_enabled(self) -> bool:
        return not self._search_has_focus()

    def _header_text(self) -> HTML:
        if self.syncing:
            spinner = SPINNER[self.spinner_index]
            branch = self.sync_branch or "index"
            return HTML(
                f"<b>RuTracker</b>  🌊 {spinner} {self.sync_percent:5.1f}% {_progress_bar(self.sync_percent)}  "
                f"elapsed {self.sync_elapsed}\n"
                f"📚 {branch}\n"
                f"⚙️ {self.sync_state} | 🧵 {self.sync_active}/{self.sync_workers} | "
                f"📥 {self.sync_queued} | ✅ {self.sync_saved} | ⏭ {self.sync_skipped} | ⚠ {self.sync_failed} | "
                f"🧲 {self.stats['magnets']} | 📁 {self.stats['files']}"
            )
        category = self.categories[self.category_index]["category"] if self.categories else ALL_CATEGORIES
        filters = []
        if self.query:
            filters.append(f"🔎 query={self.query}")
        filters.append(f"📈 sort={SORTS[self.sort_code][1]}")
        filters.append("desc" if self.sort_desc else "asc")
        return HTML(
            f"<b>RuTracker</b>  📚 category {self.category_index + 1}/{len(self.categories)}: {category}  |  "
            f"page {self.current_page}/{self.total_pages}  |  rows {len(self.rows)}\n"
            f"{' | '.join(filters)}\n"
            f"🧭 active: {'categories' if self.active_pane == 'categories' else 'topics'}"
        )

    def _selected_banner_text(self) -> str:
        row = self._selected_row()
        if row is None:
            return "🎬 выбери раздачу\n🧲 magnet появится здесь"
        return f"{self._category_emoji(row['forum_category'])} {row['title']}\n🧲 {row['magnet'] or '-'}"

    def _categories_text(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = [("class:header", "№  Категория              ∑\n")]
        for index, item in enumerate(self.categories):
            marker = ">" if index == self.category_index else " "
            title = _truncate(f"{self._category_emoji(item['category'])} {item['category']}", 19)
            count = item.get("topics", 0)
            line = f"{marker}{index + 1:02d} {title:<19} {count:>6}\n"
            style = "reverse" if self.active_pane == "categories" and index == self.category_index else ""
            fragments.append((style, line))
        return fragments

    def _topics_text(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = [("class:header", "! Seeds  Size       Title\n")]
        if not self.rows:
            fragments.append(("", "Нет magnet-раздач. Нажми s для синхронизации.\n"))
            return fragments
        start = (self.current_page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(self.rows))
        for index in range(start, end):
            row = self.rows[index]
            marker = ">" if index == self.selected_index else " "
            sticky = "!" if row["is_sticky"] else " "
            title = _truncate(row["title"], 72)
            size = _truncate(row["size_text"] or "-", 10)
            line = f"{marker}{sticky:<2} {row['seeders'] or 0:<6} {size:<10} {title}\n"
            style = "reverse" if self.active_pane == "topics" and index == self.selected_index else ""
            fragments.append((style, line))
        return fragments

    def _details_text(self) -> str:
        return self._selected_details_text(full=False)

    def _full_details_text(self) -> str:
        lines = self._selected_details_text(full=True).splitlines()
        if not lines:
            return ""
        return "\n".join(lines[self.detail_scroll :])

    def _selected_details_text(self, full: bool) -> str:
        row = self._selected_row()
        if row is None:
            return "Нет magnet-раздач.\n\ns синхронизация\n/ поиск\nq выход"
        files = self.storage.topic_files(row["id"]) if self.storage else []
        file_limit = len(files) if full else 8
        file_preview = "\n".join(f"- {item.path} ({item.size_text or '-'})" for item in files[:file_limit])
        description_raw = (row["description"] or "").strip()
        description = description_raw if full else _truncate(description_raw.replace("\n", " "), 420)
        date = _clean_date(row["registered_at"])
        ascii_art = (row["first_image_ascii"] or "").strip()
        if ascii_art and not full:
            ascii_art = "\n".join(ascii_art.splitlines()[:10])
        parts = [
            row["url"],
            (
                f"🌱 {row['seeders'] or 0} | "
                f"🪱 {row['leechers'] or 0} | "
                f"📦 {row['size_text'] or '-'} | "
                f"📅 {date or '-'} | "
                f"📌 {'yes' if row['is_sticky'] else 'no'}"
            ),
            "",
        ]
        if ascii_art:
            parts.extend(["ascii:", ascii_art, ""])
        parts.extend(["files:", file_preview or "-", ""])
        if description:
            parts.append(description)
        return "\n".join(parts)

    def _log_text(self) -> str:
        return "\n".join(self.logs[-6:])

    def _footer_text(self) -> str:
        if self._search_has_focus():
            return "enter применить  esc назад"
        section = f"раздел {self.category_index + 1}/{len(self.categories)}"
        page = f"стр {self.current_page}/{self.total_pages}"
        pos = f"{self.selected_index + 1 if self.rows else 0}/{len(self.rows)}"
        if self.fullscreen:
            return f"{section}  {page}  pos {pos}  ↑/↓ scroll  pgup/pgdn  enter/esc назад  q выход"
        return f"{section}  {page}  pos {pos}  ←/→ панель  ↑/↓ выбрать  enter открыть  / поиск  s sync  o сорт  d порядок  c сброс  q выход"

    def _selected_row(self) -> Any | None:
        if not self.rows:
            return None
        return self.rows[self.selected_index]

    def _category_emoji(self, category: str | None) -> str:
        return CATEGORY_EMOJI.get(category or "", "🧲")

    def _update_stats(self) -> None:
        if not self.storage:
            return
        self.stats = self.storage.stats()
        self._load_categories()

    def _load_categories(self) -> None:
        if not self.storage:
            return
        current = self.categories[self.category_index]["category"] if self.categories else ALL_CATEGORIES
        categories = [
            {"category": ALL_CATEGORIES, "forums": self.stats["forums"], "topics": self.stats["magnets"]}
        ] + [dict(row) for row in self.storage.list_categories()]
        self.categories = categories
        self.category_index = next(
            (index for index, item in enumerate(categories) if item["category"] == current),
            0,
        )

    def _apply_progress(self, message: str) -> None:
        match = PROGRESS_RE.search(message)
        if match:
            self.sync_percent = float(match.group("percent"))
            self.sync_elapsed = match.group("elapsed")
            self.sync_branch = match.group("branch")
            self.sync_state = f"page {match.group('page')} | {match.group('state')}"
            return
        topic_match = TOPIC_PROGRESS_RE.search(message)
        if topic_match:
            self.sync_active = int(topic_match.group("active"))
            self.sync_queued = int(topic_match.group("queued"))
            self.sync_saved = int(topic_match.group("saved"))
            self.sync_skipped = int(topic_match.group("skipped"))
            self.sync_failed = int(topic_match.group("failed"))

    def _invalidate(self) -> None:
        if self.app is None:
            return
        try:
            get_app().invalidate()
        except Exception:
            self.app.invalidate()


def _truncate(value: str, length: int) -> str:
    return value if len(value) <= length else value[: max(0, length - 1)] + "…"


def _progress_bar(percent: float, width: int = 24) -> str:
    filled = max(0, min(width, int(width * percent / 100)))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _format_elapsed(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _short_http_error(exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    if status_code == 521:
        return "HTTP 521"
    if status_code == 429:
        return "HTTP 429: rate limit"
    return f"HTTP {status_code}"


def _clean_date(value: str | None) -> str | None:
    if not value:
        return None
    if re.search(r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:\d{2}|\d{4})\b", value):
        return value
    if re.search(rf"\b(?:0?[1-9]|[12]\d|3[01])\s+(?:{MONTH_WORDS_RE})\s+\d{{4}}\b", value, re.IGNORECASE):
        return value
    return None


def _clean_log(message: str) -> str:
    progress_match = PROGRESS_RE.search(message)
    if progress_match:
        return (
            f"{progress_match.group('done')}/{progress_match.group('total')} "
            f"{progress_match.group('percent')}% | {progress_match.group('branch')} | "
            f"{progress_match.group('state')}"
        )
    message = re.sub(r"https?://\S+", "", message)
    message = message.replace("⏳", "").replace("⚠️", "").replace("🌐", "").replace("🗺️", "")
    message = re.sub(r"\s+", " ", message).strip()
    if "521" in message:
        return "HTTP 521"
    if "429" in message:
        return "HTTP 429: rate limit"
    return message
