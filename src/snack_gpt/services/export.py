"""Data export utilities for JSON and CSV formats."""

import csv
import json
from datetime import datetime, timezone
from io import StringIO
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from snack_gpt.models.domain import (
    ConsumptionEntry,
    DailyTarget,
    FoodAlias,
    FoodReference,
    Portion,
    Profile,
)


class DataExporter:
    """Export profile data in various formats."""

    @staticmethod
    def export_consumption_history_json(
        db: Session, profile_id: int
    ) -> str:
        """
        Export consumption history as JSON.

        Args:
            db: Database session.
            profile_id: Profile ID to export.

        Returns:
            JSON string containing consumption history.
        """
        entries = db.execute(
            select(ConsumptionEntry)
            .where(ConsumptionEntry.profile_id == profile_id)
            .order_by(ConsumptionEntry.consumption_time.desc())
        ).scalars().all()

        data = {
            "profile_id": profile_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entries": [
                {
                    "id": entry.id,
                    "food": entry.food_reference.canonical_name if entry.food_reference else None,
                    "quantity_grams": entry.quantity_grams,
                    "consumption_time": entry.consumption_time.isoformat(),
                    "calories": entry.calories_snapshot,
                    "protein_g": entry.protein_snapshot,
                    "carbohydrate_g": entry.carbohydrate_snapshot,
                    "fat_g": entry.fat_snapshot,
                    "fiber_g": entry.fiber_snapshot,
                }
                for entry in entries
            ],
        }

        return json.dumps(data, indent=2)

    @staticmethod
    def export_consumption_history_csv(
        db: Session, profile_id: int
    ) -> str:
        """
        Export consumption history as CSV.

        Args:
            db: Database session.
            profile_id: Profile ID to export.

        Returns:
            CSV string containing consumption history.
        """
        entries = db.execute(
            select(ConsumptionEntry)
            .where(ConsumptionEntry.profile_id == profile_id)
            .order_by(ConsumptionEntry.consumption_time.desc())
        ).scalars().all()

        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "consumption_time",
                "food",
                "quantity_grams",
                "calories",
                "protein_g",
                "carbohydrate_g",
                "fat_g",
                "fiber_g",
            ],
        )

        writer.writeheader()
        for entry in entries:
            writer.writerow({
                "consumption_time": entry.consumption_time.isoformat(),
                "food": entry.food_reference.canonical_name if entry.food_reference else "",
                "quantity_grams": entry.quantity_grams,
                "calories": entry.calories_snapshot,
                "protein_g": entry.protein_snapshot,
                "carbohydrate_g": entry.carbohydrate_snapshot,
                "fat_g": entry.fat_snapshot,
                "fiber_g": entry.fiber_snapshot,
            })

        return output.getvalue()

    @staticmethod
    def export_food_database_json(
        db: Session, profile_id: int
    ) -> str:
        """
        Export food aliases and references as JSON.

        Args:
            db: Database session.
            profile_id: Profile ID to export.

        Returns:
            JSON string containing food data.
        """
        aliases = db.execute(
            select(FoodAlias).where(FoodAlias.profile_id == profile_id)
        ).scalars().all()

        data = {
            "profile_id": profile_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "food_aliases": [
                {
                    "id": alias.id,
                    "phrase": alias.phrase,
                    "barcode": alias.barcode,
                    "food": {
                        "canonical_name": alias.food_reference.canonical_name,
                        "brand": alias.food_reference.brand,
                        "preparation": alias.food_reference.preparation,
                        "nutrition_source": alias.food_reference.nutrition_source,
                        "calories_per_gram": alias.food_reference.calories_per_gram,
                        "protein_per_gram": alias.food_reference.protein_per_gram,
                        "carbohydrate_per_gram": alias.food_reference.carbohydrate_per_gram,
                        "fat_per_gram": alias.food_reference.fat_per_gram,
                        "fiber_per_gram": alias.food_reference.fiber_per_gram,
                    },
                }
                for alias in aliases
            ],
        }

        return json.dumps(data, indent=2)

    @staticmethod
    def export_daily_targets_json(
        db: Session, profile_id: int
    ) -> str:
        """
        Export daily nutrition targets as JSON.

        Args:
            db: Database session.
            profile_id: Profile ID to export.

        Returns:
            JSON string containing daily targets.
        """
        targets = db.execute(
            select(DailyTarget)
            .where(DailyTarget.profile_id == profile_id)
            .order_by(DailyTarget.effective_date.desc())
        ).scalars().all()

        data = {
            "profile_id": profile_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "daily_targets": [
                {
                    "effective_date": target.effective_date.date().isoformat(),
                    "calories": target.calories,
                    "protein_grams": target.protein_grams,
                    "carbohydrate_grams": target.carbohydrate_grams,
                    "fat_grams": target.fat_grams,
                    "fiber_grams": target.fiber_grams,
                }
                for target in targets
            ],
        }

        return json.dumps(data, indent=2)
