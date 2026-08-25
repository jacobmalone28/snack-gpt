from pathlib import Path
import tempfile
import unittest

from snack_gpt.storage import Storage


class StorageTests(unittest.TestCase):
    def test_initialization_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"

            with Storage(database_path) as storage:
                storage.initialize()
                first_health = storage.health()

            with Storage(database_path) as restarted_storage:
                restarted_storage.initialize()
                restarted_health = restarted_storage.health()

            self.assertEqual(first_health.schema_version, 1)
            self.assertTrue(first_health.writable)
            self.assertEqual(restarted_health, first_health)


if __name__ == "__main__":
    unittest.main()