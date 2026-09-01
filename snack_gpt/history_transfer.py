from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import json
import math
from typing import cast

from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage


class HistoryImportError(ValueError):
    pass


@dataclass(frozen=True)
class ImportResult:
    imported_count: int
    skipped_count: int
    conflict_ids: tuple[str, ...]


def export_history(storage: Storage) -> bytes:
    document = {
        "schema_version": 1,
        "consumption_events": [
            _event_document(event) for event in storage.list_consumption_events()
        ],
    }
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def import_history(storage: Storage, document: bytes) -> ImportResult:
    events = _parse_document(document)
    existing_events = {
        event.event_id: event for event in storage.list_consumption_events()
    }
    new_events: list[ConsumptionEvent] = []
    skipped_count = 0
    conflict_ids: list[str] = []
    for event in events:
        existing = existing_events.get(event.event_id)
        if existing is None:
            new_events.append(event)
        elif existing == event:
            skipped_count += 1
        else:
            conflict_ids.append(event.event_id)

    storage.create_consumption_events(new_events)
    return ImportResult(
        imported_count=len(new_events),
        skipped_count=skipped_count,
        conflict_ids=tuple(conflict_ids),
    )


def _event_document(event: ConsumptionEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "revision": event.revision,
        "day": event.day.isoformat(),
        "usda_food_id": event.usda_food_id,
        "food_description": event.food_description,
        "food_quantity": {
            "value": event.quantity_value,
            "measure": event.quantity_measure,
        },
        "nutrition_snapshot": {
            "calories": event.nutrition.calories,
            "protein": event.nutrition.protein,
            "carbohydrates": event.nutrition.carbohydrates,
            "fat": event.nutrition.fat,
        },
    }


def _parse_document(document: bytes) -> list[ConsumptionEvent]:
    try:
        value = json.loads(document)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HistoryImportError("History import is not valid JSON.") from error

    root = _object(
        value,
        {"schema_version", "consumption_events"},
        "history document",
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise HistoryImportError("History import has an unsupported schema version.")
    raw_events = root["consumption_events"]
    if not isinstance(raw_events, list):
        raise HistoryImportError("consumption_events must be an array.")

    events = [_parse_event(value, index) for index, value in enumerate(raw_events)]
    event_ids = [event.event_id for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise HistoryImportError("History import contains duplicate event IDs.")
    return events


def _parse_event(value: object, index: int) -> ConsumptionEvent:
    path = f"consumption_events[{index}]"
    event = _object(
        value,
        {
            "event_id",
            "revision",
            "day",
            "usda_food_id",
            "food_description",
            "food_quantity",
            "nutrition_snapshot",
        },
        path,
    )
    quantity = _object(
        event["food_quantity"], {"value", "measure"}, f"{path}.food_quantity"
    )
    nutrition = _object(
        event["nutrition_snapshot"],
        {"calories", "protein", "carbohydrates", "fat"},
        f"{path}.nutrition_snapshot",
    )
    day_value = _string(event["day"], f"{path}.day")
    try:
        event_day = date.fromisoformat(day_value)
    except ValueError as error:
        raise HistoryImportError(f"{path}.day must be an ISO calendar day.") from error

    revision = event["revision"]
    if type(revision) is not int or revision < 1:
        raise HistoryImportError(f"{path}.revision must be a positive integer.")
    return ConsumptionEvent(
        event_id=_string(event["event_id"], f"{path}.event_id"),
        revision=revision,
        day=event_day,
        usda_food_id=_string(event["usda_food_id"], f"{path}.usda_food_id"),
        food_description=_string(
            event["food_description"], f"{path}.food_description"
        ),
        quantity_value=_number(
            quantity["value"], f"{path}.food_quantity.value", positive=True
        ),
        quantity_measure=_string(
            quantity["measure"], f"{path}.food_quantity.measure"
        ),
        nutrition=NutritionSnapshot(
            calories=_number(
                nutrition["calories"], f"{path}.nutrition_snapshot.calories"
            ),
            protein=_number(
                nutrition["protein"], f"{path}.nutrition_snapshot.protein"
            ),
            carbohydrates=_number(
                nutrition["carbohydrates"],
                f"{path}.nutrition_snapshot.carbohydrates",
            ),
            fat=_number(nutrition["fat"], f"{path}.nutrition_snapshot.fat"),
        ),
    )


def _object(value: object, keys: set[str], path: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoryImportError(f"{path} must be an object.")
    result = cast(dict[str, object], value)
    if set(result) != keys:
        raise HistoryImportError(f"{path} has missing or unexpected fields.")
    return result


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise HistoryImportError(f"{path} must be a non-empty string.")
    return value


def _number(value: object, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HistoryImportError(f"{path} must be a finite number.")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        requirement = "positive" if positive else "non-negative"
        raise HistoryImportError(f"{path} must be a finite {requirement} number.")
    return result