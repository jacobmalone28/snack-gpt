from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
import sqlite3
from types import TracebackType
from typing import Self, Sequence


@dataclass(frozen=True)
class StorageHealth:
    schema_version: int
    writable: bool


class VoiceStatus(StrEnum):
    LISTENING = "listening"
    PAUSED = "paused"
    PROCESSING = "processing"
    USDA_UNAVAILABLE = "usda_unavailable"
    AUDIO_UNAVAILABLE = "audio_unavailable"
    CONFIGURATION_ERROR = "configuration_error"


@dataclass(frozen=True)
class VoiceState:
    paused: bool
    status: VoiceStatus
    usda_available: bool


@dataclass(frozen=True)
class NutritionSnapshot:
    calories: float
    protein: float
    carbohydrates: float
    fat: float


@dataclass(frozen=True)
class ConsumptionEvent:
    event_id: str
    revision: int
    day: date
    usda_food_id: str
    food_description: str
    quantity_value: float
    quantity_measure: str
    nutrition: NutritionSnapshot


class Storage:
    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(database_path)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._connection.close()

    def initialize(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (1)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consumption_events (
                    event_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    usda_food_id TEXT NOT NULL,
                    food_description TEXT NOT NULL,
                    quantity_value REAL NOT NULL,
                    quantity_measure TEXT NOT NULL,
                    calories REAL NOT NULL,
                    protein REAL NOT NULL,
                    carbohydrates REAL NOT NULL,
                    fat REAL NOT NULL
                )
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (2)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS owner_credentials (
                    owner_id INTEGER PRIMARY KEY CHECK (owner_id = 1),
                    password_hash TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS owner_sessions (
                    token_hash TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (3)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_utterances (
                    utterance_id TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (4)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    paused INTEGER NOT NULL CHECK (paused IN (0, 1)),
                    status TEXT NOT NULL CHECK (status != 'paused'),
                    usda_available INTEGER NOT NULL CHECK (usda_available IN (0, 1))
                )
                """
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO voice_state (singleton, paused, status, usda_available)
                VALUES (1, 0, 'configuration_error', 1)
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (5)"
            )

    def voice_state(self) -> VoiceState:
        row = self._connection.execute(
            "SELECT paused, status, usda_available FROM voice_state WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("Storage is not initialized")
        return VoiceState(bool(row[0]), VoiceStatus(str(row[1])), bool(row[2]))

    def set_voice_paused(self, paused: bool) -> VoiceState:
        with self._connection:
            self._connection.execute(
                "UPDATE voice_state SET paused = ? WHERE singleton = 1",
                (paused,),
            )
        return self.voice_state()

    def set_voice_status(
        self, status: VoiceStatus, *, usda_available: bool | None = None
    ) -> VoiceState:
        if status == VoiceStatus.PAUSED:
            raise ValueError("Pause is controlled separately from runtime status")
        with self._connection:
            if usda_available is None:
                self._connection.execute(
                    "UPDATE voice_state SET status = ? WHERE singleton = 1",
                    (status.value,),
                )
            else:
                self._connection.execute(
                    """
                    UPDATE voice_state SET status = ?, usda_available = ?
                    WHERE singleton = 1
                    """,
                    (status.value, usda_available),
                )
        return self.voice_state()

    def set_usda_available(self, available: bool) -> VoiceState:
        with self._connection:
            self._connection.execute(
                "UPDATE voice_state SET usda_available = ? WHERE singleton = 1",
                (available,),
            )
        return self.voice_state()

    def retry_usda(self) -> VoiceState:
        with self._connection:
            self._connection.execute(
                """
                UPDATE voice_state SET status = 'listening', usda_available = 1
                WHERE singleton = 1
                """
            )
        return self.voice_state()

    def set_owner_password_hash(self, password_hash: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO owner_credentials (owner_id, password_hash) VALUES (1, ?)
                ON CONFLICT(owner_id) DO UPDATE SET password_hash = excluded.password_hash
                """,
                (password_hash,),
            )
            self._connection.execute("DELETE FROM owner_sessions")

    def owner_password_hash(self) -> str | None:
        row = self._connection.execute(
            "SELECT password_hash FROM owner_credentials WHERE owner_id = 1"
        ).fetchone()
        return str(row[0]) if row is not None else None

    def create_owner_session(
        self, token_hash: str, expires_at: int, expected_password_hash: str
    ) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO owner_sessions (token_hash, expires_at)
                SELECT ?, ?
                FROM owner_credentials
                WHERE owner_id = 1 AND password_hash = ?
                """,
                (token_hash, expires_at, expected_password_hash),
            )
        return cursor.rowcount == 1

    def owner_session_is_valid(self, token_hash: str, now: int) -> bool:
        with self._connection:
            self._connection.execute(
                "DELETE FROM owner_sessions WHERE expires_at <= ?", (now,)
            )
            row = self._connection.execute(
                "SELECT 1 FROM owner_sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return row is not None

    def delete_owner_session(self, token_hash: str) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM owner_sessions WHERE token_hash = ?", (token_hash,)
            )

    def create_consumption_event(self, event: ConsumptionEvent) -> None:
        self.create_consumption_events([event])

    def create_consumption_events(
        self,
        events: Sequence[ConsumptionEvent],
        *,
        utterance_id: str | None = None,
    ) -> bool:
        with self._connection:
            if utterance_id is not None:
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO processed_utterances (utterance_id) VALUES (?)",
                    (utterance_id,),
                )
                if cursor.rowcount == 0:
                    return False
            self._connection.executemany(
                """
                INSERT INTO consumption_events (
                    event_id, revision, day, usda_food_id, food_description,
                    quantity_value, quantity_measure, calories, protein,
                    carbohydrates, fat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event.event_id,
                        event.revision,
                        event.day.isoformat(),
                        event.usda_food_id,
                        event.food_description,
                        event.quantity_value,
                        event.quantity_measure,
                        event.nutrition.calories,
                        event.nutrition.protein,
                        event.nutrition.carbohydrates,
                        event.nutrition.fat,
                    )
                    for event in events
                ],
            )
        return True

    def update_consumption_event(
        self, event: ConsumptionEvent, expected_revision: int
    ) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE consumption_events
                SET revision = ?, day = ?, usda_food_id = ?, food_description = ?,
                    quantity_value = ?, quantity_measure = ?, calories = ?,
                    protein = ?, carbohydrates = ?, fat = ?
                WHERE event_id = ? AND revision = ?
                """,
                (
                    event.revision,
                    event.day.isoformat(),
                    event.usda_food_id,
                    event.food_description,
                    event.quantity_value,
                    event.quantity_measure,
                    event.nutrition.calories,
                    event.nutrition.protein,
                    event.nutrition.carbohydrates,
                    event.nutrition.fat,
                    event.event_id,
                    expected_revision,
                ),
            )
        return cursor.rowcount == 1

    def delete_consumption_event(self, event_id: str, expected_revision: int) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM consumption_events WHERE event_id = ? AND revision = ?",
                (event_id, expected_revision),
            )
        return cursor.rowcount == 1

    def get_consumption_event(self, event_id: str) -> ConsumptionEvent | None:
        return next(
            (
                event
                for event in self.list_consumption_events()
                if event.event_id == event_id
            ),
            None,
        )

    def list_consumption_events(self) -> list[ConsumptionEvent]:
        rows = self._connection.execute(
            """
            SELECT event_id, revision, day, usda_food_id, food_description,
                   quantity_value, quantity_measure, calories, protein,
                   carbohydrates, fat
            FROM consumption_events
            ORDER BY day, rowid
            """
        ).fetchall()
        return [
            ConsumptionEvent(
                event_id=str(row[0]),
                revision=int(row[1]),
                day=date.fromisoformat(str(row[2])),
                usda_food_id=str(row[3]),
                food_description=str(row[4]),
                quantity_value=float(row[5]),
                quantity_measure=str(row[6]),
                nutrition=NutritionSnapshot(
                    calories=float(row[7]),
                    protein=float(row[8]),
                    carbohydrates=float(row[9]),
                    fat=float(row[10]),
                ),
            )
            for row in rows
        ]

    def health(self) -> StorageHealth:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        schema_version = int(row[0]) if row is not None else 0

        writable = True
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.rollback()
        except sqlite3.OperationalError:
            writable = False

        return StorageHealth(schema_version=schema_version, writable=writable)