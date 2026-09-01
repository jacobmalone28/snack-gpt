from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from snack_gpt.ingestion import (
    ConsumptionReportItem,
    FoodSearchResult,
    IngestionError,
    correct_consumption_event,
    create_consumption_event,
    create_consumption_report,
)
from snack_gpt.storage import ConsumptionEvent, NutritionSnapshot, Storage


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
    def test_food_correction_replaces_the_usda_result_and_nutrition_snapshot(self) -> None:
        original = ConsumptionEvent(
            event_id="event-id",
            revision=1,
            day=date(2026, 8, 25),
            usda_food_id="20",
            food_description="Egg, whole, raw, fresh",
            quantity_value=1,
            quantity_measure="large",
            nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
        )
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                storage.create_consumption_event(original)
                usda_search = ControlledUsdaSearch([COOKED_RICE_RESULT])

                corrected = correct_consumption_event(
                    storage,
                    usda_search,
                    event_id=original.event_id,
                    expected_revision=1,
                    food="rice",
                    quantity="1",
                    measure="cup",
                    day="2026-08-25",
                )

        self.assertEqual(usda_search.queries, ["rice"])
        self.assertEqual(corrected.usda_food_id, "30")
        self.assertEqual(corrected.food_description, COOKED_RICE_RESULT.description)
        self.assertEqual(corrected.nutrition.calories, 260)

    def test_day_only_correction_preserves_the_nutrition_snapshot_without_usda(self) -> None:
        original = ConsumptionEvent(
            event_id="event-id",
            revision=1,
            day=date(2026, 8, 25),
            usda_food_id="20",
            food_description="Egg, whole, raw, fresh",
            quantity_value=1,
            quantity_measure="large",
            nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
        )
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                storage.create_consumption_event(original)

                corrected = correct_consumption_event(
                    storage,
                    None,
                    event_id=original.event_id,
                    expected_revision=1,
                    food=original.food_description,
                    quantity="1",
                    measure="large",
                    day="2026-08-26",
                )

                self.assertEqual(storage.list_consumption_events(), [corrected])

        self.assertEqual(corrected.revision, 2)
        self.assertEqual(corrected.day, date(2026, 8, 26))
        self.assertEqual(corrected.nutrition, original.nutrition)

    def test_future_day_correction_leaves_the_original_event_unchanged(self) -> None:
        original = ConsumptionEvent(
            event_id="event-id",
            revision=1,
            day=date.today(),
            usda_food_id="20",
            food_description="Egg, whole, raw, fresh",
            quantity_value=1,
            quantity_measure="large",
            nutrition=NutritionSnapshot(71.5, 6.3, 0.36, 4.755),
        )
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                storage.create_consumption_event(original)

                with self.assertRaisesRegex(IngestionError, "future day"):
                    correct_consumption_event(
                        storage,
                        None,
                        event_id=original.event_id,
                        expected_revision=1,
                        food=original.food_description,
                        quantity="1",
                        measure="large",
                        day=(date.today() + timedelta(days=1)).isoformat(),
                    )

                self.assertEqual(storage.list_consumption_events(), [original])

    def test_quantity_correction_refreshes_the_nutrition_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Storage(Path(directory) / "events.sqlite3") as storage:
                storage.initialize()
                usda_search = ControlledUsdaSearch([COMPLETE_RESULT])
                original = create_consumption_event(
                    storage,
                    usda_search,
                    food="egg",
                    quantity="1",
                    measure="large",
                    day="2026-08-25",
                )

                corrected = correct_consumption_event(
                    storage,
                    usda_search,
                    event_id=original.event_id,
                    expected_revision=1,
                    food=original.food_description,
                    quantity="2",
                    measure="large",
                    day="2026-08-25",
                )

        self.assertEqual(usda_search.queries, ["egg", original.food_description])
        self.assertEqual(corrected.revision, 2)
        self.assertEqual(corrected.quantity_value, 2)
        self.assertEqual(corrected.nutrition.calories, 143)

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