import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rutracker_tui import cli
from rutracker_tui.cli import build_parser


class CliParserTest(unittest.TestCase):
    def test_default_command_is_run(self):
        args = build_parser().parse_args([])
        self.assertIsNone(args.command)
        self.assertFalse(args.no_auto_sync)
        self.assertFalse(args.no_tui)

    def test_global_options_survive_subcommand_defaults(self):
        args = build_parser().parse_args(
            [
                "--db",
                "custom.sqlite3",
                "--workers",
                "2",
                "sync",
                "--delay",
                "1.5",
            ]
        )
        self.assertEqual(args.db, Path("custom.sqlite3"))
        self.assertEqual(args.workers, 2)
        self.assertEqual(args.delay, 1.5)

    def test_search_json_flags(self):
        args = build_parser().parse_args(
            ["search", "ubuntu", "--json", "--offline", "--limit", "5", "-o", "10", "--category", "Аниме", "--asc"]
        )
        self.assertEqual(args.command, "search")
        self.assertEqual(args.query, "ubuntu")
        self.assertTrue(args.json)
        self.assertTrue(args.offline)
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.sort, "10")
        self.assertEqual(args.category, "Аниме")
        self.assertTrue(args.asc)

    def test_run_opens_tui_without_cli_sync(self):
        with TemporaryDirectory() as temp_dir:
            args = build_parser().parse_args(["--db", str(Path(temp_dir) / "empty.sqlite3")])
            with patch("rutracker_tui.cli._sync") as sync, patch("rutracker_tui.tui.RutrackerApp.run") as tui_run:
                cli._run(args)
            sync.assert_not_called()
            tui_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
