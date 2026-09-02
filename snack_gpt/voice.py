from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import math
import time
from typing import Protocol, cast

from snack_gpt.ingestion import IngestionError, UsdaSearch, create_consumption_event
from snack_gpt.storage import ConsumptionEvent, Storage


VOICE_PROCESSING_TIMEOUT_SECONDS = 30.0
VOICE_FEEDBACK_TIMEOUT_SECONDS = 10.0


class ExtractionError(ValueError):
    """Raised when Needle output is not a valid Consumption Report."""


class VoiceProcessingTimeout(Exception):
    pass


class VoiceProcessingError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedFood:
    food: str
    quantity: float
    measure: str


@dataclass(frozen=True)
class ExtractedConsumptionReport:
    item: ExtractedFood


@dataclass(frozen=True)
class CapturedSpeech:
    audio: bytes
    started_on: date


class VoiceRuntime(Protocol):
    def wait_for_wake_and_capture(self) -> CapturedSpeech: ...

    def transcribe(self, audio: bytes, deadline: float) -> str: ...

    def extract(self, transcript: str, deadline: float) -> object: ...

    def report_success(self, event: ConsumptionEvent, deadline: float) -> None: ...

    def report_failure(self, reason: str, deadline: float) -> None: ...


def parse_consumption_report(value: object) -> ExtractedConsumptionReport:
    if not isinstance(value, dict):
        raise ExtractionError("extraction must contain only a foods list")
    extraction = cast(dict[object, object], value)
    if set(extraction) != {"foods"}:
        raise ExtractionError("extraction must contain only a foods list")

    foods = extraction["foods"]
    if not isinstance(foods, list):
        raise ExtractionError("extraction must contain exactly one food")
    food_items = cast(list[object], foods)
    if len(food_items) != 1:
        raise ExtractionError("extraction must contain exactly one food")

    raw_item = food_items[0]
    if not isinstance(raw_item, dict):
        raise ExtractionError("extracted food must contain food, quantity, and measure")
    item = cast(dict[object, object], raw_item)
    if set(item) != {"food", "quantity", "measure"}:
        raise ExtractionError("extracted food must contain food, quantity, and measure")

    food = item["food"]
    if not isinstance(food, str) or not food.strip():
        raise ExtractionError("extracted food must be non-blank text")

    quantity = item["quantity"]
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, (int, float))
        or not math.isfinite(quantity)
        or quantity <= 0
    ):
        raise ExtractionError("extracted quantity must be a finite number greater than zero")

    measure = item["measure"]
    if not isinstance(measure, str) or not measure.strip():
        raise ExtractionError("extracted measure must be non-blank text")

    return ExtractedConsumptionReport(
        item=ExtractedFood(
            food=food.strip(),
            quantity=float(quantity),
            measure=measure.strip(),
        )
    )


def create_consumption_event_from_voice(
    storage: Storage,
    usda_search: UsdaSearch,
    runtime: VoiceRuntime,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> ConsumptionEvent | None:
    try:
        capture = runtime.wait_for_wake_and_capture()
    except VoiceProcessingError as error:
        deadline = monotonic() + VOICE_PROCESSING_TIMEOUT_SECONDS
        runtime.report_failure(str(error), deadline)
        return None
    final_deadline = monotonic() + VOICE_PROCESSING_TIMEOUT_SECONDS
    processing_deadline = final_deadline - VOICE_FEEDBACK_TIMEOUT_SECONDS
    try:
        transcript = runtime.transcribe(capture.audio, processing_deadline)
        _require_time_remaining(processing_deadline, monotonic)
        report = parse_consumption_report(runtime.extract(transcript, processing_deadline))
        _require_time_remaining(processing_deadline, monotonic)
        event = create_consumption_event(
            storage,
            usda_search,
            food=report.item.food,
            quantity=str(report.item.quantity),
            measure=report.item.measure,
            day=capture.started_on.isoformat(),
            timeout_seconds=processing_deadline - monotonic(),
        )
        _require_time_remaining(processing_deadline, monotonic)
    except (VoiceProcessingTimeout, TimeoutError):
        runtime.report_failure("Processing took too long.", final_deadline)
        return None
    except (ExtractionError, IngestionError, VoiceProcessingError) as error:
        runtime.report_failure(str(error), final_deadline)
        return None
    runtime.report_success(event, final_deadline)
    return event


def _require_time_remaining(
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    if monotonic() >= deadline:
        raise VoiceProcessingTimeout