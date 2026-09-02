from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
import math
import time
from typing import Protocol
from uuid import uuid4

from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage


class IngestionError(ValueError):
    """Raised when a Consumption Event cannot be validated and created."""


class ConsumptionEventConflict(IngestionError):
    """Raised when a Consumption Event mutation uses a stale revision."""


@dataclass(frozen=True)
class FoodSearchResult:
    usda_food_id: str
    description: str
    nutrients_per_100_grams: Mapping[str, float]
    measures: Mapping[str, float]


@dataclass(frozen=True)
class ConsumptionReportItem:
    food: str
    quantity: str
    measure: str


class UsdaSearch(Protocol):
    def search(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> Sequence[FoodSearchResult]: ...


def _resolve_measure(
    measures: Mapping[str, float],
    requested_measure: str,
) -> tuple[str, float] | None:
    normalized_measures = {
        alias.strip().lower(): weight
        for alias, weight in measures.items()
        if alias.strip() and weight > 0
    }
    exact_weight = normalized_measures.get(requested_measure)
    if exact_weight is not None:
        return requested_measure, exact_weight

    if requested_measure.endswith("s") and not requested_measure.endswith("ss"):
        variants = {requested_measure[:-1]}
    else:
        variants = {f"{requested_measure}s"}
    matches = [
        (alias, weight)
        for alias, weight in normalized_measures.items()
        if alias in variants
    ]
    if len({weight for _, weight in matches}) != 1:
        return None
    return matches[0] if matches else None


def create_consumption_event(
    storage: Storage,
    usda_search: UsdaSearch,
    *,
    food: str,
    quantity: str,
    measure: str,
    day: str,
    timeout_seconds: float | None = None,
) -> ConsumptionEvent:
    return create_consumption_report(
        storage,
        usda_search,
        items=[ConsumptionReportItem(food, quantity, measure)],
        day=day,
        timeout_seconds=timeout_seconds,
    )[0]


def create_consumption_report(
    storage: Storage,
    usda_search: UsdaSearch,
    *,
    items: Sequence[ConsumptionReportItem],
    day: str,
    timeout_seconds: float | None = None,
    utterance_id: str | None = None,
) -> list[ConsumptionEvent]:
    if not items:
        raise IngestionError("Enter at least one food and Food Quantity.")

    try:
        event_day = date.fromisoformat(day)
    except ValueError as error:
        raise IngestionError("Choose a valid calendar day.") from error
    if event_day > date.today():
        raise IngestionError("Consumption Events cannot be created for a future day.")

    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    events: list[ConsumptionEvent] = []
    for item in items:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("USDA search deadline expired")
        events.append(
            _build_consumption_event(
                usda_search,
                item=item,
                event_day=event_day,
                timeout_seconds=remaining,
            )
        )
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("USDA search deadline expired")
    created = storage.create_consumption_events(events, utterance_id=utterance_id)
    return events if created else []


def correct_consumption_event(
    storage: Storage,
    usda_search: UsdaSearch | None,
    *,
    event_id: str,
    expected_revision: int,
    food: str,
    quantity: str,
    measure: str,
    day: str,
) -> ConsumptionEvent:
    existing = storage.get_consumption_event(event_id)
    if existing is None:
        raise IngestionError("Consumption Event was not found.")
    if existing.revision != expected_revision:
        raise ConsumptionEventConflict(
            "Consumption Event changed; refresh and try again."
        )

    try:
        event_day = date.fromisoformat(day)
    except ValueError as error:
        raise IngestionError("Choose a valid calendar day.") from error
    if event_day > date.today():
        raise IngestionError("Consumption Events cannot be corrected to a future day.")

    query = food.strip()
    try:
        quantity_value = float(quantity)
    except ValueError as error:
        raise IngestionError("Food quantity must be a number greater than zero.") from error
    normalized_measure = measure.strip().lower()
    food_quantity_changed = (
        query != existing.food_description
        or quantity_value != existing.quantity_value
        or normalized_measure != existing.quantity_measure
    )
    if food_quantity_changed:
        if usda_search is None:
            raise IngestionError("USDA food search is not configured.")
        candidate = _build_consumption_event(
            usda_search,
            item=ConsumptionReportItem(food, quantity, measure),
            event_day=event_day,
        )
        corrected = replace(
            candidate,
            event_id=existing.event_id,
            revision=existing.revision + 1,
        )
    else:
        corrected = replace(
            existing,
            revision=existing.revision + 1,
            day=event_day,
        )

    if not storage.update_consumption_event(corrected, expected_revision):
        raise ConsumptionEventConflict(
            "Consumption Event changed; refresh and try again."
        )
    return corrected


def _build_consumption_event(
    usda_search: UsdaSearch,
    *,
    item: ConsumptionReportItem,
    event_day: date,
    timeout_seconds: float | None = None,
) -> ConsumptionEvent:
    food = item.food
    quantity = item.quantity
    measure = item.measure
    query = food.strip()
    if not query:
        raise IngestionError("Enter a food to search for.")

    try:
        quantity_value = float(quantity)
    except ValueError as error:
        raise IngestionError("Food quantity must be a number greater than zero.") from error
    if not math.isfinite(quantity_value) or quantity_value <= 0:
        raise IngestionError("Food quantity must be greater than zero.")

    normalized_measure = measure.strip().lower()
    if not normalized_measure:
        raise IngestionError("Enter a Food Quantity measure.")

    complete_result = next(
        (
            result
            for result in usda_search.search(query, timeout_seconds=timeout_seconds)
            if {"calories", "protein", "carbohydrates", "fat"}
            <= result.nutrients_per_100_grams.keys()
        ),
        None,
    )
    if complete_result is None:
        raise IngestionError(
            "No USDA result for that food contains complete nutrition information."
        )

    if normalized_measure in {"g", "gram", "grams"}:
        grams = quantity_value
        stored_measure = "grams"
    else:
        resolved_measure = _resolve_measure(complete_result.measures, normalized_measure)
        if resolved_measure is None:
            raise IngestionError("That quantity measure is not recognized by USDA.")
        stored_measure, grams_per_measure = resolved_measure
        grams = quantity_value * grams_per_measure

    scale = grams / 100.0
    nutrients = complete_result.nutrients_per_100_grams
    return ConsumptionEvent(
        event_id=str(uuid4()),
        revision=1,
        day=event_day,
        usda_food_id=complete_result.usda_food_id,
        food_description=complete_result.description,
        quantity_value=quantity_value,
        quantity_measure=stored_measure,
        nutrition=NutritionSnapshot(
            calories=nutrients["calories"] * scale,
            protein=nutrients["protein"] * scale,
            carbohydrates=nutrients["carbohydrates"] * scale,
            fat=nutrients["fat"] * scale,
        ),
    )