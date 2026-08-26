import unittest

from snack_gpt.usda import FoodDataCentralSearch


class FoodDataCentralSearchTests(unittest.TestCase):
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
                    {"gramWeight": 50, "modifier": "large", "measureUnit": {"name": "egg"}}
                ],
            },
        }

        def fetch_json(path: str, parameters: dict[str, str]) -> object:
            self.assertEqual(parameters["api_key"], "secret")
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


if __name__ == "__main__":
    unittest.main()