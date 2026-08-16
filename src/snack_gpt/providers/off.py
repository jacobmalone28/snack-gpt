"""Open Food Facts provider."""

import json
import logging
from typing import Optional

import httpx

from snack_gpt.config import settings
from snack_gpt.providers import FoodLookupResult, FoodProvider

logger = logging.getLogger(__name__)


class OpenFoodFactsProvider(FoodProvider):
    """Provider for Open Food Facts API."""

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize Open Food Facts provider.

        Args:
            base_url: Base URL for the API. Uses settings if not provided.
        """
        self.base_url = base_url or settings.open_food_facts_api_url

    async def lookup_by_name(self, name: str) -> Optional[FoodLookupResult]:
        """Look up food by name in Open Food Facts."""
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                response = await client.get(
                    f"{self.base_url}/cgi/search.pl",
                    params={
                        "search_terms": name,
                        "page_size": 1,
                        "json": 1,
                    },
                )
                response.raise_for_status()

                data = response.json()
                if data.get("products"):
                    return self._parse_product_response(data["products"][0])

        except httpx.HTTPError as e:
            logger.error(f"Open Food Facts lookup failed for '{name}': {e}")

        return None

    async def lookup_by_barcode(self, barcode: str) -> Optional[FoodLookupResult]:
        """Look up food by barcode in Open Food Facts."""
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                response = await client.get(
                    f"{self.base_url}/api/v2/product/{barcode}.json",
                )
                response.raise_for_status()

                data = response.json()
                if data.get("product"):
                    return self._parse_product_response(data["product"])

        except httpx.HTTPError as e:
            logger.error(f"Open Food Facts lookup failed for barcode '{barcode}': {e}")

        return None

    @staticmethod
    def _parse_product_response(product_data: dict) -> Optional[FoodLookupResult]:  # type: ignore[type-arg]
        """
        Parse Open Food Facts product response into FoodLookupResult.

        Args:
            product_data: Raw product data from Open Food Facts API.

        Returns:
            FoodLookupResult or None if data is insufficient.
        """
        try:
            description = product_data.get("product_name", "")
            brands = product_data.get("brands", "")
            barcode = product_data.get("code")

            # Open Food Facts returns per 100g values
            nutrition = product_data.get("nutriments", {})
            calories_per_100g = nutrition.get("energy-kcal_100g", 0)
            protein_per_100g = nutrition.get("proteins_100g", 0)
            carbs_per_100g = nutrition.get("carbohydrates_100g", 0)
            fat_per_100g = nutrition.get("fat_100g", 0)
            fiber_per_100g = nutrition.get("fiber_100g", 0)

            return FoodLookupResult(
                description=description,
                brand=brands if brands else None,
                barcode=barcode,
                calories_per_gram=calories_per_100g / 100.0,
                protein_per_gram=protein_per_100g / 100.0,
                carbohydrate_per_gram=carbs_per_100g / 100.0,
                fat_per_gram=fat_per_100g / 100.0,
                fiber_per_gram=fiber_per_100g / 100.0,
                provider_key=f"off:{barcode}",
                raw_response=json.dumps(product_data),
            )

        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Failed to parse Open Food Facts response: {e}")
            return None
