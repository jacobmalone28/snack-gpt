"""Daily totals calculation service."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from snack_gpt.models.domain import (
    ConsumptionEntry,
    DailyTarget,
    PendingConsumption,
    Profile,
)
from snack_gpt.services.nutrition import Nutrition, NutritionCalculator


class DailyTotalsCalculator:
    """Calculate daily nutrition totals for a profile."""

    @staticmethod
    def get_daily_total(
        db: Session, profile_id: int, target_date: date
    ) -> tuple[Nutrition, Optional[Nutrition], bool]:
        """
        Get confirmed and pending nutrition totals for a day.

        Args:
            db: Database session.
            profile_id: Profile ID.
            target_date: Date to calculate totals for.

        Returns:
            Tuple of (confirmed_nutrition, pending_nutrition, has_pending).
            Pending nutrition is None if no pending items exist.
        """
        # Get profile timezone
        profile = db.execute(
            select(Profile).where(Profile.id == profile_id)
        ).scalar_one_or_none()

        if not profile:
            return Nutrition(0, 0, 0, 0, 0), None, False

        # Get all confirmed consumption entries for the day
        # (Using UTC assumption; in production should use profile timezone)
        day_start = datetime.combine(target_date, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        day_end = datetime.combine(target_date, datetime.max.time()).replace(
            tzinfo=timezone.utc
        )

        confirmed_entries = db.execute(
            select(ConsumptionEntry).where(
                and_(
                    ConsumptionEntry.profile_id == profile_id,
                    ConsumptionEntry.consumption_time >= day_start,
                    ConsumptionEntry.consumption_time <= day_end,
                    ConsumptionEntry.replaces_entry_id.is_(None),  # Not a correction
                )
            )
        ).scalars().all()

        # Calculate confirmed totals
        confirmed_nutrition_list: list[Nutrition] = [
            Nutrition(
                calories=float(entry.calories_snapshot),
                protein=float(entry.protein_snapshot),
                carbohydrate=float(entry.carbohydrate_snapshot),
                fat=float(entry.fat_snapshot),
                fiber=float(entry.fiber_snapshot),
            )
            for entry in confirmed_entries
        ]

        confirmed_total = NutritionCalculator.sum_nutrition(confirmed_nutrition_list)

        # Check for pending items
        pending_items = db.execute(
            select(PendingConsumption).where(
                and_(
                    PendingConsumption.profile_id == profile_id,
                    PendingConsumption.consumption_time >= day_start,
                    PendingConsumption.consumption_time <= day_end,
                )
            )
        ).scalars().all()

        has_pending = len(pending_items) > 0

        return confirmed_total, None, has_pending

    @staticmethod
    def get_daily_target(
        db: Session, profile_id: int, target_date: date
    ) -> Optional[Nutrition]:
        """
        Get the daily nutrition target for a profile on a specific date.

        Args:
            db: Database session.
            profile_id: Profile ID.
            target_date: Date to get target for.

        Returns:
            Nutrition representing the target, or None if not set.
        """
        target = db.execute(
            select(DailyTarget).where(
                and_(
                    DailyTarget.profile_id == profile_id,
                    func.date(DailyTarget.effective_date) <= target_date,
                )
            )
            .order_by(DailyTarget.effective_date.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not target:
            return None

        return Nutrition(
            calories=float(target.calories),
            protein=float(target.protein_grams),
            carbohydrate=float(target.carbohydrate_grams),
            fat=float(target.fat_grams),
            fiber=float(target.fiber_grams),
        )
