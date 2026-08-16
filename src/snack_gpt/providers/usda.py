"""USDA FoodData Central provider."""

import json
import logging
from typing import Optional

import httpx

from snack_gpt.config import settings
from snack_gpt.providers import FoodLookupResult, FoodProvider

logger = logging.getLogger(__name__)


class USDAProvider(FoodProvider):
    """Provider for USDA FoodData Central API."""

    BASE_URL = "https://fdc.nal.usda.gov/api/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize USDA provider.

        Args:
            api_key: USDA API key. Uses settings.usda_api_key if not provided.
        """
        self.api_key = api_key or settings.usda_api_key
        if not self.api_key:
            logger.warning("USDA API key not configured")

    async def lookup_by_name(self, name: str) -> Optional[FoodLookupResult]:
        """Look up food by name in USDA FoodData Central."""
        if not self.api_key:
            logger.warning("Cannot lookup USDA food without API key")
            return None

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                response = await client.get(
                    f"{self.BASE_URL}/foods/search",
                    params={
                        "query": name,
                        "pageSize": 1,
                        "api_key": self.api_key,
                    },
                )
                response.raise_for_status()

                data = response.json()
                if data.get("foods"):
                    return self._parse_food_response(data["foods"][0])

        except httpx.HTTPError as e:
            logger.error(f"USDA lookup failed for '{name}': {e}")

        return None

    async def lookup_by_barcode(self, barcode: str) -> Optional[FoodLookupResult]:
        """Look up food by barcode in USDA FoodData Central."""
        if not self.api_key:
            logger.warning("Cannot lookup USDA food without API key")
            return None

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                response = await client.get(
                    f"{self.BASE_URL}/foods/search",
                    params={
                        "query": barcode,
                        "pageSize": 1,
                        "api_key": self.api_key,
                    },
                )
                response.raise_for_status()

                data = response.json()
                if data.get("foods"):
                    return self._parse_food_response(data["foods"][0])

        except httpx.HTTPError as e:
            logger.error(f"USDA lookup failed for barcode '{barcode}': {e}")

        return None

    @staticmethod
    def _parse_food_response(food_data: dict) -> Optional[FoodLookupResult]:  # type: ignore[type-arg]
        """
        Parse USDA food response into FoodLookupResult.

        Args:
            food_data: Raw food data from USDA API.

        Returns:
            FoodLookupResult or None if data is insufficient.
        """
        try:
            description = food_data.get("description", "")
            nutrients = {n["nutrientName"]: n.get("value", 0) for n in food_data.get("foodNutrients", [])}

            # USDA returns per 100g values
            calories_per_100g = nutrients.get("Energy", 0)
            protein_per_100g = nutrients.get("Protein", 0)
            carbs_per_100g = nutrients.get("Carbohydrate, by difference", 0)
            fat_per_100g = nutrients.get("Total lipid (fat)", 0)
            fiber_per_100g = nutrients.get("Fiber, total dietary", 0)

            return FoodLookupResult(
                description=description,
                barcode=food_data.get("gtinUpc"),
                calories_per_gram=calories_per_100g / 100.0,
                protein_per_gram=protein_per_100g / 100.0,
                carbohydrate_per_gram=carbs_per_100g / 100.0,
                fat_per_gram=fat_per_100g / 100.0,
                fiber_per_gram=fiber_per_100g / 100.0,
                provider_key=f"usda:{food_data.get('fdcId')}",
                raw_response=json.dumps(food_data),
            )

        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Failed to parse USDA response: {e}")
            return None
