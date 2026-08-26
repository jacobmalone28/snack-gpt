from collections.abc import Callable, Mapping
import json
from typing import cast
from urllib.parse import urlencode
from urllib.request import urlopen

from snack_gpt.ingestion import FoodSearchResult


FetchJson = Callable[[str, dict[str, str]], object]


class FoodDataCentralSearch:
    def __init__(self, api_key: str, fetch_json: FetchJson | None = None) -> None:
        self._api_key = api_key
        self._fetch_json = fetch_json or _fetch_json

    def search(self, query: str) -> list[FoodSearchResult]:
        response = _as_mapping(
            self._fetch_json(
                "/foods/search",
                {"api_key": self._api_key, "query": query, "pageSize": "25"},
            )
        )
        if response is None:
            return []

        foods = _as_list(response.get("foods"))
        if foods is None:
            return []
        for food in foods:
            summary = _as_mapping(food)
            if summary is None:
                continue
            food_id = summary.get("fdcId")
            if not isinstance(food_id, (int, str)):
                continue
            details = _as_mapping(
                self._fetch_json(
                    f"/food/{food_id}", {"api_key": self._api_key}
                )
            )
            result = _food_search_result(details)
            if result is not None:
                return [result]
        return []


def _food_search_result(
    details: Mapping[str, object] | None,
) -> FoodSearchResult | None:
    if details is None:
        return None
    food_id = details.get("fdcId")
    description = details.get("description")
    if not isinstance(food_id, (int, str)) or not isinstance(description, str):
        return None

    nutrients = _nutrients(details.get("foodNutrients"))
    if len(nutrients) != 4:
        return None
    return FoodSearchResult(
        usda_food_id=str(food_id),
        description=description,
        nutrients_per_100_grams=nutrients,
        measures=_measures(details.get("foodPortions")),
    )


def _nutrients(value: object) -> dict[str, float]:
    nutrients: dict[str, float] = {}
    items = _as_list(value)
    if items is None:
        return nutrients
    names = {
        "protein": "protein",
        "carbohydrate, by difference": "carbohydrates",
        "total lipid (fat)": "fat",
    }
    for item in items:
        food_nutrient = _as_mapping(item)
        if food_nutrient is None:
            continue
        nutrient = _as_mapping(food_nutrient.get("nutrient"))
        amount = food_nutrient.get("amount")
        if nutrient is None or not isinstance(amount, (int, float)):
            continue
        name = nutrient.get("name")
        unit = nutrient.get("unitName")
        if not isinstance(name, str):
            continue
        normalized_name = name.lower()
        if normalized_name == "energy" and isinstance(unit, str) and unit.lower() == "kcal":
            nutrients.setdefault("calories", float(amount))
        elif normalized_name in names:
            nutrients.setdefault(names[normalized_name], float(amount))
    return nutrients


def _measures(value: object) -> dict[str, float]:
    measures: dict[str, float] = {}
    items = _as_list(value)
    if items is None:
        return measures
    for item in items:
        portion = _as_mapping(item)
        if portion is None:
            continue
        gram_weight = portion.get("gramWeight")
        if not isinstance(gram_weight, (int, float)) or gram_weight <= 0:
            continue
        aliases = [portion.get("modifier"), portion.get("portionDescription")]
        measure_unit = _as_mapping(portion.get("measureUnit"))
        if measure_unit is not None:
            aliases.append(measure_unit.get("name"))
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                measures.setdefault(alias.strip().lower(), float(gram_weight))
    return measures


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        return None
    return cast(dict[str, object], mapping)


def _as_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast(list[object], value)


def _fetch_json(path: str, parameters: dict[str, str]) -> object:
    url = f"https://api.nal.usda.gov/fdc/v1{path}?{urlencode(parameters)}"
    with urlopen(url, timeout=15) as response:
        result: object = json.load(response)
    return result