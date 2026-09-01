from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from snack_gpt.history_transfer import HistoryImportError, export_history, import_history
from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage


EVENT = ConsumptionEvent(
    event_id="stable-event-id",
    revision=3,
    day=date(2026, 8, 25),
    usda_food_id="171287",
    food_description="Egg, whole, raw, fresh",
    quantity_value=2.0,
    quantity_measure="large",
    nutrition=NutritionSnapshot(143.0, 12.6, 0.72, 9.51),
)


class HistoryTransferTests(unittest.TestCase):
    def test_export_round_trips_every_consumption_event_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite3"
            destination_path = Path(directory) / "destination.sqlite3"
            with Storage(source_path) as source:
                source.initialize()
                source.create_consumption_event(EVENT)
                document = export_history(source)

            payload = json.loads(document)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(
                payload["consumption_events"],
                [
                    {
                        "event_id": "stable-event-id",
                        "revision": 3,
                        "day": "2026-08-25",
                        "usda_food_id": "171287",
                        "food_description": "Egg, whole, raw, fresh",
                        "food_quantity": {"value": 2.0, "measure": "large"},
                        "nutrition_snapshot": {
                            "calories": 143.0,
                            "protein": 12.6,
                            "carbohydrates": 0.72,
                            "fat": 9.51,
                        },
                    }
                ],
            )

            with Storage(destination_path) as destination:
                destination.initialize()
                result = import_history(destination, document)
                imported_events = destination.list_consumption_events()

        self.assertEqual(result.imported_count, 1)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(result.conflict_ids, ())
        self.assertEqual(imported_events, [EVENT])

    def test_malformed_document_is_rejected_before_any_event_is_imported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite3"
            destination_path = Path(directory) / "destination.sqlite3"
            with Storage(source_path) as source:
                source.initialize()
                source.create_consumption_event(EVENT)
                payload = json.loads(export_history(source))
            payload["consumption_events"].append({"event_id": "incomplete"})

            with Storage(destination_path) as destination:
                destination.initialize()
                with self.assertRaisesRegex(HistoryImportError, "fields"):
                    import_history(destination, json.dumps(payload).encode())
                imported_events = destination.list_consumption_events()

        self.assertEqual(imported_events, [])

    def test_document_with_duplicate_event_ids_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "events.sqlite3"
            with Storage(database_path) as storage:
                storage.initialize()
                storage.create_consumption_event(EVENT)
                payload = json.loads(export_history(storage))
                payload["consumption_events"].append(payload["consumption_events"][0])

                with self.assertRaisesRegex(HistoryImportError, "duplicate event IDs"):
                    import_history(storage, json.dumps(payload).encode())

                self.assertEqual(storage.list_consumption_events(), [EVENT])

    def test_reimport_skips_identical_existing_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite3"
            destination_path = Path(directory) / "destination.sqlite3"
            with Storage(source_path) as source:
                source.initialize()
                source.create_consumption_event(EVENT)
                document = export_history(source)

            with Storage(destination_path) as destination:
                destination.initialize()
                import_history(destination, document)
                result = import_history(destination, document)
                imported_events = destination.list_consumption_events()

        self.assertEqual(result.imported_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.conflict_ids, ())
        self.assertEqual(imported_events, [EVENT])

    def test_conflict_is_reported_without_overwriting_local_event(self) -> None:
        local_event = replace(EVENT, revision=4, food_description="Locally corrected egg")
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite3"
            destination_path = Path(directory) / "destination.sqlite3"
            with Storage(source_path) as source:
                source.initialize()
                source.create_consumption_event(EVENT)
                document = export_history(source)

            with Storage(destination_path) as destination:
                destination.initialize()
                destination.create_consumption_event(local_event)
                result = import_history(destination, document)
                imported_events = destination.list_consumption_events()

        self.assertEqual(result.imported_count, 0)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(result.conflict_ids, (EVENT.event_id,))
        self.assertEqual(imported_events, [local_event])

    def test_new_events_import_while_conflicts_preserve_local_events(self) -> None:
        new_event = replace(EVENT, event_id="new-event-id", food_description="Rice")
        local_event = replace(EVENT, revision=4, food_description="Locally corrected egg")
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite3"
            destination_path = Path(directory) / "destination.sqlite3"
            with Storage(source_path) as source:
                source.initialize()
                source.create_consumption_event(EVENT)
                source.create_consumption_event(new_event)
                document = export_history(source)

            with Storage(destination_path) as destination:
                destination.initialize()
                destination.create_consumption_event(local_event)
                result = import_history(destination, document)
                imported_events = destination.list_consumption_events()

        self.assertEqual(result.imported_count, 1)
        self.assertEqual(result.conflict_ids, (EVENT.event_id,))
        self.assertEqual(imported_events, [local_event, new_event])


if __name__ == "__main__":
    unittest.main()