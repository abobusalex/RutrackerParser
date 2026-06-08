from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import BASE_URL, default_db_path
from .crawler import RutrackerCrawler, SyncOptions, options_from_env
from .parser import parse_size
from .storage import Storage


STDOUT_ENCODING = sys.stdout.encoding or "utf-8"
UNICODE_STDOUT = "utf" in STDOUT_ENCODING.lower()
console = Console(emoji=UNICODE_STDOUT)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="rutracker-tui", description="🧲 RuTracker terminal crawler")
    parser.add_argument("--db", type=Path, default=default_db_path(), help="Path to SQLite database")
    parser.add_argument("--base-url", default=BASE_URL, help="Forum base URL")
    subparsers = parser.add_subparsers(dest="command")

    sync_parser = subparsers.add_parser("sync", help="🌊 Synchronize forum snapshot")
    _add_common_options(sync_parser)
    sync_parser.add_argument("--workers", type=int, default=8)
    sync_parser.add_argument("--delay", type=float, default=0.7)
    sync_parser.add_argument("--max-forums", type=int)
    sync_parser.add_argument("--max-topics", type=int)
    sync_parser.add_argument("--no-images", action="store_true")

    search_parser = subparsers.add_parser("search", help="🔎 Search local database")
    _add_common_options(search_parser)
    search_parser.add_argument("query", nargs="?", default="")
    search_parser.add_argument("--min-seeders", type=int)
    search_parser.add_argument("--max-size")
    search_parser.add_argument("--magnet-only", action="store_true")
    search_parser.add_argument("--limit", type=int, default=30)

    stats_parser = subparsers.add_parser("stats", help="📊 Show local snapshot stats")
    _add_common_options(stats_parser)
    tui_parser = subparsers.add_parser("tui", help="✨ Launch terminal UI")
    _add_common_options(tui_parser)

    args = parser.parse_args(argv)
    command = args.command or "tui"
    if command == "sync":
        asyncio.run(_sync(args))
    elif command == "search":
        _search(args)
    elif command == "stats":
        _stats(args.db)
    elif command == "tui":
        from .tui import RutrackerApp

        RutrackerApp(db_path=args.db, base_url=args.base_url).run()


async def _sync(args: argparse.Namespace) -> None:
    options = options_from_env(args.db, args.base_url, args.workers, args.delay)
    options = SyncOptions(
        db_path=options.db_path,
        base_url=options.base_url,
        workers=options.workers,
        delay=options.delay,
        max_forums=args.max_forums,
        max_topics=args.max_topics,
        include_images=not args.no_images,
        username=options.username,
        password=options.password,
    )
    crawler = RutrackerCrawler(options, log=_print_log)
    try:
        await crawler.run()
    finally:
        await crawler.close()


def _search(args: argparse.Namespace) -> None:
    max_size = parse_size(args.max_size)[1] if args.max_size else None
    storage = Storage(args.db)
    try:
        rows = storage.search_topics(
            query=args.query,
            min_seeders=args.min_seeders,
            max_size_bytes=max_size,
            magnet_only=args.magnet_only,
            limit=args.limit,
        )
        table = Table(title=_safe_text("🔎 RuTracker локальный поиск"))
        table.add_column(_safe_text("🧲"))
        table.add_column("Название", overflow="fold")
        table.add_column(_safe_text("🌱"), justify="right")
        table.add_column(_safe_text("📦"), justify="right")
        table.add_column("Форум", overflow="fold")
        for row in rows:
            table.add_row(
                "yes" if row["magnet"] else "—",
                row["title"],
                str(row["seeders"] or 0),
                row["size_text"] or "—",
                row["forum_title"] or "—",
            )
        console.print(table)
    finally:
        storage.close()


def _safe_text(value: str) -> str:
    return value.encode(STDOUT_ENCODING, errors="replace").decode(STDOUT_ENCODING)


def _print_log(message: str) -> None:
    console.print(_safe_text(message))


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=argparse.SUPPRESS, help="Path to SQLite database")
    parser.add_argument("--base-url", default=argparse.SUPPRESS, help="Forum base URL")


def _stats(db_path: Path) -> None:
    storage = Storage(db_path)
    try:
        stats = storage.stats()
        for key, value in stats.items():
            console.print(f"{key}: [bold cyan]{value}[/bold cyan]")
    finally:
        storage.close()
