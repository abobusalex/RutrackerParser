from pathlib import Path
import unittest

from rutracker_tui.config import app_root, default_data_dir, default_db_path


class ConfigTest(unittest.TestCase):
    def test_default_db_lives_next_to_application(self):
        self.assertEqual(default_data_dir(), app_root() / "data")
        self.assertEqual(default_db_path(), app_root() / "data" / "rutracker.sqlite3")
        self.assertNotIn("AppData", str(default_db_path()))

    def test_app_root_is_project_root(self):
        self.assertEqual(app_root(), Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    unittest.main()
