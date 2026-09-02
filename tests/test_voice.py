from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from snack_gpt.ingestion import FoodSearchResult
from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage
from snack_gpt.voice import CapturedSpeech, create_consumption_event_from_voice
from snack_gpt.voice_runtime import CommandVoiceRuntime


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


class ControlledVoiceRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.successful_event: ConsumptionEvent | None = None
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
        return {"foods": [{"food": "egg", "quantity": 1, "measure": "large"}]}

    def report_success(self, event: ConsumptionEvent, deadline: float) -> None:
        self.calls.append("success")
        self.assertEqual(deadline, 130.0)
        self.successful_event = event

    def report_failure(self, reason: str, deadline: float) -> None:
        self.calls.append("failure")
        self.failure_reason = reason

    def assert_before_deadline(self, deadline: float) -> None:
        self.assertEqual(deadline, 120.0)

    def assertEqual(self, first: object, second: object) -> None:
        if first != second:
            raise AssertionError(f"{first!r} != {second!r}")


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
            path.write_bytes(b"report audio")
        elif name == "transcription":
            assert path is not None
            path.write_text("I ate one egg", encoding="utf-8")
        elif name == "extraction":
            assert path is not None
            path.write_text(
                '{"foods":[{"food":"egg","quantity":1,"measure":"large"}]}',
                encoding="utf-8",
            )
        elif name == "synthesize":
            assert path is not None
            path.write_bytes(b"RIFFspeech")

    def assert_timeout(self, actual: float | None, expected: float) -> None:
        if actual != expected:
            raise AssertionError(f"{actual!r} != {expected!r}")


class VoiceTests(unittest.TestCase):
    def test_command_runtime_runs_local_pipeline_and_removes_private_artifacts(self) -> None:
        commands = {
            "wake_capture": ["wake-capture", "{audio}"],
            "wake_detection": ["wake-detection", "{output}"],
            "speech_capture": ["speech-capture", "{audio}"],
            "transcription": ["transcription", "{output}"],
            "extraction": ["extraction", "{output}"],
            "success_sound": ["success-sound"],
            "error_sound": ["error-sound"],
            "speech_synthesis": ["synthesize", "{output}", "{text}"],
            "play_speech": ["play", "{audio}"],
        }
        controlled_commands = ControlledCommands()
        runtime = CommandVoiceRuntime(
            commands,
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
        runtime.report_success(event, 130.0)

        self.assertEqual(capture.audio, b"report audio")
        self.assertEqual(capture.started_on, date(2026, 8, 25))
        self.assertEqual(transcript, "I ate one egg")
        self.assertEqual(
            extraction,
            {"foods": [{"food": "egg", "quantity": 1, "measure": "large"}]},
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
        self.assertEqual(runtime.successful_event, event)
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
        self.assertIsNone(runtime.successful_event)
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

    def test_usda_timeout_creates_no_event_and_reports_before_final_deadline(self) -> None:
        runtime = ControlledVoiceRuntime()
        usda_search = TimingOutUsdaSearch([])
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
        self.assertEqual(runtime.failure_reason, "Processing took too long.")
        self.assertEqual(runtime.calls, ["capture", "transcribe", "extract", "failure"])


if __name__ == "__main__":
    unittest.main()