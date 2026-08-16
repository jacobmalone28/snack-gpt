"""Unit conversion utilities."""

from decimal import Decimal
from typing import Dict, Optional


class UnitConverter:
    """Converts between cooking measurement units."""

    # Standard conversions to grams
    # https://www.usda.gov/nal/wicbreastfeeding/docs/FoodWeightedFormulas.pdf
    # Standard cooking measurements
    STANDARD_CONVERSIONS: Dict[str, Optional[float]] = {
        "g": 1.0,
        "grams": 1.0,
        "gram": 1.0,
        "kg": 1000.0,
        "kilograms": 1000.0,
        "oz": 28.3495,
        "ounce": 28.3495,
        "ounces": 28.3495,
        "lb": 453.592,
        "lbs": 453.592,
        "pound": 453.592,
        "pounds": 453.592,
        "ml": 1.0,  # Approximation: water density
        "milliliter": 1.0,
        "milliliters": 1.0,
        "l": 1000.0,
        "liter": 1000.0,
        "liters": 1000.0,
        "cup": 236.588,  # US cup
        "cups": 236.588,
        "tablespoon": 14.787,  # US tbsp (3 tsp)
        "tablespoons": 14.787,
        "tbsp": 14.787,
        "teaspoon": 4.929,  # US tsp
        "teaspoons": 4.929,
        "tsp": 4.929,
        "piece": None,  # Requires food-specific portion
        "pieces": None,
        "slice": None,  # Requires food-specific portion
        "slices": None,
        "serving": None,  # Requires food-specific portion
        "servings": None,
    }

    def __init__(self, food_portions: Optional[Dict[str, float]] = None):
        """
        Initialize converter.

        Args:
            food_portions: Optional dict mapping unit names to grams for specific foods.
        """
        self.food_portions = food_portions or {}

    def to_grams(self, quantity: float, unit: str) -> float:
        """
        Convert a quantity in the given unit to grams.

        Args:
            quantity: The amount to convert.
            unit: The unit name (case-insensitive).

        Returns:
            The quantity in grams.

        Raises:
            ValueError: If unit is unknown or requires food-specific information.
        """
        normalized_unit = unit.lower().strip()

        # First check food-specific portions
        if normalized_unit in self.food_portions:
            return quantity * self.food_portions[normalized_unit]

        # Then check standard conversions
        if normalized_unit not in self.STANDARD_CONVERSIONS:
            raise ValueError(f"Unknown unit: {unit}")

        conversion_factor = self.STANDARD_CONVERSIONS[normalized_unit]
        if conversion_factor is None:
            raise ValueError(
                f"Unit '{unit}' requires food-specific portion definition. "
                f"Please provide a portion for this unit."
            )

        return quantity * conversion_factor

    def from_grams(self, grams: float, unit: str) -> float:
        """
        Convert grams to the given unit.

        Args:
            grams: The amount in grams.
            unit: The target unit name (case-insensitive).

        Returns:
            The quantity in the target unit.

        Raises:
            ValueError: If unit is unknown or requires food-specific information.
        """
        normalized_unit = unit.lower().strip()

        # First check food-specific portions
        if normalized_unit in self.food_portions:
            return grams / self.food_portions[normalized_unit]

        # Then check standard conversions
        if normalized_unit not in self.STANDARD_CONVERSIONS:
            raise ValueError(f"Unknown unit: {unit}")

        conversion_factor = self.STANDARD_CONVERSIONS[normalized_unit]
        if conversion_factor is None:
            raise ValueError(
                f"Unit '{unit}' requires food-specific portion definition. "
                f"Cannot convert from this unit without food-specific information."
            )

        return grams / conversion_factor
