"""Tests for nutrition calculation utilities."""

import pytest

from snack_gpt.services.nutrition import Nutrition, NutritionCalculator


class TestNutrition:
    """Tests for Nutrition dataclass."""

    def test_nutrition_creation(self):
        """Test creating a Nutrition object."""
        n = Nutrition(calories=100, protein=5, carbohydrate=20, fat=3, fiber=2)
        assert n.calories == 100
        assert n.protein == 5
        assert n.carbohydrate == 20
        assert n.fat == 3
        assert n.fiber == 2

    def test_nutrition_addition(self):
        """Test adding two Nutrition objects."""
        n1 = Nutrition(calories=100, protein=5, carbohydrate=20, fat=3, fiber=2)
        n2 = Nutrition(calories=50, protein=2, carbohydrate=10, fat=1, fiber=1)
        
        result = n1 + n2
        
        assert result.calories == 150
        assert result.protein == 7
        assert result.carbohydrate == 30
        assert result.fat == 4
        assert result.fiber == 3

    def test_nutrition_multiplication(self):
        """Test multiplying Nutrition by a scalar."""
        n = Nutrition(calories=100, protein=5, carbohydrate=20, fat=3, fiber=2)
        
        result = n * 2
        
        assert result.calories == 200
        assert result.protein == 10
        assert result.carbohydrate == 40
        assert result.fat == 6
        assert result.fiber == 4

    def test_nutrition_multiplication_fractional(self):
        """Test multiplying Nutrition by a fractional scalar."""
        n = Nutrition(calories=100, protein=5, carbohydrate=20, fat=3, fiber=2)
        
        result = n * 0.5
        
        assert result.calories == 50
        assert result.protein == 2.5
        assert result.carbohydrate == 10
        assert result.fat == 1.5
        assert result.fiber == 1

    def test_nutrition_right_multiplication(self):
        """Test right multiplication (scalar * Nutrition)."""
        n = Nutrition(calories=100, protein=5, carbohydrate=20, fat=3, fiber=2)
        
        result = 2 * n
        
        assert result.calories == 200
        assert result.protein == 10


class TestNutritionCalculator:
    """Tests for NutritionCalculator."""

    def test_from_per_gram_values(self):
        """Test calculating nutrition from per-gram values."""
        # Chicken breast: ~1.65 cal/g, 0.31g protein, 0g carbs, 0.036g fat, 0g fiber per gram
        nutrition = NutritionCalculator.from_per_gram_values(
            grams=100,
            calories_per_gram=1.65,
            protein_per_gram=0.31,
            carbohydrate_per_gram=0.0,
            fat_per_gram=0.036,
            fiber_per_gram=0.0,
        )
        
        assert nutrition.calories == 165
        assert nutrition.protein == 31
        assert nutrition.carbohydrate == 0
        assert abs(nutrition.fat - 3.6) < 0.001
        assert nutrition.fiber == 0

    def test_sum_empty_list(self):
        """Test summing an empty list of nutrition."""
        result = NutritionCalculator.sum_nutrition([])
        
        assert result.calories == 0
        assert result.protein == 0
        assert result.carbohydrate == 0
        assert result.fat == 0
        assert result.fiber == 0

    def test_sum_single_nutrition(self):
        """Test summing a single nutrition."""
        n = Nutrition(calories=100, protein=5, carbohydrate=20, fat=3, fiber=2)
        result = NutritionCalculator.sum_nutrition([n])
        
        assert result == n

    def test_sum_multiple_nutrition(self):
        """Test summing multiple nutrition values."""
        n1 = Nutrition(calories=100, protein=5, carbohydrate=20, fat=3, fiber=2)
        n2 = Nutrition(calories=150, protein=10, carbohydrate=30, fat=5, fiber=3)
        n3 = Nutrition(calories=50, protein=2, carbohydrate=10, fat=1, fiber=1)
        
        result = NutritionCalculator.sum_nutrition([n1, n2, n3])
        
        assert result.calories == 300
        assert result.protein == 17
        assert result.carbohydrate == 60
        assert result.fat == 9
        assert result.fiber == 6

    def test_round_macros(self):
        """Test rounding nutrition macros."""
        n = Nutrition(
            calories=123.456,
            protein=5.678,
            carbohydrate=20.111,
            fat=3.999,
            fiber=2.0005,
        )
        
        result = NutritionCalculator.round_macros(n, decimal_places=1)
        
        assert result.calories == 123.5
        assert result.protein == 5.7
        assert result.carbohydrate == 20.1
        assert result.fat == 4.0
        assert result.fiber == 2.0

    def test_round_macros_zero_decimal_places(self):
        """Test rounding nutrition macros to integers."""
        n = Nutrition(
            calories=123.6,
            protein=5.4,
            carbohydrate=20.5,
            fat=3.1,
            fiber=2.9,
        )
        
        result = NutritionCalculator.round_macros(n, decimal_places=0)
        
        assert result.calories == 124
        assert result.protein == 5
        assert result.carbohydrate == 20 or result.carbohydrate == 21  # Floating point
        assert result.fat == 3
        assert result.fiber == 3


class TestNutritionIntegration:
    """Integration tests for nutrition calculations."""

    def test_meal_nutrition_calculation(self):
        """Test calculating nutrition for a complete meal."""
        # Meal: 100g chicken + 150g rice
        chicken = NutritionCalculator.from_per_gram_values(
            grams=100,
            calories_per_gram=1.65,
            protein_per_gram=0.31,
            carbohydrate_per_gram=0.0,
            fat_per_gram=0.036,
            fiber_per_gram=0.0,
        )
        
        rice = NutritionCalculator.from_per_gram_values(
            grams=150,
            calories_per_gram=1.30,
            protein_per_gram=0.027,
            carbohydrate_per_gram=0.28,
            fat_per_gram=0.003,
            fiber_per_gram=0.004,
        )
        
        meal = chicken + rice
        
        assert meal.calories == 165 + 195
        assert abs(meal.protein - (31 + 4.05)) < 0.001
        assert abs(meal.carbohydrate - (0 + 42)) < 0.001
