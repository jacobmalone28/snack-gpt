from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

from snack_gpt.ingestion import FoodSearchResult
from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage, VoiceStatus
from snack_gpt.voice import (
    CapturedSpeech,
    VoiceListeningPaused,
    VoiceProcessingTimeout,
    create_consumption_event_from_voice,
    create_consumption_report_from_voice,
)
from snack_gpt.usda import UsdaError
from snack_gpt.voice_runtime import CommandVoiceRuntime, VoiceRuntimeError, load_voice_manifest
from snack_gpt.voice_runtime import _run_command


COMPLETE_RESULT = FoodSearchResult(
    usda_food_id="20",
    description="Egg, whole, raw, fresh",
    nutrients_per_100_grams={
        "calories": 143.0,
        "protein": 12.6,
        "carbohydrates": 0.72,
        "fat": 9.51,
    },
    measures={"large": 50.0},
)


class ControlledUsdaSearch:
    def __init__(self, results: list[FoodSearchResult]) -> None:
        self._results = results
        self.queries: list[str] = []
        self.timeouts: list[float | None] = []

    def search(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[FoodSearchResult]:
        self.queries.append(query)
        self.timeouts.append(timeout_seconds)
        return self._results


class TimingOutUsdaSearch(ControlledUsdaSearch):
    def search(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[FoodSearchResult]:
        super().search(query, timeout_seconds=timeout_seconds)
        raise TimeoutError


class UnavailableUsdaSearch(ControlledUsdaSearch):
    def search(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[FoodSearchResult]:
        super().search(query, timeout_seconds=timeout_seconds)
        raise UsdaError("USDA unavailable")


class ControlledVoiceRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.successful_events: list[ConsumptionEvent] | None = None
        self.failure_reason: str | None = None

    def wait_for_wake_and_capture(self) -> CapturedSpeech:
        self.calls.append("capture")
        return CapturedSpeech(b"voice audio", date(2026, 8, 25))

    def transcribe(self, audio: bytes, deadline: float) -> str:
        self.calls.append("transcribe")
        self.assert_before_deadline(deadline)
        self.assertEqual(audio, b"voice audio")
        return "I ate one egg"

    def extract(self, transcript: str, deadline: float) -> object:
        self.calls.append("extract")
        self.assert_before_deadline(deadline)
        self.assertEqual(transcript, "I ate one egg")
        return {
            "foods": [{"food": "egg", "quantity": 1, "measure": "large"}],
            "confidence": 1,
        }

    def report_success(self, events: list[ConsumptionEvent], deadline: float) -> None:
        self.calls.append("success")
        self.assertEqual(deadline, 130.0)
        self.successful_events = events

    def report_failure(self, reason: str, deadline: float) -> None:
        self.calls.append("failure")
        self.failure_reason = reason

    def assert_before_deadline(self, deadline: float) -> None:
        self.assertEqual(deadline, 120.0)

    def assertEqual(self, first: object, second: object) -> None:
        if first != second:
            raise AssertionError(f"{first!r} != {second!r}")


class RepeatedFoodsVoiceRuntime(ControlledVoiceRuntime):
    def extract(self, transcript: str, deadline: float) -> object:
        self.calls.append("extract")
        self.assert_before_deadline(deadline)
        return {
            "foods": [
                {"food": "egg", "quantity": 1, "measure": "large"},
                {"food": "egg", "quantity": 2, "measure": "large"},
            ],
            "confidence": 1,
        }


class InvalidSecondFoodVoiceRuntime(RepeatedFoodsVoiceRuntime):
    def extract(self, transcript: str, deadline: float) -> object:
        extraction = super().extract(transcript, deadline)
        assert isinstance(extraction, dict)
        foods = extraction["foods"]
        assert isinstance(foods, list)
        foods[1] = {"food": "egg", "quantity": 2, "measure": "bucket"}
        return extraction


class LowConfidenceVoiceRuntime(ControlledVoiceRuntime):
    def extract(self, transcript: str, deadline: float) -> object:
        extraction = super().extract(transcript, deadline)
        assert isinstance(extraction, dict)
        extraction["confidence"] = 0.5
        return extraction


class ReplayVoiceRuntime(ControlledVoiceRuntime):
    def wait_for_wake_and_capture(self) -> CapturedSpeech:
        self.calls.append("capture")
        return CapturedSpeech(b"voice audio", date(2026, 8, 25), "utterance-id")


class CaptureTimingOutRuntime(ControlledVoiceRuntime):
    def wait_for_wake_and_capture(self) -> CapturedSpeech:
        self.calls.append("capture")
        raise VoiceProcessingTimeout


class ControlledCommands:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.paths: list[Path] = []
        self.wake_attempts = 0

    def run(self, command: list[str] | tuple[str, ...], timeout: float | None) -> None:
        name = command[0]
        self.names.append(name)
        path = Path(command[1]) if len(command) > 1 else None
        if path is not None:
            self.paths.append(path)
        if name == "wake-capture":
            assert path is not None
            path.write_bytes(b"wake audio")
        elif name == "wake-detection":
            assert path is not None
            self.wake_attempts += 1
            path.write_text(json.dumps({"detected": self.wake_attempts == 2}), encoding="utf-8")
        elif name == "speech-capture":
            assert path is not None
            self.assert_timeout(timeout, 15.0)
            if command[2] != "1.0":
                raise AssertionError(f"unexpected silence target: {command[2]}")
            path.write_bytes(b"report audio")
        elif name == "transcription":
            assert path is not None
            path.write_text("I ate one egg", encoding="utf-8")
        elif name == "extraction":
            assert path is not None
            path.write_text(
                '{"foods":[{"food":"egg","quantity":1,"measure":"large"}],"confidence":1}',
                encoding="utf-8",
            )
        elif name == "synthesize":
            assert path is not None
            path.write_bytes(b"RIFFspeech")

    def assert_timeout(self, actual: float | None, expected: float) -> None:
        if actual != expected:
            raise AssertionError(f"{actual!r} != {expected!r}")


class TranscriptionTimingOutCommands(ControlledCommands):
    def run(self, command: list[str] | tuple[str, ...], timeout: float | None) -> None:
        if command[0] == "transcription":
            self.names.append("transcription")
            raise VoiceProcessingTimeout
        super().run(command, timeout)


COMMANDS = {
    "wake_capture": ["wake-capture", "{audio}"],
    "wake_detection": ["wake-detection", "{output}"],
    "speech_capture": ["speech-capture", "{audio}", "{silence_seconds}"],
    "transcription": ["transcription", "{output}"],
    "extraction": ["extraction", "{output}"],
    "success_sound": ["success-sound"],
    "error_sound": ["error-sound"],
    "speech_synthesis": ["synthesize", "{output}", "{text}"],
    "play_speech": ["play", "{audio}"],
}


class VoiceTests(unittest.TestCase):
    def test_low_confidence_creates_no_report_and_gives_audible_feedback(self) -> None:
        runtime = LowConfidenceVoiceRuntime()
        usda_search = ControlledUsdaSearch([COMPLETE_RESULT])
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                result = create_consumption_event_from_voice(
                    storage,
                    usda_search,
                    runtime,
                    monotonic=lambda: 100.0,
                )

                self.assertIsNone(result)
                self.assertEqual(storage.list_consumption_events(), [])

        self.assertEqual(usda_search.queries, [])
        self.assertEqual(runtime.failure_reason, "I could not confidently identify every Food Quantity.")
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "failure"])

    def test_invalid_item_rejects_the_entire_voice_report(self) -> None:
        runtime = InvalidSecondFoodVoiceRuntime()
        usda_search = ControlledUsdaSearch([COMPLETE_RESULT])
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                result = create_consumption_event_from_voice(
                    storage,
                    usda_search,
                    runtime,
                    monotonic=lambda: 100.0,
                )

                self.assertIsNone(result)
                self.assertEqual(storage.list_consumption_events(), [])

        self.assertEqual(usda_search.queries, ["egg", "egg"])
        self.assertEqual(runtime.failure_reason, "That quantity measure is not recognized by USDA.")
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "failure"])

    def test_voice_logs_stages_without_private_report_data(self) -> None:
        runtime = ControlledVoiceRuntime()
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                with self.assertLogs("snack_gpt.voice", level="INFO") as captured:
                    create_consumption_event_from_voice(
                        storage,
                        ControlledUsdaSearch([]),
                        runtime,
                        monotonic=lambda: 100.0,
                        timer=lambda: 10.0,
                    )

        logs = "\n".join(captured.output)
        self.assertIn("utterance_id=", logs)
        self.assertIn("stage=ingestion", logs)
        self.assertIn("duration_ms=0.0", logs)
        self.assertIn("failure_category=invalid_report", logs)
        self.assertNotIn("I ate one egg", logs)
        self.assertNotIn("egg", logs.lower())
        self.assertNotIn("voice audio", logs)

    def test_replayed_utterance_creates_a_consumption_report_at_most_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "events.sqlite3"
            with Storage(database_path) as storage:
                storage.initialize()
                create_consumption_event_from_voice(
                    storage,
                    ControlledUsdaSearch([COMPLETE_RESULT]),
                    ReplayVoiceRuntime(),
                    monotonic=lambda: 100.0,
                )

            with Storage(database_path) as restarted_storage:
                restarted_storage.initialize()
                replay_runtime = ReplayVoiceRuntime()
                replay = create_consumption_event_from_voice(
                    restarted_storage,
                    ControlledUsdaSearch([COMPLETE_RESULT]),
                    replay_runtime,
                    monotonic=lambda: 100.0,
                )

                self.assertIsNone(replay)
                self.assertEqual(len(restarted_storage.list_consumption_events()), 1)

        self.assertEqual(replay_runtime.failure_reason, "This Consumption Report was already recorded.")

    def test_voice_report_creates_repeated_foods_atomically(self) -> None:
        runtime = RepeatedFoodsVoiceRuntime()
        usda_search = ControlledUsdaSearch([COMPLETE_RESULT])
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                result = create_consumption_report_from_voice(
                    storage,
                    usda_search,
                    runtime,
                    monotonic=lambda: 100.0,
                )

                events = storage.list_consumption_events()

            self.assertEqual(result, events)
        self.assertEqual([event.quantity_value for event in events], [1.0, 2.0])
        self.assertEqual(usda_search.queries, ["egg", "egg"])
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "success"])

    def test_voice_report_publishes_processing_and_usda_recovery(self) -> None:
        states: list[tuple[VoiceStatus, bool | None]] = []
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                create_consumption_report_from_voice(
                    storage,
                    ControlledUsdaSearch([COMPLETE_RESULT]),
                    ControlledVoiceRuntime(),
                    monotonic=lambda: 100.0,
                    state_changed=lambda status, available: states.append(
                        (status, available)
                    ),
                )

        self.assertEqual(
            states,
            [
                (VoiceStatus.PROCESSING, None),
                (VoiceStatus.LISTENING, True),
            ],
        )

    def test_voice_report_publishes_usda_unavailable(self) -> None:
        states: list[tuple[VoiceStatus, bool | None]] = []
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                create_consumption_report_from_voice(
                    storage,
                    UnavailableUsdaSearch([]),
                    ControlledVoiceRuntime(),
                    monotonic=lambda: 100.0,
                    state_changed=lambda status, available: states.append(
                        (status, available)
                    ),
                )

        self.assertEqual(
            states,
            [
                (VoiceStatus.PROCESSING, None),
                (VoiceStatus.USDA_UNAVAILABLE, False),
            ],
        )

    def test_capture_timeout_reports_standard_reason(self) -> None:
        runtime = CaptureTimingOutRuntime()
        usda_search = ControlledUsdaSearch([COMPLETE_RESULT])
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                event = create_consumption_event_from_voice(storage, usda_search, runtime)

                self.assertIsNone(event)
                self.assertEqual(storage.list_consumption_events(), [])

        self.assertEqual(runtime.failure_reason, "Processing took too long.")
        self.assertEqual(runtime.calls, ["capture", "failure"])

    def test_manifest_requires_an_explicit_memory_backed_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "voice.json"
            manifest.write_text('{"commands": {}}', encoding="utf-8")

            with self.assertRaisesRegex(VoiceRuntimeError, "memory_directory"):
                load_voice_manifest(manifest)

    def test_command_failure_does_not_expose_stderr(self) -> None:
        with self.assertRaisesRegex(VoiceRuntimeError, "Voice command failed") as raised:
            _run_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.write('private transcript'); raise SystemExit(1)",
                ],
                15.0,
            )

        self.assertNotIn("private transcript", str(raised.exception))

    def test_command_runtime_runs_local_pipeline_and_removes_private_artifacts(self) -> None:
        controlled_commands = ControlledCommands()
        with tempfile.TemporaryDirectory() as memory_directory:
            runtime = CommandVoiceRuntime(
                COMMANDS,
                Path(memory_directory),
                run_command=controlled_commands.run,
                today=lambda: date(2026, 8, 25),
                monotonic=lambda: 100.0,
            )

            capture = runtime.wait_for_wake_and_capture()
            transcript = runtime.transcribe(capture.audio, 130.0)
            extraction = runtime.extract(transcript, 130.0)
            event = ConsumptionEvent(
                event_id="event-id",
                revision=1,
                day=capture.started_on,
                usda_food_id="20",
                food_description="Egg, whole, raw, fresh",
                quantity_value=1,
                quantity_measure="large",
                nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
            )
            runtime.report_success([event], 130.0)

        self.assertEqual(capture.audio, b"report audio")
        self.assertEqual(capture.started_on, date(2026, 8, 25))
        self.assertEqual(transcript, "I ate one egg")
        self.assertEqual(
            extraction,
            {
                "foods": [{"food": "egg", "quantity": 1, "measure": "large"}],
                "confidence": 1,
            },
        )
        self.assertEqual(
            controlled_commands.names,
            [
                "wake-capture",
                "wake-detection",
                "wake-capture",
                "wake-detection",
                "speech-capture",
                "transcription",
                "extraction",
                "success-sound",
                "synthesize",
                "play",
            ],
        )
        self.assertTrue(all(not path.exists() for path in controlled_commands.paths))

    def test_command_runtime_observes_pause_between_wake_capture_chunks(self) -> None:
        controlled_commands = ControlledCommands()
        allowed = iter((True, False))
        with tempfile.TemporaryDirectory() as memory_directory:
            runtime = CommandVoiceRuntime(
                COMMANDS,
                Path(memory_directory),
                run_command=controlled_commands.run,
                listening_allowed=lambda: next(allowed),
            )

            with self.assertRaises(VoiceListeningPaused):
                runtime.wait_for_wake_and_capture()

        self.assertEqual(controlled_commands.names, ["wake-capture"])

    def test_command_runtime_and_coordinator_create_event(self) -> None:
        self._run_integrated_voice_report(ControlledCommands(), [COMPLETE_RESULT], expect_event=True)

    def test_command_runtime_and_coordinator_report_lookup_failure(self) -> None:
        self._run_integrated_voice_report(ControlledCommands(), [], expect_event=False)

    def test_command_runtime_and_coordinator_report_timeout(self) -> None:
        self._run_integrated_voice_report(
            TranscriptionTimingOutCommands(),
            [COMPLETE_RESULT],
            expect_event=False,
        )

    def _run_integrated_voice_report(
        self,
        controlled_commands: ControlledCommands,
        results: list[FoodSearchResult],
        *,
        expect_event: bool,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = CommandVoiceRuntime(
                COMMANDS,
                root,
                run_command=controlled_commands.run,
                today=lambda: date(2026, 8, 25),
                monotonic=lambda: 100.0,
            )
            with Storage(root / "events.sqlite3") as storage:
                storage.initialize()

                event = create_consumption_event_from_voice(
                    storage,
                    ControlledUsdaSearch(results),
                    runtime,
                    monotonic=lambda: 100.0,
                )

                self.assertEqual(event is not None, expect_event)
                self.assertEqual(len(storage.list_consumption_events()), int(expect_event))

        expected_feedback = "success-sound" if expect_event else "error-sound"
        self.assertIn(expected_feedback, controlled_commands.names)
        self.assertTrue(all(not path.exists() for path in controlled_commands.paths))

    def test_voice_report_uses_shared_ingestion_and_capture_day(self) -> None:
        runtime = ControlledVoiceRuntime()
        usda_search = ControlledUsdaSearch([COMPLETE_RESULT])
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                event = create_consumption_event_from_voice(
                    storage,
                    usda_search,
                    runtime,
                    monotonic=lambda: 100.0,
                )

                self.assertEqual(storage.list_consumption_events(), [event])

        self.assertEqual(usda_search.queries, ["egg"])
        self.assertEqual(len(usda_search.timeouts), 1)
        assert usda_search.timeouts[0] is not None
        self.assertGreater(usda_search.timeouts[0], 0)
        self.assertEqual(event.day, date(2026, 8, 25))
        self.assertEqual(runtime.successful_events, [event])
        self.assertIsNone(runtime.failure_reason)
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "success"])

    def test_lookup_failure_creates_no_event_and_reports_reason(self) -> None:
        runtime = ControlledVoiceRuntime()
        usda_search = ControlledUsdaSearch([])
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                event = create_consumption_event_from_voice(
                    storage,
                    usda_search,
                    runtime,
                    monotonic=lambda: 100.0,
                )

                self.assertIsNone(event)
                self.assertEqual(storage.list_consumption_events(), [])

        self.assertEqual(usda_search.queries, ["egg"])
        self.assertIsNone(runtime.successful_events)
        self.assertEqual(
            runtime.failure_reason,
            "No USDA result for that food contains complete nutrition information.",
        )
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "failure"])

    def test_processing_stops_when_a_stage_crosses_the_thirty_second_deadline(self) -> None:
        runtime = ControlledVoiceRuntime()
        usda_search = ControlledUsdaSearch([COMPLETE_RESULT])
        times = iter((100.0, 131.0))
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                event = create_consumption_event_from_voice(
                    storage,
                    usda_search,
                    runtime,
                    monotonic=lambda: next(times),
                )

                self.assertIsNone(event)
                self.assertEqual(storage.list_consumption_events(), [])

        self.assertEqual(usda_search.queries, [])
        self.assertEqual(runtime.failure_reason, "Processing took too long.")
        self.assertEqual(runtime.calls, ["capture", "transcribe", "failure"])

    def test_committed_report_is_acknowledged_when_storage_crosses_the_deadline(self) -> None:
        runtime = ControlledVoiceRuntime()
        times = iter((100.0, 100.0, 100.0, 100.0, 121.0))
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                events = create_consumption_report_from_voice(
                    storage,
                    ControlledUsdaSearch([COMPLETE_RESULT]),
                    runtime,
                    monotonic=lambda: next(times),
                )

                self.assertEqual(events, storage.list_consumption_events())

        self.assertIsNone(runtime.failure_reason)
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "success"])

    def test_usda_timeout_creates_no_event_and_reports_before_final_deadline(self) -> None:
        runtime = ControlledVoiceRuntime()
        usda_search = TimingOutUsdaSearch([])
        states: list[tuple[VoiceStatus, bool | None]] = []
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                event = create_consumption_event_from_voice(
                    storage,
                    usda_search,
                    runtime,
                    monotonic=lambda: 100.0,
                    state_changed=lambda status, available: states.append(
                        (status, available)
                    ),
                )

                self.assertIsNone(event)
                self.assertEqual(storage.list_consumption_events(), [])

        self.assertEqual(usda_search.queries, ["egg"])
        self.assertEqual(runtime.failure_reason, "Processing took too long.")
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "failure"])
        self.assertEqual(states[-1], (VoiceStatus.USDA_UNAVAILABLE, False))


if __name__ == "__main__":
    unittest.main()