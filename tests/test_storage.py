from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage


class StorageTests(unittest.TestCase):
    def test_stale_mutations_preserve_the_newer_consumption_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "snack-gpt.sqlite3") as storage:
                storage.initialize()
                original = ConsumptionEvent(
                    event_id="event-id",
                    revision=1,
                    day=date(2026, 8, 25),
                    usda_food_id="171287",
                    food_description="Egg, whole, raw, fresh",
                    quantity_value=1,
                    quantity_measure="large",
                    nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
                )
                replacement = ConsumptionEvent(
                    event_id="event-id",
                    revision=2,
                    day=date(2026, 8, 26),
                    usda_food_id="171287",
                    food_description="Egg, whole, raw, fresh",
                    quantity_value=1,
                    quantity_measure="large",
                    nutrition=original.nutrition,
                )
                stale_replacement = ConsumptionEvent(
                    event_id="event-id",
                    revision=2,
                    day=date(2026, 8, 27),
                    usda_food_id="171287",
                    food_description="Egg, whole, raw, fresh",
                    quantity_value=1,
                    quantity_measure="large",
                    nutrition=original.nutrition,
                )
                storage.create_consumption_event(original)

                self.assertTrue(storage.update_consumption_event(replacement, 1))
                self.assertFalse(storage.update_consumption_event(stale_replacement, 1))
                self.assertFalse(storage.delete_consumption_event("event-id", 1))

                self.assertEqual(storage.list_consumption_events(), [replacement])

    def test_consumption_report_rolls_back_when_any_insert_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "snack-gpt.sqlite3") as storage:
                storage.initialize()
                event = ConsumptionEvent(
                    event_id="duplicate-id",
                    revision=1,
                    day=date(2026, 8, 25),
                    usda_food_id="171287",
                    food_description="Egg, whole, raw, fresh",
                    quantity_value=1,
                    quantity_measure="large",
                    nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    storage.create_consumption_events([event, event])

                self.assertEqual(storage.list_consumption_events(), [])

    def test_initialization_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"

            with Storage(database_path) as storage:
                storage.initialize()
                first_health = storage.health()

            with Storage(database_path) as restarted_storage:
                restarted_storage.initialize()
                restarted_health = restarted_storage.health()

            self.assertEqual(first_health.schema_version, 2)
            self.assertTrue(first_health.writable)
            self.assertEqual(restarted_health, first_health)


if __name__ == "__main__":
    unittest.main()