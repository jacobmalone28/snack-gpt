from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import uuid4

from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage


class IngestionError(ValueError):
    """Raised when a Consumption Event cannot be validated and created."""


@dataclass(frozen=True)
class FoodSearchResult:
    usda_food_id: str
    description: str
    nutrients_per_100_grams: Mapping[str, float]
    measures: Mapping[str, float]


class UsdaSearch(Protocol):
    def search(self, query: str) -> Sequence[FoodSearchResult]: ...


def create_consumption_event(
    storage: Storage,
    usda_search: UsdaSearch,
    *,
    food: str,
    quantity: str,
    measure: str,
    day: str,
) -> ConsumptionEvent:
    query = food.strip()
    if not query:
        raise IngestionError("Enter a food to search for.")

    try:
        quantity_value = float(quantity)
    except ValueError as error:
        raise IngestionError("Food quantity must be a number greater than zero.") from error
    if quantity_value <= 0:
        raise IngestionError("Food quantity must be greater than zero.")

    normalized_measure = measure.strip().lower()
    try:
        event_day = date.fromisoformat(day)
    except ValueError as error:
        raise IngestionError("Choose a valid calendar day.") from error
    if event_day > date.today():
        raise IngestionError("Consumption Events cannot be created for a future day.")

    complete_result = next(
        (
            result
            for result in usda_search.search(query)
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
        grams_per_measure = complete_result.measures.get(normalized_measure)
        if grams_per_measure is None:
            raise IngestionError("That quantity measure is not recognized by USDA.")
        grams = quantity_value * grams_per_measure
        stored_measure = normalized_measure

    scale = grams / 100.0
    nutrients = complete_result.nutrients_per_100_grams
    event = ConsumptionEvent(
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
    storage.create_consumption_event(event)
    return event