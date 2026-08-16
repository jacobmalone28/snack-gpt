"""Tests for daily totals calculation."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snack_gpt.db import Base
from snack_gpt.models.domain import (
    ConsumptionEntry,
    DailyTarget,
    FoodReference,
    PendingConsumption,
    Profile,
)
from snack_gpt.services.nutrition import Nutrition
from snack_gpt.services.totals import DailyTotalsCalculator


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


class TestDailyTotalsCalculator:
    """Tests for DailyTotalsCalculator."""

    def test_get_daily_total_empty(self, test_db):
        """Test getting totals for a day with no entries."""
        profile = Profile(name="Test User", timezone="UTC")
        test_db.add(profile)
        test_db.commit()

        confirmed, pending, has_pending = DailyTotalsCalculator.get_daily_total(
            test_db, profile.id, date.today()
        )

        assert confirmed.calories == 0
        assert confirmed.protein == 0
        assert has_pending is False

    def test_get_daily_total_with_entries(self, test_db):
        """Test getting totals for a day with consumption entries."""
        # Create profile and food
        profile = Profile(name="Test User", timezone="UTC")
        test_db.add(profile)
        test_db.commit()

        food = FoodReference(
            canonical_name="Chicken",
            nutrition_source="usda",
            calories_per_gram=1.65,
            protein_per_gram=0.31,
            carbohydrate_per_gram=0.0,
            fat_per_gram=0.036,
            fiber_per_gram=0.0,
        )
        test_db.add(food)
        test_db.commit()

        # Create consumption entry
        today = date.today()
        consumption_time = datetime.combine(today, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        entry = ConsumptionEntry(
            profile_id=profile.id,
            food_reference_id=food.id,
            quantity_grams=100,
            consumption_time=consumption_time,
            calories_snapshot=165,
            protein_snapshot=31,
            carbohydrate_snapshot=0,
            fat_snapshot=3.6,
            fiber_snapshot=0,
        )
        test_db.add(entry)
        test_db.commit()

        confirmed, pending, has_pending = DailyTotalsCalculator.get_daily_total(
            test_db, profile.id, today
        )

        assert confirmed.calories == 165
        assert confirmed.protein == 31
        assert has_pending is False

    def test_get_daily_total_with_pending(self, test_db):
        """Test that pending items are detected."""
        profile = Profile(name="Test User", timezone="UTC")
        test_db.add(profile)
        test_db.commit()

        today = date.today()
        consumption_time = datetime.combine(today, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        pending = PendingConsumption(
            profile_id=profile.id,
            original_description="Unknown food",
            quantity_description="50 grams",
            consumption_time=consumption_time,
        )
        test_db.add(pending)
        test_db.commit()

        confirmed, pending_nut, has_pending = DailyTotalsCalculator.get_daily_total(
            test_db, profile.id, today
        )

        assert has_pending is True

    def test_get_daily_target(self, test_db):
        """Test getting the daily nutrition target."""
        profile = Profile(name="Test User", timezone="UTC")
        test_db.add(profile)
        test_db.commit()

        target_date = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        target = DailyTarget(
            profile_id=profile.id,
            effective_date=target_date,
            calories=2000,
            protein_grams=150,
            carbohydrate_grams=250,
            fat_grams=65,
            fiber_grams=30,
        )
        test_db.add(target)
        test_db.commit()

        result = DailyTotalsCalculator.get_daily_target(test_db, profile.id, date.today())

        assert result is not None
        assert result.calories == 2000
        assert result.protein == 150

    def test_get_daily_target_none(self, test_db):
        """Test getting daily target when none is set."""
        profile = Profile(name="Test User", timezone="UTC")
        test_db.add(profile)
        test_db.commit()

        result = DailyTotalsCalculator.get_daily_target(test_db, profile.id, date.today())
        assert result is None

    def test_get_daily_total_nonexistent_profile(self, test_db):
        """Test getting totals for nonexistent profile."""
        confirmed, pending, has_pending = DailyTotalsCalculator.get_daily_total(
            test_db, 999, date.today()
        )

        assert confirmed.calories == 0
        assert has_pending is False
