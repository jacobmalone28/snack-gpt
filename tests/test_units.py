"""Tests for unit conversion utilities."""

import pytest

from snack_gpt.services.units import UnitConverter


class TestUnitConverterStandardConversions:
    """Tests for standard unit conversions."""

    def test_grams_to_grams(self):
        """Test gram to gram conversion."""
        converter = UnitConverter()
        assert converter.to_grams(100, "g") == 100.0

    def test_kilograms_to_grams(self):
        """Test kilogram to gram conversion."""
        converter = UnitConverter()
        assert converter.to_grams(1, "kg") == 1000.0

    def test_ounces_to_grams(self):
        """Test ounce to gram conversion."""
        converter = UnitConverter()
        result = converter.to_grams(1, "oz")
        assert abs(result - 28.3495) < 0.001

    def test_pounds_to_grams(self):
        """Test pound to gram conversion."""
        converter = UnitConverter()
        result = converter.to_grams(1, "lb")
        assert abs(result - 453.592) < 0.001

    def test_cups_to_grams(self):
        """Test cup to gram conversion."""
        converter = UnitConverter()
        result = converter.to_grams(1, "cup")
        assert abs(result - 236.588) < 0.001

    def test_tablespoons_to_grams(self):
        """Test tablespoon to gram conversion."""
        converter = UnitConverter()
        result = converter.to_grams(1, "tablespoon")
        assert abs(result - 14.787) < 0.001

    def test_teaspoons_to_grams(self):
        """Test teaspoon to gram conversion."""
        converter = UnitConverter()
        result = converter.to_grams(1, "tsp")
        assert abs(result - 4.929) < 0.001

    def test_case_insensitive(self):
        """Test that conversions are case-insensitive."""
        converter = UnitConverter()
        assert converter.to_grams(100, "GRAMS") == 100.0
        assert converter.to_grams(100, "Grams") == 100.0
        assert converter.to_grams(1, "OZ") == converter.to_grams(1, "oz")

    def test_unknown_unit_raises_error(self):
        """Test that unknown units raise ValueError."""
        converter = UnitConverter()
        with pytest.raises(ValueError, match="Unknown unit"):
            converter.to_grams(100, "unknown_unit")


class TestUnitConverterFoodSpecific:
    """Tests for food-specific portion conversions."""

    def test_food_specific_piece_conversion(self):
        """Test food-specific conversion for pieces."""
        portions = {"piece": 150.0}  # 1 piece = 150 grams
        converter = UnitConverter(portions)
        assert converter.to_grams(2, "piece") == 300.0

    def test_food_specific_slice_conversion(self):
        """Test food-specific conversion for slices."""
        portions = {"slice": 30.0}  # 1 slice = 30 grams
        converter = UnitConverter(portions)
        assert converter.to_grams(4, "slice") == 120.0

    def test_piece_without_food_specific_raises_error(self):
        """Test that piece conversion requires food-specific data."""
        converter = UnitConverter()
        with pytest.raises(ValueError, match="requires food-specific"):
            converter.to_grams(1, "piece")

    def test_food_specific_overrides_standard(self):
        """Test that food-specific portions override standard conversions."""
        # ML is normally 1:1 with water, but we can override
        portions = {"ml": 1.2}  # This food is denser than water
        converter = UnitConverter(portions)
        assert converter.to_grams(100, "ml") == 120.0


class TestUnitConverterReverse:
    """Tests for reverse conversion (grams to units)."""

    def test_grams_from_grams(self):
        """Test reverse gram conversion."""
        converter = UnitConverter()
        assert converter.from_grams(100, "g") == 100.0

    def test_grams_from_ounces(self):
        """Test reverse ounce conversion."""
        converter = UnitConverter()
        result = converter.from_grams(28.3495, "oz")
        assert abs(result - 1.0) < 0.001

    def test_grams_from_cups(self):
        """Test reverse cup conversion."""
        converter = UnitConverter()
        result = converter.from_grams(236.588, "cup")
        assert abs(result - 1.0) < 0.001

    def test_grams_from_food_specific(self):
        """Test reverse conversion with food-specific portions."""
        portions = {"piece": 150.0}
        converter = UnitConverter(portions)
        assert converter.from_grams(300, "piece") == 2.0
