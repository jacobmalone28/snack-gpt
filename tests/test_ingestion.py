from pathlib import Path
import tempfile
import unittest

from snack_gpt.ingestion import (
    FoodSearchResult,
    IngestionError,
    create_consumption_event,
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


class ControlledUsdaSearch:
    def __init__(self, results: list[FoodSearchResult]) -> None:
        self._results = results

    def search(self, query: str) -> list[FoodSearchResult]:
        return self._results


class IngestionTests(unittest.TestCase):
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
            "missing quantity": ("", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "zero quantity": ("0", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "negative quantity": ("-1", "grams", "2026-08-25", [COMPLETE_RESULT]),
            "unsupported measure": ("1", "bucket", "2026-08-25", [COMPLETE_RESULT]),
            "future day": ("1", "grams", "2999-01-01", [COMPLETE_RESULT]),
            "no complete result": ("1", "grams", "2026-08-25", [INCOMPLETE_RESULT]),
        }
        for name, (quantity, measure, day, results) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with Storage(Path(directory) / "events.sqlite3") as storage:
                    storage.initialize()
                    with self.assertRaisesRegex(IngestionError, ".+"):
                        create_consumption_event(
                            storage,
                            ControlledUsdaSearch(results),
                            food="egg",
                            quantity=quantity,
                            measure=measure,
                            day=day,
                        )
                    self.assertEqual(storage.list_consumption_events(), [])


if __name__ == "__main__":
    unittest.main()