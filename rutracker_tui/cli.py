from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

from .config import BASE_URL, default_db_path
from .crawler import RutrackerCrawler, SyncOptions, options_from_env
from .parser import parse_size
from .storage import SORTS, Storage


STDOUT_ENCODING = sys.stdout.encoding or "utf-8"
UNICODE_STDOUT = "utf" in STDOUT_ENCODING.lower()
console = Console(emoji=UNICODE_STDOUT)


class SafeArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message: str, file: Any | None = None) -> None:
        if message:
            target = file or sys.stderr
            target.write(_safe_text(message))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"

    if command == "run":
        _run(args)
    elif command == "sync":
        if not asyncio.run(_sync(args, exit_on_error=False)):
            raise SystemExit(2)
    elif command == "search":
        _search(args)
    elif command == "show":
        _show(args)
    elif command == "files":
        _files(args)
    elif command == "magnet":
        _magnet(args)
    elif command == "forums":
        _forums(args)
    elif command == "stats":
        _stats(args)
    elif command == "doctor":
        asyncio.run(_doctor(args))
    elif command == "db-path":
        _print(str(args.db))


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="rutracker-tui",
        description="RuTracker TUI: локальный слепок форума, поиск, фильтры и синхронизация.",
    )
    _add_common_options(parser)
    _add_sync_options(parser)
    parser.add_argument("--no-auto-sync", action="store_true", help="Не запускать фоновый sync при пустой базе")
    parser.add_argument("--no-tui", action="store_true", help="Запустить sync без TUI")

    subparsers = parser.add_subparsers(dest="command", parser_class=SafeArgumentParser)

    run_parser = subparsers.add_parser("run", help="Открыть TUI; sync стартует внутри, если база пустая")
    _add_common_options(run_parser, suppress_defaults=True)
    _add_sync_options(run_parser, suppress_defaults=True)
    run_parser.add_argument(
        "--no-auto-sync",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Не запускать фоновый sync при пустой базе",
    )
    run_parser.add_argument(
        "--no-tui",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Запустить sync без TUI",
    )

    sync_parser = subparsers.add_parser("sync", help="Синхронизировать форум в локальную SQLite-базу")
    _add_common_options(sync_parser, suppress_defaults=True)
    _add_sync_options(sync_parser, suppress_defaults=True)

    search_parser = subparsers.add_parser("search", help="Искать по локальной базе")
    _add_common_options(search_parser, suppress_defaults=True)
    search_parser.add_argument("query", nargs="?", default="", help="Текст запроса")
    search_parser.add_argument("--min-seeders", type=int, help="Минимум сидов")
    search_parser.add_argument("--max-size", help="Максимальный размер, например 10 GB")
    search_parser.add_argument("--magnet-only", action="store_true", help="Показывать только темы с magnet")
    search_parser.add_argument(
        "-o",
        "--sort",
        choices=list(SORTS),
        default="1",
        help="Сортировка как на RuTracker: 1 дата, 2 название, 4 скачивания, 10 сиды, 11 личи, 7 размер",
    )
    search_parser.add_argument("--asc", action="store_true", help="Сортировать по возрастанию")
    search_parser.add_argument("--category", help="Крупная категория форума")
    search_parser.add_argument("--limit", type=int, default=30, help="Сколько результатов вывести")
    search_parser.add_argument("--json", action="store_true", help="Вывести JSON вместо таблицы")
    search_parser.add_argument("--offline", action="store_true", help="Не синхронизировать пустую базу перед поиском")

    show_parser = subparsers.add_parser("show", help="Показать карточку раздачи по topic id")
    _add_common_options(show_parser, suppress_defaults=True)
    show_parser.add_argument("topic_id", type=int)
    show_parser.add_argument("--json", action="store_true")

    files_parser = subparsers.add_parser("files", help="Показать файлы раздачи по topic id")
    _add_common_options(files_parser, suppress_defaults=True)
    files_parser.add_argument("topic_id", type=int)
    files_parser.add_argument("--json", action="store_true")

    magnet_parser = subparsers.add_parser("magnet", help="Напечатать magnet-ссылку по topic id")
    _add_common_options(magnet_parser, suppress_defaults=True)
    magnet_parser.add_argument("topic_id", type=int)

    forums_parser = subparsers.add_parser("forums", help="Показать индексированные форумы")
    _add_common_options(forums_parser, suppress_defaults=True)
    forums_parser.add_argument("--limit", type=int, default=50)
    forums_parser.add_argument("--json", action="store_true")

    stats_parser = subparsers.add_parser("stats", help="Статистика локального слепка")
    _add_common_options(stats_parser, suppress_defaults=True)
    stats_parser.add_argument("--json", action="store_true")

    doctor_parser = subparsers.add_parser("doctor", help="Проверить базу и доступность сайта")
    _add_common_options(doctor_parser, suppress_defaults=True)

    db_path_parser = subparsers.add_parser("db-path", help="Показать путь к SQLite-базе")
    _add_common_options(db_path_parser, suppress_defaults=True)

    return parser


