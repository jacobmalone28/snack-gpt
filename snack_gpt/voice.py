from dataclasses import dataclass
import math
from typing import cast


class ExtractionError(ValueError):
    """Raised when Needle output is not a valid Consumption Report."""


@dataclass(frozen=True)
class ExtractedFood:
    food: str
    quantity: float
    measure: str


@dataclass(frozen=True)
class ExtractedConsumptionReport:
    item: ExtractedFood


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