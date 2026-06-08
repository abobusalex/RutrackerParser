from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Label, Log, Static

from .config import BASE_URL, default_db_path
from .crawler import RutrackerCrawler, SyncOptions, options_from_env
from .parser import parse_size
from .storage import Storage


class RutrackerApp(App):
    CSS = """
    Screen {
        background: #10131a;
    }

    #top {
        height: 4;
        padding: 1 2;
        background: #171d27;
        border: tall #5af78e;
    }

    #hint {
        color: #d7dae0;
    }

    #search_bar {
        height: 3;
        padding: 0 1;
        background: #111721;
    }

    #query {
        width: 1fr;
    }

    #main {
        height: 1fr;
    }

    #results {
        width: 2fr;
        border: round #57c7ff;
    }

    #details {
        width: 1fr;
        border: round #ffb86c;
        padding: 1;
    }

    #log {
        height: 7;
        border: round #bd93f9;
    }

    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "focus_table", "Back"),
        ("/", "focus_search", "Search"),
        ("enter", "open_selected", "Open"),
        ("r", "refresh", "Refresh"),
        ("s", "sync", "Sync"),
        ("m", "toggle_magnet", "Magnet"),
        ("f", "toggle_seed_filter", "Seeds"),
        ("c", "clear_filters", "Clear"),
    ]

    def __init__(self, db_path: Path = default_db_path(), base_url: str = BASE_URL):
        super().__init__()
        self.db_path = db_path
        self.base_url = base_url
        self.storage: Storage | None = None
        self.magnet_only = False
        self.min_seeders: int | None = None
        self.max_size_text = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="top"):
            yield Label("🧲 RuTracker TUI", id="title")
            yield Label(
                "↑/↓ выбрать · Enter детали · / поиск · s синхра · m magnet · f сиды · c сброс · q выход",
                id="hint",
            )
        with Horizontal(id="search_bar", classes="hidden"):
            yield Input(placeholder="Поиск по названию и описанию; Enter применить, Esc назад", id="query")
        with Horizontal(id="main"):
            yield DataTable(id="results")
            yield Static("База пустая. Нажми s для синхронизации или / для поиска после загрузки.", id="details")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.storage = Storage(self.db_path)
        table = self.query_one("#results", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("ID", "🧲", "Название", "🌱", "🪱", "📦", "Форум")
        self._refresh_results()
        table.focus()
        self._log("Готово. Управление стрелками уже активно.")

    def on_unmount(self) -> None:
        if self.storage:
            self.storage.close()

    @on(Input.Submitted, "#query")
    def query_submitted(self, _: Input.Submitted) -> None:
        self._refresh_results()
        self.action_focus_table()

    @on(DataTable.RowHighlighted, "#results")
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._show_row(event.row_key)

    @on(DataTable.RowSelected, "#results")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        self._show_row(event.row_key)

    def action_focus_search(self) -> None:
        self.query_one("#search_bar").remove_class("hidden")
        self.query_one("#query", Input).focus()

    def action_focus_table(self) -> None:
        self.query_one("#search_bar").add_class("hidden")
        self.query_one("#results", DataTable).focus()

    def action_open_selected(self) -> None:
        table = self.query_one("#results", DataTable)
        if table.has_focus:
            self._show_row(table.cursor_row_key)

    def action_refresh(self) -> None:
        self._refresh_results()
        self.action_focus_table()

    def action_toggle_magnet(self) -> None:
        self.magnet_only = not self.magnet_only
        self._log(f"Фильтр magnet: {'включён' if self.magnet_only else 'выключен'}")
        self._refresh_results()

    def action_toggle_seed_filter(self) -> None:
        if self.min_seeders is None:
            self.min_seeders = 1
        elif self.min_seeders == 1:
            self.min_seeders = 10
        elif self.min_seeders == 10:
            self.min_seeders = 100
        else:
            self.min_seeders = None
        label = "любой" if self.min_seeders is None else str(self.min_seeders)
        self._log(f"Минимум сидов: {label}")
        self._refresh_results()

    def action_clear_filters(self) -> None:
        self.magnet_only = False
        self.min_seeders = None
        self.max_size_text = ""
        self.query_one("#query", Input).value = ""
        self._log("Фильтры сброшены")
        self._refresh_results()

    def action_sync(self) -> None:
        self.run_worker(self._sync(), exclusive=True, name="sync")

    async def _sync(self) -> None:
        self._log("Запускаю синхронизацию. Если сайт лежит — TUI не упадёт.")
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
            log=self._log,
        )
        try:
            await crawler.run()
            self._log("Синхронизация завершена")
        except Exception as exc:
            self._log(f"Синхронизация остановлена без падения TUI: {type(exc).__name__}: {exc}")
        finally:
            await crawler.close()
            self._refresh_results()
            self.action_focus_table()

    def _refresh_results(self) -> None:
        if not self.storage:
            return
        query = self.query_one("#query", Input).value
        max_size = parse_size(self.max_size_text)[1] if self.max_size_text else None
        rows = self.storage.search_topics(
            query=query,
            min_seeders=self.min_seeders,
            max_size_bytes=max_size,
            magnet_only=self.magnet_only,
            limit=300,
        )
        table = self.query_one("#results", DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                str(row["id"]),
                "🧲" if row["magnet"] else "·",
                row["title"],
                str(row["seeders"] or 0),
                str(row["leechers"] or 0),
                row["size_text"] or "—",
                row["forum_title"] or "—",
                key=str(row["id"]),
            )
        if rows:
            table.move_cursor(row=0, animate=False)
            self._show_topic(rows[0]["id"])
        else:
            self.query_one("#details", Static).update(self._empty_details())
        self._write_stats()

    def _show_row(self, row_key: object | None) -> None:
        if row_key is None:
            return
        try:
            topic_id = int(str(row_key))
        except ValueError:
            return
        self._show_topic(topic_id)

    def _show_topic(self, topic_id: int) -> None:
        if not self.storage:
            return
        topic = self.storage.get_topic(topic_id)
        if not topic:
            return
        files = self.storage.topic_files(topic_id)
        file_preview = "\n".join(f"  • {item.path} · {item.size_text or '—'}" for item in files[:10])
        ascii_preview = topic["first_image_ascii"] or "ASCII-слепка пока нет"
        details = (
            f"🧲 {topic['title']}\n\n"
            f"ID: {topic['id']}\n"
            f"Форум: {topic['forum_title'] or '—'}\n"
            f"Сиды: {topic['seeders'] or 0} · Личи: {topic['leechers'] or 0}\n"
            f"Размер: {topic['size_text'] or '—'}\n"
            f"Дата: {topic['registered_at'] or '—'}\n"
            f"Magnet: {'есть' if topic['magnet'] else 'нет'}\n\n"
            f"Файлы:\n{file_preview or '  —'}\n\n"
            f"ASCII:\n{ascii_preview}"
        )
        self.query_one("#details", Static).update(details)

    def _empty_details(self) -> str:
        filters = []
        if self.magnet_only:
            filters.append("только magnet")
        if self.min_seeders is not None:
            filters.append(f"сидов >= {self.min_seeders}")
        suffix = f"\nФильтры: {', '.join(filters)}" if filters else ""
        return (
            "Ничего не найдено.\n\n"
            "Стрелки работают по таблице, когда там есть строки.\n"
            "Нажми s для синхронизации, / для поиска, c для сброса фильтров."
            f"{suffix}"
        )

    def _write_stats(self) -> None:
        if not self.storage:
            return
        stats = self.storage.stats()
        self._log(
            f"Форумы {stats['forums']} · Темы {stats['topics']} · "
            f"Разобрано {stats['crawled_topics']} · Магниты {stats['magnets']} · Файлы {stats['files']}"
        )

    def _log(self, message: str) -> None:
        try:
            self.query_one("#log", Log).write_line(message)
        except Exception:
            pass