def _run(args: argparse.Namespace) -> None:
    if args.no_tui:
        if _database_is_empty(args.db) and not args.no_auto_sync:
            asyncio.run(_sync(args, exit_on_error=False))
        _stats(args)
        return

    from .tui import RutrackerApp

    RutrackerApp(
        db_path=args.db,
        base_url=args.base_url,
        auto_sync=not args.no_auto_sync,
        sync_workers=args.workers,
        sync_delay=args.delay,
        max_forums=args.max_forums,
        max_topics=args.max_topics,
        include_images=not args.no_images,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
    ).run()


async def _sync(args: argparse.Namespace, exit_on_error: bool) -> bool:
    options = _sync_options(args)
    crawler = RutrackerCrawler(options, log=_print_log)
    try:
        await crawler.run()
        return True
    except httpx.HTTPStatusError as exc:
        _print(_friendly_http_error(exc))
        if exit_on_error:
            raise
        return False
    except httpx.HTTPError as exc:
        _print(f"network error: {_network_error_message(exc)}")
        if exit_on_error:
            raise
        return False
    finally:
        await crawler.close()


def _search(args: argparse.Namespace) -> None:
    if _database_is_empty(args.db) and not args.offline:
        _print("🔎 Локальная база пустая — запускаю первичную синхронизацию перед поиском.")
        asyncio.run(_sync(_search_sync_args(args), exit_on_error=False))

    max_size = parse_size(args.max_size)[1] if args.max_size else None
    storage = Storage(args.db)
    try:
        rows = storage.search_topics(
            query=args.query,
            min_seeders=args.min_seeders,
            max_size_bytes=max_size,
            magnet_only=args.magnet_only,
            category=args.category,
            sort_code=args.sort,
            sort_desc=not args.asc,
            limit=args.limit,
        )
        if args.json:
            _print_json([_row_dict(row) for row in rows])
            return
        table = Table(title="RuTracker локальный поиск")
        table.add_column("M")
        table.add_column("ID", justify="right")
        table.add_column("Название", overflow="fold")
        table.add_column("Seeds", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Категория", overflow="fold")
        table.add_column("Форум", overflow="fold")
        for row in rows:
            table.add_row(
                "yes" if row["magnet"] else "—",
                str(row["id"]),
                row["title"],
                str(row["seeders"] or 0),
                row["size_text"] or "—",
                row["forum_category"] or "—",
                row["forum_title"] or "—",
            )
        console.print(table)
    finally:
        storage.close()


def _show(args: argparse.Namespace) -> None:
    storage = Storage(args.db)
    try:
        topic = storage.get_topic(args.topic_id)
        if topic is None:
            _print(f"🕳️ Topic {args.topic_id} не найден в локальной базе.")
            return
        files = storage.topic_files(args.topic_id)
        if args.json:
            payload = _row_dict(topic)
            payload["files"] = [asdict(item) for item in files]
            _print_json(payload)
            return
        _print(f"🧲 {topic['title']}")
        _print(f"ID: {topic['id']} | Форум: {topic['forum_title'] or '—'}")
        _print(f"🌱 Сиды: {topic['seeders'] or 0} | 🪱 Личи: {topic['leechers'] or 0}")
        _print(f"📦 Размер: {topic['size_text'] or '—'} | 📅 Дата: {topic['registered_at'] or '—'}")
        _print(f"🔗 Magnet: {topic['magnet'] or '—'}")
        _print(f"📁 Файлов: {len(files)}")
        if topic["first_image_ascii"]:
            _print("\n🖼️ ASCII-слепок:\n" + topic["first_image_ascii"])
    finally:
        storage.close()


def _files(args: argparse.Namespace) -> None:
    storage = Storage(args.db)
    try:
        files = storage.topic_files(args.topic_id)
        if args.json:
            _print_json([asdict(item) for item in files])
            return
        for item in files:
            _print(f"{item.order_index + 1:04d}. {item.path} — {item.size_text or '—'}")
    finally:
        storage.close()


def _magnet(args: argparse.Namespace) -> None:
    storage = Storage(args.db)
    try:
        topic = storage.get_topic(args.topic_id)
        if topic is None or not topic["magnet"]:
            raise SystemExit(f"Magnet для topic {args.topic_id} не найден.")
        _print(topic["magnet"])
    finally:
        storage.close()


def _forums(args: argparse.Namespace) -> None:
    storage = Storage(args.db)
    try:
        rows = storage.list_forums(args.limit)
        if args.json:
            _print_json([_row_dict(row) for row in rows])
            return
        table = Table(title=_safe_text("🗺️ Индексированные форумы"))
        table.add_column("ID", justify="right")
        table.add_column("Название", overflow="fold")
        table.add_column("Категория", overflow="fold")
        table.add_column("Тем")
        table.add_column("В базе")
        for row in rows:
            table.add_row(
                str(row["id"]),
                row["title"],
                row["category"] or "—",
                str(row["topics_count"] or "—"),
                str(row["indexed_topics"] or 0),
            )
        console.print(table)
    finally:
        storage.close()


def _stats(args: argparse.Namespace) -> None:
    storage = Storage(args.db)
    try:
        stats = storage.stats()
        if args.json:
            _print_json(stats)
            return
        for key, value in stats.items():
            console.print(f"{key}: [bold cyan]{value}[/bold cyan]")
    finally:
        storage.close()


async def _doctor(args: argparse.Namespace) -> None:
    _stats(argparse.Namespace(db=args.db, json=False))
    _print(f"💾 DB: {args.db}")
    timeout = httpx.Timeout(20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(args.base_url.rstrip("/") + "/index.php")
            _print(f"🌐 {args.base_url} -> HTTP {response.status_code}")
            if response.status_code == 521:
                _print("HTTP 521: index недоступен")
    except httpx.HTTPError as exc:
        _print(f"network error: {_network_error_message(exc)}")


def _sync_options(args: argparse.Namespace) -> SyncOptions:
    options = options_from_env(args.db, args.base_url, args.workers, args.delay)
    return SyncOptions(
        db_path=options.db_path,
        base_url=options.base_url,
        workers=options.workers,
        delay=options.delay,
        max_forums=args.max_forums,
        max_topics=args.max_topics,
        include_images=not args.no_images,
        username=options.username,
        password=options.password,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
    )


def _search_sync_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        db=args.db,
        base_url=args.base_url,
        workers=4,
        delay=1.0,
        max_forums=None,
        max_topics=None,
        no_images=False,
        retries=3,
        retry_backoff=2.0,
    )


def _database_is_empty(db_path: Path) -> bool:
    storage = Storage(db_path)
    try:
        return storage.is_empty()
    finally:
        storage.close()


def _friendly_http_error(exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    url = str(exc.request.url)
    if status_code == 521:
        return f"HTTP 521: index недоступен ({url})"
    if status_code == 429:
        return f"HTTP 429: rate limit ({url})"
    return f"⚠️ HTTP {status_code} при загрузке {url}: {exc}"


def _network_error_message(exc: httpx.HTTPError) -> str:
    details = str(exc).strip()
    return f"{type(exc).__name__}: {details}" if details else type(exc).__name__


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def _print_json(value: Any) -> None:
    _print(json.dumps(value, ensure_ascii=False, indent=2))


def _safe_text(value: str) -> str:
    return value.encode(STDOUT_ENCODING, errors="replace").decode(STDOUT_ENCODING)


def _print(message: str) -> None:
    console.print(_safe_text(message))


def _print_log(message: str) -> None:
    _print(message)


def _add_common_options(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    db_default: Path | str = argparse.SUPPRESS if suppress_defaults else default_db_path()
    base_default: str = argparse.SUPPRESS if suppress_defaults else BASE_URL
    parser.add_argument("--db", type=Path, default=db_default, help="Path to SQLite database")
    parser.add_argument("--base-url", default=base_default, help="Forum base URL")


def _add_sync_options(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    int_default: int | str | None = argparse.SUPPRESS if suppress_defaults else None
    false_default: bool | str = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument(
        "--workers",
        type=int,
        default=argparse.SUPPRESS if suppress_defaults else 8,
        help="Сколько параллельных HTTP worker'ов",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=argparse.SUPPRESS if suppress_defaults else 0.7,
        help="Пауза worker'а между topic-запросами",
    )
    parser.add_argument("--max-forums", type=int, default=int_default, help="Ограничить число форумов для тестового прохода")
    parser.add_argument("--max-topics", type=int, default=int_default, help="Ограничить число тем для тестового прохода")
    parser.add_argument("--no-images", action="store_true", default=false_default, help="Не скачивать картинки для ASCII-слепков")
    parser.add_argument(
        "--retries",
        type=int,
        default=argparse.SUPPRESS if suppress_defaults else 3,
        help="Повторы для временных HTTP/сетевых ошибок",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=argparse.SUPPRESS if suppress_defaults else 2.0,
        help="Базовая пауза между повторами",
    )
