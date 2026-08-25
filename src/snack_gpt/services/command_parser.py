"""Command parsing service for converting transcripts to structured commands."""

import json
import re
from dataclasses import asdict, dataclass
from typing import Optional

from snack_gpt.models.voice import ParsedCommand


@dataclass
class ParseResult:
    """Result of parsing a transcript."""

    command_type: str
    foods: list[dict[str, object]]
    confidence: float
    requires_clarification: bool
    clarification_reason: str


class CommandParser:
    """Parse voice transcripts into structured commands."""

    # Pattern for "I ate X grams of Y" or "consumed X Y"
    CONSUMPTION_PATTERNS = [
        # "I ate 200 grams of chicken"
        r"(?:i\s+)?(?:ate|consumed|had)\s+(\d+(?:\.\d+)?)\s*(grams?|g|oz|ounces?|lbs?|pounds?|cups?|tbsps?|tsps?)\s+(?:of\s+)?(.+?)(?:\s+(?:and|also|plus)|$)",
        # "200g of chicken"
        r"(\d+(?:\.\d+)?)\s*(g|grams?|oz|ounces?|lbs?|pounds?|cups?|tbsps?|tsps?)\s+(?:of\s+)?(.+?)(?:\s+(?:and|also|plus)|$)",
        # "a cup of rice"
        r"(?:a|an|one|two|three|four|five)\s+(cup|tbsp|tsp|piece|slice|bowl|plate)\s+(?:of\s+)?(.+?)(?:\s+(?:and|also|plus)|$)",
        # "chicken 150g"
        r"(.+?)\s+(\d+(?:\.\d+)?)\s*(g|grams?|oz|ounces?|lbs?|pounds?)(?:\s+(?:and|also|plus)|$)",
    ]

    # Commands that don't consume food
    COMMAND_KEYWORDS = {
        "undo": ["undo", "revert", "cancel", "oops"],
        "skip": ["skip", "nevermind", "forget it"],
        "clear": ["clear", "delete", "remove"],
        "list": ["list", "show", "what", "read"],
        "done": ["done", "confirm", "finished"],
    }

    def __init__(self) -> None:
        """Initialize the parser."""
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.CONSUMPTION_PATTERNS]

    def parse(self, transcript: str) -> ParseResult:
        """
        Parse a transcript into a command.

        Args:
            transcript: User's spoken or typed command.

        Returns:
            ParseResult with command_type, foods, confidence, and clarification flags.
        """
        transcript = transcript.strip()
        if not transcript:
            return ParseResult(
                command_type="error",
                foods=[],
                confidence=0.0,
                requires_clarification=True,
                clarification_reason="Empty transcript",
            )

        # Check for non-consumption commands first
        for cmd_type, keywords in self.COMMAND_KEYWORDS.items():
            if any(kw in transcript.lower() for kw in keywords):
                return ParseResult(
                    command_type=cmd_type,
                    foods=[],
                    confidence=0.95,
                    requires_clarification=False,
                    clarification_reason="",
                )

        # Try to extract foods from consumption patterns
        foods = []
        matches = []

        for pattern in self.compiled_patterns:
            for match in pattern.finditer(transcript):
                matches.append(match)

        if not matches:
            return ParseResult(
                command_type="unclear",
                foods=[],
                confidence=0.0,
                requires_clarification=True,
                clarification_reason=f"Could not parse food from: {transcript}",
            )

        # Process matches to extract structured food data
        for match in matches:
            groups = match.groups()

            # Pattern matching - try to extract quantity, unit, food name
            if len(groups) == 3 and re.fullmatch(r"\d+(?:\.\d+)?", groups[0]):
                # Most patterns: quantity, unit, food name
                quantity_str = groups[0]
                unit = groups[1]
                food_name = groups[2]
            elif len(groups) == 3:
                # Food-first pattern: food name, quantity, unit
                food_name = groups[0]
                quantity_str = groups[1]
                unit = groups[2]
            elif len(groups) == 2:
                # Some patterns might have just quantity and food
                quantity_str = groups[0]
                unit = "grams"
                food_name = groups[1]
            else:
                continue

            try:
                quantity = float(quantity_str)
            except (ValueError, IndexError):
                continue

            foods.append(
                {
                    "description": food_name.strip().lower(),
                    "quantity": quantity,
                    "unit": unit.strip().lower(),
                    "confidence": 0.85,  # Extracted patterns are relatively high confidence
                }
            )

        if not foods:
            return ParseResult(
                command_type="unclear",
                foods=[],
                confidence=0.0,
                requires_clarification=True,
                clarification_reason=f"Could not extract foods from: {transcript}",
            )

        return ParseResult(
            command_type="consume",
            foods=foods,
            confidence=0.9,
            requires_clarification=False,
            clarification_reason="",
        )

    def validate_foods(self, foods: list[dict[str, object]]) -> tuple[bool, str]:
        """
        Validate extracted foods have required fields.

        Args:
            foods: List of extracted food dicts.

        Returns:
            (is_valid, error_message)
        """
        for food in foods:
            if not food.get("description"):
                return False, "Food name missing"
            quantity = food.get("quantity", 0)
            if not isinstance(quantity, (int, float)) or quantity <= 0:
                return False, "Quantity must be positive"
            if not food.get("unit"):
                return False, "Unit missing"

        return True, ""
