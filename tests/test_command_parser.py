"""Tests for command parser service."""

import pytest

from snack_gpt.services.command_parser import CommandParser


class TestCommandParserBasicCommands:
    """Test parsing of basic command types."""

    def setup_method(self) -> None:
        """Set up parser for each test."""
        self.parser = CommandParser()

    def test_parse_undo_command(self) -> None:
        """Test parsing undo command."""
        result = self.parser.parse("undo")
        assert result.command_type == "undo"
        assert result.confidence > 0.9
        assert not result.requires_clarification

    def test_parse_undo_variants(self) -> None:
        """Test various undo phrasings."""
        variants = ["undo", "revert", "cancel", "oops"]
        for variant in variants:
            result = self.parser.parse(variant)
            assert result.command_type == "undo", f"Failed for: {variant}"

    def test_parse_skip_command(self) -> None:
        """Test parsing skip command."""
        result = self.parser.parse("skip")
        assert result.command_type == "skip"

    def test_parse_list_command(self) -> None:
        """Test parsing list command."""
        result = self.parser.parse("list")
        assert result.command_type == "list"

    def test_parse_done_command(self) -> None:
        """Test parsing done/confirm command."""
        result = self.parser.parse("done")
        assert result.command_type == "done"


class TestCommandParserConsumptionPatterns:
    """Test parsing of food consumption patterns."""

    def setup_method(self) -> None:
        """Set up parser for each test."""
        self.parser = CommandParser()

    def test_parse_i_ate_pattern(self) -> None:
        """Test 'I ate X grams of Y' pattern."""
        result = self.parser.parse("I ate 200 grams of chicken")
        assert result.command_type == "consume"
        assert len(result.foods) > 0
        assert result.foods[0]["description"] == "chicken"
        assert result.foods[0]["quantity"] == 200
        assert "grams" in result.foods[0]["unit"].lower()

    def test_parse_simple_quantity_food(self) -> None:
        """Test parsing quantity + food."""
        result = self.parser.parse("150g of rice")
        assert result.command_type == "consume"
        assert len(result.foods) > 0
        assert result.foods[0]["description"] == "rice"
        assert result.foods[0]["quantity"] == 150

    def test_parse_ounces(self) -> None:
        """Test parsing ounces."""
        result = self.parser.parse("I ate 6 ounces of steak")
        assert result.command_type == "consume"
        assert len(result.foods) > 0
        assert "ounce" in result.foods[0]["unit"].lower()

    def test_parse_cups(self) -> None:
        """Test parsing cups."""
        result = self.parser.parse("2 cups of milk")
        assert result.command_type == "consume"
        assert len(result.foods) > 0
        assert "cup" in result.foods[0]["unit"].lower()

    def test_parse_food_first_quantity_last(self) -> None:
        """Test parsing with food name first, quantity last."""
        result = self.parser.parse("chicken 150g")
        assert result.command_type == "consume"
        assert len(result.foods) > 0

    def test_parse_decimal_quantity(self) -> None:
        """Test parsing decimal quantities."""
        result = self.parser.parse("2.5 cups of oatmeal")
        assert result.command_type == "consume"
        assert len(result.foods) > 0
        assert result.foods[0]["quantity"] == 2.5

    def test_parse_multiple_foods(self) -> None:
        """Test parsing multiple foods in one statement."""
        result = self.parser.parse("I ate 200 grams of chicken and 150g of rice")
        assert result.command_type == "consume"
        assert len(result.foods) >= 2


class TestCommandParserEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self) -> None:
        """Set up parser for each test."""
        self.parser = CommandParser()

    def test_parse_empty_transcript(self) -> None:
        """Test parsing empty transcript."""
        result = self.parser.parse("")
        assert result.command_type == "error"
        assert result.confidence == 0.0
        assert result.requires_clarification

    def test_parse_whitespace_only(self) -> None:
        """Test parsing whitespace-only transcript."""
        result = self.parser.parse("   \t\n  ")
        assert result.command_type == "error"

    def test_parse_unclear_input(self) -> None:
        """Test parsing input that doesn't match any pattern."""
        result = self.parser.parse("hello world")
        assert result.requires_clarification
        assert result.confidence == 0.0

    def test_parse_case_insensitive(self) -> None:
        """Test that parsing is case-insensitive."""
        result1 = self.parser.parse("I ATE 200 GRAMS OF CHICKEN")
        result2 = self.parser.parse("i ate 200 grams of chicken")

        assert result1.command_type == result2.command_type
        assert len(result1.foods) == len(result2.foods)
        assert result1.foods[0]["description"].lower() == result2.foods[0]["description"].lower()

    def test_parse_invalid_quantity(self) -> None:
        """Test handling of invalid quantity."""
        result = self.parser.parse("ate abc grams of chicken")
        # Should fail to parse if quantity is invalid
        assert result.requires_clarification or result.command_type != "consume"


class TestCommandParserValidation:
    """Test food validation."""

    def setup_method(self) -> None:
        """Set up parser for each test."""
        self.parser = CommandParser()

    def test_validate_complete_food(self) -> None:
        """Test validation of complete food entry."""
        foods = [{"description": "chicken", "quantity": 200, "unit": "grams", "confidence": 0.9}]
        is_valid, msg = self.parser.validate_foods(foods)
        assert is_valid
        assert msg == ""

    def test_validate_missing_description(self) -> None:
        """Test validation fails for missing description."""
        foods = [{"description": "", "quantity": 200, "unit": "grams"}]
        is_valid, msg = self.parser.validate_foods(foods)
        assert not is_valid

    def test_validate_missing_quantity(self) -> None:
        """Test validation fails for missing quantity."""
        foods = [{"description": "chicken", "unit": "grams"}]
        is_valid, msg = self.parser.validate_foods(foods)
        assert not is_valid

    def test_validate_zero_quantity(self) -> None:
        """Test validation fails for zero quantity."""
        foods = [{"description": "chicken", "quantity": 0, "unit": "grams"}]
        is_valid, msg = self.parser.validate_foods(foods)
        assert not is_valid

    def test_validate_negative_quantity(self) -> None:
        """Test validation fails for negative quantity."""
        foods = [{"description": "chicken", "quantity": -100, "unit": "grams"}]
        is_valid, msg = self.parser.validate_foods(foods)
        assert not is_valid

    def test_validate_missing_unit(self) -> None:
        """Test validation fails for missing unit."""
        foods = [{"description": "chicken", "quantity": 200}]
        is_valid, msg = self.parser.validate_foods(foods)
        assert not is_valid

    def test_validate_multiple_foods(self) -> None:
        """Test validation of multiple foods."""
        foods = [
            {"description": "chicken", "quantity": 200, "unit": "grams"},
            {"description": "rice", "quantity": 150, "unit": "grams"},
        ]
        is_valid, msg = self.parser.validate_foods(foods)
        assert is_valid
