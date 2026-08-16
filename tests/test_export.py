"""Tests for data export functionality."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import json
import csv
from io import StringIO

from snack_gpt.db import Base
from snack_gpt.models.domain import (
    ConsumptionEntry,
    DailyTarget,
    FoodAlias,
    FoodReference,
    Profile,
)
from snack_gpt.services.export import DataExporter


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def setup_test_data(test_db):
    """Set up test data."""
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

    return profile, food, entry


class TestDataExporter:
    """Tests for DataExporter."""

    def test_export_consumption_history_json(self, test_db, setup_test_data):
        """Test exporting consumption history as JSON."""
        profile, food, entry = setup_test_data

        json_str = DataExporter.export_consumption_history_json(test_db, profile.id)

        data = json.loads(json_str)
        assert data["profile_id"] == profile.id
        assert "exported_at" in data
        assert len(data["entries"]) == 1
        assert data["entries"][0]["food"] == "Chicken"
        assert data["entries"][0]["calories"] == 165

    def test_export_consumption_history_csv(self, test_db, setup_test_data):
        """Test exporting consumption history as CSV."""
        profile, food, entry = setup_test_data

        csv_str = DataExporter.export_consumption_history_csv(test_db, profile.id)

        reader = csv.DictReader(StringIO(csv_str))
        rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["food"] == "Chicken"
        assert float(rows[0]["calories"]) == 165

    def test_export_food_database_json(self, test_db, setup_test_data):
        """Test exporting food database as JSON."""
        profile, food, entry = setup_test_data

        # Create a food alias
        alias = FoodAlias(
            profile_id=profile.id,
            food_reference_id=food.id,
            phrase="chicken breast",
        )
        test_db.add(alias)
        test_db.commit()

        json_str = DataExporter.export_food_database_json(test_db, profile.id)

        data = json.loads(json_str)
        assert data["profile_id"] == profile.id
        assert len(data["food_aliases"]) == 1
        assert data["food_aliases"][0]["phrase"] == "chicken breast"
        assert data["food_aliases"][0]["food"]["canonical_name"] == "Chicken"

    def test_export_daily_targets_json(self, test_db, setup_test_data):
        """Test exporting daily targets as JSON."""
        profile, food, entry = setup_test_data

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

        json_str = DataExporter.export_daily_targets_json(test_db, profile.id)

        data = json.loads(json_str)
        assert data["profile_id"] == profile.id
        assert len(data["daily_targets"]) == 1
        assert data["daily_targets"][0]["calories"] == 2000

    def test_export_empty_profile(self, test_db):
        """Test exporting data for a profile with no data."""
        profile = Profile(name="Empty User", timezone="UTC")
        test_db.add(profile)
        test_db.commit()

        json_str = DataExporter.export_consumption_history_json(test_db, profile.id)
        data = json.loads(json_str)

        assert len(data["entries"]) == 0
