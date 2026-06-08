from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Log, Static

from .config import BASE_URL, default_db_path
from .crawler import RutrackerCrawler, SyncOptions, options_from_env
from .parser import parse_size
from .storage import Storage


class RutrackerApp(App):
    CSS = """
    Screen {
        background: #10131a;
    }

    #hero {
        height: 5;
        padding: 1 2;
        background: #1d2330;
        color: #f8f8f2;
        border: tall #5af78e;
    }

    #filters {
        height: 5;
        padding: 1;
        background: #151a23;
    }

    #results {
        height: 1fr;
        border: round #57c7ff;
    }

    #details {
        width: 44;
        border: round #ffb86c;
        padding: 1;
    }

    #log {
        height: 9;
        border: round #bd93f9;
    }

    Input {
        width: 1fr;
        margin-right: 1;
    }

    Button {
        margin-right: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("s", "sync", "Sync"),
        ("m", "toggle_magnet", "Magnet only"),
    ]

    def __init__(self, db_path: Path = default_db_path(), base_url: str = BASE_URL):
        super().__init__()
        self.db_path = db_path
        self.base_url = base_url
        self.storage: Storage | None = None
        self.magnet_only = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("🧲 RuTracker TUI  ·  🔎 ищи  🎚️ фильтруй  🌊 синхронизируй  ✨ живи красиво", id="hero")
        with Horizontal(id="filters"):
            yield Input(placeholder="🔎 Поиск: название, описание, релиз...", id="query")
            yield Input(placeholder="🌱 min сиды", id="min_seeders")
            yield Input(placeholder="📦 max размер, напр. 10 GB", id="max_size")
            yield Button("🔎 Найти", id="search", variant="primary")
            yield Button("🧲 Только magnet", id="magnet")
            yield Button("🌊 Синхра", id="sync", variant="success")
        with Horizontal():
            yield DataTable(id="results")
            yield Static("Выбери раздачу, и тут появятся детали 🪄", id="details")
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.storage = Storage(self.db_path)
        table = self.query_one("#results", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "🧲", "Название", "🌱", "🪱", "📦", "Форум")
        self._write_stats()
        self._refresh_results()

    def on_unmount(self) -> None:
        if self.storage:
            self.storage.close()

    @on(Input.Submitted)
    def input_submitted(self, _: Input.Submitted) -> None:
        self._refresh_results()

    @on(Button.Pressed, "#search")
    def search_pressed(self, _: Button.Pressed) -> None:
        self._refresh_results()

    @on(Button.Pressed, "#magnet")
    def magnet_pressed(self, _: Button.Pressed) -> None:
        self.action_toggle_magnet()

    @on(Button.Pressed, "#sync")
    def sync_pressed(self, _: Button.Pressed) -> None:
        self.action_sync()

    @on(DataTable.RowSelected)
    def row_selected(self, event: DataTable.RowSelected) -> None:
        if not self.storage:
            return
        table = self.query_one("#results", DataTable)
        row = table.get_row(event.row_key)
        topic_id = int(str(row[0]))
        direct = self.storage.get_topic(topic_id)
        files = self.storage.topic_files(topic_id)
        if not direct:
            return
        file_preview = "\n".join(f"  • {item.path} · {item.size_text or '—'}" for item in files[:12])
        ascii_preview = direct["first_image_ascii"] or "ASCII-слепка пока нет 🖼️"
        details = (
            f"🧲 {direct['title']}\n\n"
            f"🌱 Сиды: {direct['seeders'] or 0}  🪱 Личи: {direct['leechers'] or 0}\n"
            f"📦 Размер: {direct['size_text'] or '—'}\n"
            f"📅 Дата: {direct['registered_at'] or '—'}\n"
            f"🔗 Magnet: {'есть' if direct['magnet'] else 'нет'}\n\n"
            f"📁 Файлы:\n{file_preview or '  —'}\n\n"
            f"🖼️ ASCII:\n{ascii_preview}"
        )
        self.query_one("#details", Static).update(details)

    def action_refresh(self) -> None:
        self._refresh_results()

    def action_toggle_magnet(self) -> None:
        self.magnet_only = not self.magnet_only
        state = "включён" if self.magnet_only else "выключен"
        self._log(f"🧲 Фильтр magnet {state}")
        self._refresh_results()

    def action_sync(self) -> None:
        self.run_worker(self._sync(), exclusive=False, name="sync")

    async def _sync(self) -> None:
        self._log("🌊 Запускаю синхронизацию")
        options = options_from_env(self.db_path, self.base_url, workers=8, delay=0.7)
        crawler = RutrackerCrawler(
            SyncOptions(
                db_path=options.db_path,
                base_url=options.base_url,
                workers=options.workers,
                delay=options.delay,
                username=options.username,
                password=options.password,
            ),
            log=lambda message: self.call_later(self._log, message),
        )
        try:
            await crawler.run()
        except Exception as exc:
            self.call_later(self._log, f"⚠️ Синхронизация остановлена: {exc}")
        finally:
            await crawler.close()
        self.call_from_thread(self._refresh_results)

    def _refresh_results(self) -> None:
        if not self.storage:
            return
        query = self.query_one("#query", Input).value
        min_seeders_text = self.query_one("#min_seeders", Input).value.strip()
        max_size_text = self.query_one("#max_size", Input).value.strip()
        min_seeders = int(min_seeders_text) if min_seeders_text.isdigit() else None
        max_size = parse_size(max_size_text)[1] if max_size_text else None
        rows = self.storage.search_topics(
            query=query,
            min_seeders=min_seeders,
            max_size_bytes=max_size,
            magnet_only=self.magnet_only,
            limit=200,
        )
        table = self.query_one("#results", DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                str(row["id"]),
                "🧲" if row["magnet"] else "▫️",
                row["title"],
                str(row["seeders"] or 0),
                str(row["leechers"] or 0),
                row["size_text"] or "—",
                row["forum_title"] or "—",
            )
        self._write_stats()

    def _write_stats(self) -> None:
        if not self.storage:
            return
        stats = self.storage.stats()
        self._log(
            f"📊 Форумы {stats['forums']} · Темы {stats['topics']} · "
            f"Разобрано {stats['crawled_topics']} · Магниты {stats['magnets']} · Файлы {stats['files']}"
        )

    def _log(self, message: str) -> None:
        self.query_one("#log", Log).write_line(message)
