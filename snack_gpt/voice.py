from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
import logging
import math
import time
from typing import Protocol, cast
from uuid import uuid4

from snack_gpt.ingestion import (
    ConsumptionReportItem,
    IngestionError,
    UsdaSearch,
    create_consumption_report,
)
from snack_gpt.storage import ConsumptionEvent, Storage
from snack_gpt.usda import UsdaError


VOICE_PROCESSING_TIMEOUT_SECONDS = 30.0
VOICE_FEEDBACK_TIMEOUT_SECONDS = 10.0
MIN_EXTRACTION_CONFIDENCE = 0.8
LOGGER = logging.getLogger(__name__)


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
    items: tuple[ExtractedFood, ...]
    confidence: float


@dataclass(frozen=True)
class CapturedSpeech:
    audio: bytes
    started_on: date
    utterance_id: str = ""

    def __post_init__(self) -> None:
        if not self.utterance_id:
            object.__setattr__(self, "utterance_id", str(uuid4()))


class VoiceRuntime(Protocol):
    def wait_for_wake_and_capture(self) -> CapturedSpeech: ...

    def transcribe(self, audio: bytes, deadline: float) -> str: ...

    def extract(self, transcript: str, deadline: float) -> object: ...

    def report_success(self, events: Sequence[ConsumptionEvent], deadline: float) -> None: ...

    def report_failure(self, reason: str, deadline: float) -> None: ...


def parse_consumption_report(value: object) -> ExtractedConsumptionReport:
    if not isinstance(value, dict):
        raise ExtractionError("extraction must contain foods and confidence")
    extraction = cast(dict[object, object], value)
    if set(extraction) != {"foods", "confidence"}:
        raise ExtractionError("extraction must contain foods and confidence")

    confidence = extraction["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ExtractionError("extraction confidence must be a finite number from zero to one")
    if confidence < MIN_EXTRACTION_CONFIDENCE:
        raise ExtractionError("I could not confidently identify every Food Quantity.")

    foods = extraction["foods"]
    if not isinstance(foods, list):
        raise ExtractionError("extraction must contain a foods list")
    food_items = cast(list[object], foods)
    if not food_items:
        raise ExtractionError("extraction must contain at least one food")

    return ExtractedConsumptionReport(
        tuple(_parse_extracted_food(item) for item in food_items),
        float(confidence),
    )


def _parse_extracted_food(raw_item: object) -> ExtractedFood:
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

    return ExtractedFood(
        food=food.strip(),
        quantity=float(quantity),
        measure=measure.strip(),
    )


def create_consumption_report_from_voice(
    storage: Storage,
    usda_search: UsdaSearch,
    runtime: VoiceRuntime,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    timer: Callable[[], float] = time.monotonic,
) -> list[ConsumptionEvent] | None:
    operation_id = str(uuid4())
    stage = "capture"
    stage_started = timer()
    try:
        capture = runtime.wait_for_wake_and_capture()
    except VoiceProcessingTimeout:
        _log_stage(operation_id, stage, stage_started, timer(), "failure", "timeout")
        deadline = monotonic() + VOICE_PROCESSING_TIMEOUT_SECONDS
        feedback_started = timer()
        runtime.report_failure("Processing took too long.", deadline)
        _log_stage(operation_id, "feedback", feedback_started, timer(), "success")
        return None
    except VoiceProcessingError as error:
        _log_stage(operation_id, stage, stage_started, timer(), "failure", "audio_unavailable")
        deadline = monotonic() + VOICE_PROCESSING_TIMEOUT_SECONDS
        feedback_started = timer()
        runtime.report_failure(str(error), deadline)
        _log_stage(operation_id, "feedback", feedback_started, timer(), "success")
        return None
    utterance_id = capture.utterance_id
    _log_stage(utterance_id, stage, stage_started, timer(), "success")
    final_deadline = monotonic() + VOICE_PROCESSING_TIMEOUT_SECONDS
    processing_deadline = final_deadline - VOICE_FEEDBACK_TIMEOUT_SECONDS
    try:
        stage = "transcription"
        stage_started = timer()
        transcript = runtime.transcribe(capture.audio, processing_deadline)
        _require_time_remaining(processing_deadline, monotonic)
        _log_stage(utterance_id, stage, stage_started, timer(), "success")
        stage = "extraction"
        stage_started = timer()
        report = parse_consumption_report(runtime.extract(transcript, processing_deadline))
        _require_time_remaining(processing_deadline, monotonic)
        _log_stage(utterance_id, stage, stage_started, timer(), "success")
        stage = "ingestion"
        stage_started = timer()
        events = create_consumption_report(
            storage,
            usda_search,
            items=[
                ConsumptionReportItem(item.food, str(item.quantity), item.measure)
                for item in report.items
            ],
            day=capture.started_on.isoformat(),
            timeout_seconds=processing_deadline - monotonic(),
            utterance_id=capture.utterance_id,
        )
        _require_time_remaining(processing_deadline, monotonic)
        _log_stage(utterance_id, stage, stage_started, timer(), "success")
    except (VoiceProcessingTimeout, TimeoutError) as error:
        _log_stage(utterance_id, stage, stage_started, timer(), "failure", _failure_category(error))
        feedback_started = timer()
        runtime.report_failure("Processing took too long.", final_deadline)
        _log_stage(utterance_id, "feedback", feedback_started, timer(), "success")
        return None
    except (ExtractionError, IngestionError, UsdaError, VoiceProcessingError) as error:
        _log_stage(utterance_id, stage, stage_started, timer(), "failure", _failure_category(error))
        feedback_started = timer()
        runtime.report_failure(str(error), final_deadline)
        _log_stage(utterance_id, "feedback", feedback_started, timer(), "success")
        return None
    feedback_started = timer()
    if not events:
        runtime.report_failure("This Consumption Report was already recorded.", final_deadline)
        _log_stage(utterance_id, "feedback", feedback_started, timer(), "duplicate")
        return None
    runtime.report_success(events, final_deadline)
    _log_stage(utterance_id, "feedback", feedback_started, timer(), "success")
    return events


def create_consumption_event_from_voice(
    storage: Storage,
    usda_search: UsdaSearch,
    runtime: VoiceRuntime,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    timer: Callable[[], float] = time.monotonic,
) -> ConsumptionEvent | None:
    events = create_consumption_report_from_voice(
        storage,
        usda_search,
        runtime,
        monotonic=monotonic,
        timer=timer,
    )
    return events[0] if events else None


def _failure_category(error: BaseException) -> str:
    if isinstance(error, (VoiceProcessingTimeout, TimeoutError)):
        return "timeout"
    if isinstance(error, ExtractionError):
        return "invalid_extraction"
    if isinstance(error, IngestionError):
        return "invalid_report"
    if isinstance(error, UsdaError):
        return "usda_unavailable"
    return "runtime"


def _log_stage(
    utterance_id: str,
    stage: str,
    started: float,
    finished: float,
    outcome: str,
    failure_category: str = "none",
) -> None:
    LOGGER.info(
        "voice_pipeline utterance_id=%s stage=%s duration_ms=%.1f outcome=%s failure_category=%s",
        utterance_id,
        stage,
        max(0.0, finished - started) * 1000,
        outcome,
        failure_category,
    )


def _require_time_remaining(
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    if monotonic() >= deadline:
        raise VoiceProcessingTimeout