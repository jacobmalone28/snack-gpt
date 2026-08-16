"""Nutrition arithmetic and calculation services."""

from dataclasses import dataclass


@dataclass
class Nutrition:
    """Immutable nutrition snapshot."""

    calories: float
    protein: float  # grams
    carbohydrate: float  # grams
    fat: float  # grams
    fiber: float  # grams

    def __add__(self, other: "Nutrition") -> "Nutrition":
        """Add two nutrition values."""
        if not isinstance(other, Nutrition):
            return NotImplemented
        return Nutrition(
            calories=self.calories + other.calories,
            protein=self.protein + other.protein,
            carbohydrate=self.carbohydrate + other.carbohydrate,
            fat=self.fat + other.fat,
            fiber=self.fiber + other.fiber,
        )

    def __mul__(self, scalar: float) -> "Nutrition":
        """Multiply nutrition by a scalar."""
        return Nutrition(
            calories=self.calories * scalar,
            protein=self.protein * scalar,
            carbohydrate=self.carbohydrate * scalar,
            fat=self.fat * scalar,
            fiber=self.fiber * scalar,
        )

    def __rmul__(self, scalar: float) -> "Nutrition":
        """Right multiply nutrition by a scalar."""
        return self.__mul__(scalar)


class NutritionCalculator:
    """Calculate nutrition values from food references and quantities."""

    @staticmethod
    def from_per_gram_values(
        grams: float,
        calories_per_gram: float,
        protein_per_gram: float,
        carbohydrate_per_gram: float,
        fat_per_gram: float,
        fiber_per_gram: float,
    ) -> Nutrition:
        """
        Calculate total nutrition from per-gram values.

        Args:
            grams: Total weight in grams.
            calories_per_gram: Calories per gram.
            protein_per_gram: Protein grams per gram of food.
            carbohydrate_per_gram: Carbohydrate grams per gram of food.
            fat_per_gram: Fat grams per gram of food.
            fiber_per_gram: Fiber grams per gram of food.

        Returns:
            Nutrition snapshot for the specified quantity.
        """
        return Nutrition(
            calories=grams * calories_per_gram,
            protein=grams * protein_per_gram,
            carbohydrate=grams * carbohydrate_per_gram,
            fat=grams * fat_per_gram,
            fiber=grams * fiber_per_gram,
        )

    @staticmethod
    def sum_nutrition(nutrition_list: list[Nutrition]) -> Nutrition:
        """
        Sum multiple nutrition values.

        Args:
            nutrition_list: List of Nutrition objects.

        Returns:
            Combined Nutrition.
        """
        if not nutrition_list:
            return Nutrition(calories=0.0, protein=0.0, carbohydrate=0.0, fat=0.0, fiber=0.0)

        result = nutrition_list[0]
        for nutrition in nutrition_list[1:]:
            result = result + nutrition

        return result

    @staticmethod
    def round_macros(nutrition: Nutrition, decimal_places: int = 1) -> Nutrition:
        """
        Round nutrition macros to specified decimal places.

        Args:
            nutrition: Nutrition to round.
            decimal_places: Number of decimal places.

        Returns:
            Nutrition with rounded values.
        """
        multiplier = 10 ** decimal_places
        return Nutrition(
            calories=round(nutrition.calories * multiplier) / multiplier,
            protein=round(nutrition.protein * multiplier) / multiplier,
            carbohydrate=round(nutrition.carbohydrate * multiplier) / multiplier,
            fat=round(nutrition.fat * multiplier) / multiplier,
            fiber=round(nutrition.fiber * multiplier) / multiplier,
        )
