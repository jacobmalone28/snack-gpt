from pathlib import Path
import tempfile
import unittest

from snack_gpt.ingestion import (
    ConsumptionReportItem,
    FoodSearchResult,
    IngestionError,
    create_consumption_event,
    create_consumption_report,
)
from snack_gpt.storage import Storage


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
INCOMPLETE_RESULT = FoodSearchResult(
    usda_food_id="10",
    description="Incomplete egg",
    nutrients_per_100_grams={"calories": 100.0},
    measures={"large": 40.0},
)
COOKED_RICE_RESULT = FoodSearchResult(
    usda_food_id="30",
    description="Rice, white, long-grain, regular, cooked",
    nutrients_per_100_grams={
        "calories": 130.0,
        "protein": 2.69,
        "carbohydrates": 28.17,
        "fat": 0.28,
    },
    measures={"cup": 200.0},
)


class ControlledUsdaSearch:
    def __init__(self, results: list[FoodSearchResult]) -> None:
        self._results = results
        self.queries: list[str] = []

    def search(self, query: str) -> list[FoodSearchResult]:
        self.queries.append(query)
        return self._results


class IngestionTests(unittest.TestCase):
    def test_consumption_report_is_not_stored_when_any_item_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()

                with self.assertRaisesRegex(IngestionError, "not recognized"):
                    create_consumption_report(
                        storage,
                        ControlledUsdaSearch([COMPLETE_RESULT]),
                        items=[
                            ConsumptionReportItem("egg", "1", "large"),
                            ConsumptionReportItem("egg", "1", "bucket"),
                        ],
                        day="2026-08-25",
                    )

                self.assertEqual(storage.list_consumption_events(), [])

    def test_preserves_food_qualifiers_and_normalizes_plural_measure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                usda_search = ControlledUsdaSearch([COOKED_RICE_RESULT])

                event = create_consumption_event(
                    storage,
                    usda_search,
                    food=" white rice cooked ",
                    quantity="0.75",
                    measure=" Cups ",
                    day="2026-08-25",
                )

        self.assertEqual(usda_search.queries, ["white rice cooked"])
        self.assertEqual(event.quantity_value, 0.75)
        self.assertEqual(event.quantity_measure, "cup")
        self.assertEqual(event.nutrition.calories, 195.0)

    def test_selects_the_highest_ranked_complete_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                event = create_consumption_event(
                    storage,
                    ControlledUsdaSearch([INCOMPLETE_RESULT, COMPLETE_RESULT]),
                    food="egg",
                    quantity="100",
                    measure="grams",
                    day="2026-08-25",
                )

        self.assertEqual(event.usda_food_id, "20")
        self.assertEqual(event.nutrition.calories, 143.0)

    def test_invalid_submissions_create_no_event(self) -> None:
        cases = {
            "blank food": (" ", "1", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "missing quantity": ("egg", "", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "nonnumeric quantity": ("egg", "one", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "zero quantity": ("egg", "0", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "negative quantity": ("egg", "-1", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "nan quantity": ("egg", "nan", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "infinite quantity": ("egg", "inf", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "blank measure": ("egg", "1", " ", "2026-08-25", [COMPLETE_RESULT]),
            "unsupported measure": ("egg", "1", "bucket", "2026-08-25", [COMPLETE_RESULT]),
            "future day": ("egg", "1", "grams", "2999-01-01", [COMPLETE_RESULT]),
            "no complete result": ("egg", "1", "grams", "2026-08-25", [INCOMPLETE_RESULT]),
        }
        for name, (food, quantity, measure, day, results) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with Storage(Path(directory) / "events.sqlite3") as storage:
                    storage.initialize()
                    with self.assertRaisesRegex(IngestionError, ".+"):
                        create_consumption_event(
                            storage,
                            ControlledUsdaSearch(results),
                            food=food,
                            quantity=quantity,
                            measure=measure,
                            day=day,
                        )
                    self.assertEqual(storage.list_consumption_events(), [])


if __name__ == "__main__":
    unittest.main()