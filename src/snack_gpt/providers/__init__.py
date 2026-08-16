"""Provider interfaces for food data lookup."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FoodLookupResult:
    """Result from a food lookup."""

    description: str
    brand: Optional[str] = None
    barcode: Optional[str] = None
    calories_per_gram: float = 0.0
    protein_per_gram: float = 0.0
    carbohydrate_per_gram: float = 0.0
    fat_per_gram: float = 0.0
    fiber_per_gram: float = 0.0
    provider_key: Optional[str] = None
    raw_response: Optional[str] = None


class FoodProvider(ABC):
    """Abstract base class for food data providers."""

    @abstractmethod
    async def lookup_by_name(self, name: str) -> Optional[FoodLookupResult]:
        """
        Look up food by name.

        Args:
            name: The food name to search for.

        Returns:
            FoodLookupResult if found, None otherwise.
        """
        pass

    @abstractmethod
    async def lookup_by_barcode(self, barcode: str) -> Optional[FoodLookupResult]:
        """
        Look up food by barcode.

        Args:
            barcode: The barcode/UPC to search for.

        Returns:
            FoodLookupResult if found, None otherwise.
        """
        pass
