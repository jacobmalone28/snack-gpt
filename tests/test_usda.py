import unittest
from unittest.mock import patch
from urllib.error import URLError
from io import BytesIO

from snack_gpt.usda import FoodDataCentralSearch, UsdaError, _fetch_json


class FoodDataCentralSearchTests(unittest.TestCase):
    def test_malformed_responses_are_normalized(self) -> None:
        with patch("snack_gpt.usda.urlopen", return_value=BytesIO(b"not-json")):
            with self.assertRaisesRegex(UsdaError, "USDA is unavailable"):
                _fetch_json("/foods/search", {}, 1.0)

    def test_transport_failures_are_normalized_without_response_details(self) -> None:
        with patch(
            "snack_gpt.usda.urlopen",
            side_effect=URLError("private response detail"),
        ):
            with self.assertRaisesRegex(UsdaError, "USDA is unavailable") as raised:
                _fetch_json("/foods/search", {}, 1.0)

        self.assertNotIn("private response detail", str(raised.exception))

    def test_search_requests_share_one_timeout_budget(self) -> None:
        responses: dict[str, object] = {
            "/foods/search": {"foods": [{"fdcId": 20}]},
            "/food/20": {
                "fdcId": 20,
                "description": "Egg",
                "foodNutrients": [],
            },
        }
        request_timeouts: list[float] = []
        times = iter((100.0, 100.0, 110.0))

        def fetch_json(path: str, parameters: dict[str, str], timeout_seconds: float) -> object:
            request_timeouts.append(timeout_seconds)
            return responses[path]

        search = FoodDataCentralSearch(
            "secret",
            fetch_json=fetch_json,
            monotonic=lambda: next(times),
        )

        search.search("egg", timeout_seconds=15.0)

        self.assertEqual(request_timeouts, [15.0, 5.0])

    def test_returns_the_highest_ranked_complete_food(self) -> None:
        responses: dict[str, object] = {
            "/foods/search": {"foods": [{"fdcId": 10}, {"fdcId": 20}]},
            "/food/10": {
                "fdcId": 10,
                "description": "Incomplete egg",
                "foodNutrients": [],
            },
            "/food/20": {
                "fdcId": 20,
                "description": "Egg, whole, raw, fresh",
                "foodNutrients": [
                    {"nutrient": {"name": "Energy", "unitName": "kcal"}, "amount": 143},
                    {"nutrient": {"name": "Protein", "unitName": "g"}, "amount": 12.6},
                    {
                        "nutrient": {"name": "Carbohydrate, by difference", "unitName": "g"},
                        "amount": 0.72,
                    },
                    {"nutrient": {"name": "Total lipid (fat)", "unitName": "g"}, "amount": 9.51},
                ],
                "foodPortions": [
                    {
                        "gramWeight": 50,
                        "modifier": "large",
                        "portionDescription": "1 cup, cooked",
                        "measureUnit": {"name": "egg"},
                    }
                ],
            },
        }

        def fetch_json(path: str, parameters: dict[str, str], timeout_seconds: float) -> object:
            self.assertEqual(parameters["api_key"], "secret")
            self.assertGreater(timeout_seconds, 0)
            if path == "/foods/search":
                self.assertEqual(parameters["query"], "egg")
            return responses[path]

        search = FoodDataCentralSearch("secret", fetch_json=fetch_json)

        results = search.search("egg")

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.usda_food_id, "20")
        self.assertEqual(result.nutrients_per_100_grams["calories"], 143.0)
        self.assertEqual(result.measures["large"], 50.0)
        self.assertEqual(result.measures["egg"], 50.0)
        self.assertEqual(result.measures["1 cup, cooked"], 50.0)
        self.assertEqual(result.measures["cup"], 50.0)


if __name__ == "__main__":
    unittest.main()