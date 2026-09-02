from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

from snack_gpt.auth import hash_password, session_token_hash, verify_password
from snack_gpt.storage import (
    ConsumptionEvent,
    NutritionSnapshot,
    Storage,
    VoiceState,
    VoiceStatus,
)


class StorageTests(unittest.TestCase):
    def test_voice_control_and_status_are_shared_between_connections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"
            with Storage(database_path) as listener_storage:
                listener_storage.initialize()
                self.assertEqual(
                    listener_storage.voice_state(),
                    VoiceState(False, VoiceStatus.CONFIGURATION_ERROR, True),
                )

                with Storage(database_path) as web_storage:
                    paused = web_storage.set_voice_paused(True)

                self.assertEqual(
                    paused, VoiceState(True, VoiceStatus.CONFIGURATION_ERROR, True)
                )
                self.assertEqual(listener_storage.voice_state(), paused)
                listener_storage.set_voice_status(
                    VoiceStatus.USDA_UNAVAILABLE, usda_available=False
                )

                with Storage(database_path) as refreshed_web_storage:
                    self.assertEqual(
                        refreshed_web_storage.voice_state(),
                        VoiceState(True, VoiceStatus.USDA_UNAVAILABLE, False),
                    )
                    self.assertEqual(
                        refreshed_web_storage.set_voice_paused(False),
                        VoiceState(False, VoiceStatus.USDA_UNAVAILABLE, False),
                    )

                with self.assertRaisesRegex(ValueError, "controlled separately"):
                    listener_storage.set_voice_status(VoiceStatus.PAUSED)

    def test_password_reset_stores_only_a_hash_and_revokes_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"
            with Storage(database_path) as storage:
                storage.initialize()
                first_hash = hash_password("first password")
                storage.set_owner_password_hash(first_hash)
                token_hash = session_token_hash("session secret")
                self.assertTrue(storage.create_owner_session(token_hash, 200, first_hash))

                replacement_hash = hash_password("replacement password")
                storage.set_owner_password_hash(replacement_hash)

                self.assertEqual(storage.owner_password_hash(), replacement_hash)
                self.assertTrue(verify_password("replacement password", replacement_hash))
                self.assertFalse(storage.owner_session_is_valid(token_hash, 100))

            database_contents = database_path.read_bytes()
            self.assertNotIn(b"first password", database_contents)
            self.assertNotIn(b"replacement password", database_contents)
            self.assertNotIn(b"session secret", database_contents)

    def test_session_creation_rejects_a_hash_invalidated_by_password_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "snack-gpt.sqlite3") as storage:
                storage.initialize()
                verified_hash = hash_password("first password")
                storage.set_owner_password_hash(verified_hash)

                storage.set_owner_password_hash(hash_password("replacement password"))
                token_hash = session_token_hash("stale login session")
                created = storage.create_owner_session(token_hash, 200, verified_hash)

                self.assertFalse(created)
                self.assertFalse(storage.owner_session_is_valid(token_hash, 100))

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
                    storage.create_consumption_events(
                        [event, event],
                        utterance_id="utterance-id",
                    )

                self.assertEqual(storage.list_consumption_events(), [])
                self.assertTrue(
                    storage.create_consumption_events(
                        [event],
                        utterance_id="utterance-id",
                    )
                )
                self.assertEqual(storage.list_consumption_events(), [event])

    def test_initialization_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snack-gpt.sqlite3"

            with Storage(database_path) as storage:
                storage.initialize()
                first_health = storage.health()

            with Storage(database_path) as restarted_storage:
                restarted_storage.initialize()
                restarted_health = restarted_storage.health()

            self.assertEqual(first_health.schema_version, 5)
            self.assertTrue(first_health.writable)
            self.assertEqual(restarted_health, first_health)


if __name__ == "__main__":
    unittest.main()