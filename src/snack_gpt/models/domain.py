"""SQLAlchemy domain models for Snack GPT."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from snack_gpt.db import Base


class Profile(Base):
    """A household member whose consumption entries are tracked independently."""

    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    timezone = Column(String(63), nullable=False, default="UTC")
    is_active = Column(Integer, nullable=False, default=1)  # SQLite boolean as integer
    is_default = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    daily_targets = relationship("DailyTarget", back_populates="profile")
    food_aliases = relationship("FoodAlias", back_populates="profile")
    consumption_entries = relationship("ConsumptionEntry", back_populates="profile")
    pending_consumption = relationship("PendingConsumption", back_populates="profile")


class DailyTarget(Base):
    """A profile's effective-dated nutrition targets."""

    __tablename__ = "daily_targets"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    effective_date = Column(DateTime, nullable=False)
    calories = Column(Integer, nullable=False)
    protein_grams = Column(Float, nullable=False)
    carbohydrate_grams = Column(Float, nullable=False)
    fat_grams = Column(Float, nullable=False)
    fiber_grams = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("profile_id", "effective_date", name="uq_profile_effective_date"),)

    profile = relationship("Profile", back_populates="daily_targets")


class FoodReference(Base):
    """A reusable description of a food and its nutrition values."""

    __tablename__ = "food_references"

    id = Column(Integer, primary_key=True)
    canonical_name = Column(String(255), nullable=False)
    preparation = Column(String(127), nullable=True)  # raw, cooked, etc.
    brand = Column(String(255), nullable=True)
    barcode = Column(String(63), nullable=True)
    nutrition_source = Column(String(63), nullable=False)  # package_label, usda, open_food_facts, profile
    calories_per_gram = Column(Float, nullable=False)
    protein_per_gram = Column(Float, nullable=False)
    carbohydrate_per_gram = Column(Float, nullable=False)
    fat_per_gram = Column(Float, nullable=False)
    fiber_per_gram = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("canonical_name", "preparation", "brand", "barcode", name="uq_food_identity"),)

    portions = relationship("Portion", back_populates="food_reference")
    food_aliases = relationship("FoodAlias", back_populates="food_reference")
    consumption_entries = relationship("ConsumptionEntry", back_populates="food_reference")


class FoodAlias(Base):
    """A profile-approved phrase or barcode mapped to a Food Reference."""

    __tablename__ = "food_aliases"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    food_reference_id = Column(Integer, ForeignKey("food_references.id"), nullable=False)
    phrase = Column(String(255), nullable=True)  # Explicit alias text
    barcode = Column(String(63), nullable=True)  # Barcode alias
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("profile_id", "phrase", name="uq_profile_phrase"),)

    profile = relationship("Profile", back_populates="food_aliases")
    food_reference = relationship("FoodReference", back_populates="food_aliases")


class Portion(Base):
    """Food-specific unit, amount, and gram equivalent."""

    __tablename__ = "portions"

    id = Column(Integer, primary_key=True)
    food_reference_id = Column(Integer, ForeignKey("food_references.id"), nullable=False)
    unit = Column(String(63), nullable=False)  # grams, cup, tablespoon, piece, etc.
    grams_per_unit = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("food_reference_id", "unit", name="uq_food_unit"),)

    food_reference = relationship("FoodReference", back_populates="portions")


class MealDraft(Base):
    """A named or ad hoc collection of foods being assembled before consumption."""

    __tablename__ = "meal_drafts"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=True)
    final_yield_grams = Column(Float, nullable=True)  # Total cooked weight
    final_yield_servings = Column(Float, nullable=True)  # Total serving count
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ingredients = relationship("MealDraftIngredient", back_populates="meal_draft")


class MealDraftIngredient(Base):
    """An ingredient in a meal draft."""

    __tablename__ = "meal_draft_ingredients"

    id = Column(Integer, primary_key=True)
    meal_draft_id = Column(Integer, ForeignKey("meal_drafts.id"), nullable=False)
    food_reference_id = Column(Integer, ForeignKey("food_references.id"), nullable=False)
    quantity_grams = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    meal_draft = relationship("MealDraft", back_populates="ingredients")
    food_reference = relationship("FoodReference")


class ConsumptionEntry(Base):
    """A snapshot of a quantity of food recorded as consumed by a profile."""

    __tablename__ = "consumption_entries"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    food_reference_id = Column(Integer, ForeignKey("food_references.id"), nullable=False)
    quantity_grams = Column(Float, nullable=False)
    consumption_time = Column(DateTime, nullable=False)
    # Snapshot of nutrition at time of entry
    calories_snapshot = Column(Float, nullable=False)
    protein_snapshot = Column(Float, nullable=False)
    carbohydrate_snapshot = Column(Float, nullable=False)
    fat_snapshot = Column(Float, nullable=False)
    fiber_snapshot = Column(Float, nullable=False)
    # Correction linkage
    replaces_entry_id = Column(Integer, ForeignKey("consumption_entries.id"), nullable=True)
    is_reversal = Column(Integer, nullable=False, default=0)  # Boolean: true if this reverses an entry
    command_id = Column(Integer, ForeignKey("commands.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    profile = relationship("Profile", back_populates="consumption_entries")
    food_reference = relationship("FoodReference", back_populates="consumption_entries")


class PendingConsumption(Base):
    """A reported quantity of food whose nutrition cannot yet be resolved."""

    __tablename__ = "pending_consumption"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    original_description = Column(Text, nullable=False)
    quantity_description = Column(String(255), nullable=True)
    consumption_time = Column(DateTime, nullable=False)
    command_id = Column(Integer, ForeignKey("commands.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    profile = relationship("Profile", back_populates="pending_consumption")


class Command(Base):
    """A captured voice or text command with its idempotency key and outcomes."""

    __tablename__ = "commands"

    id = Column(Integer, primary_key=True)
    idempotency_key = Column(String(255), nullable=False, unique=True)
    transcript = Column(Text, nullable=False)
    status = Column(String(63), nullable=False, default="pending")  # pending, completed, failed
    outcome_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProviderCache(Base):
    """Cached provider responses for nutrition lookup."""

    __tablename__ = "provider_cache"

    id = Column(Integer, primary_key=True)
    provider_key = Column(String(255), nullable=False)  # e.g., "usda:fdc_id", "off:barcode"
    normalized_result = Column(Text, nullable=False)  # JSON
    original_response = Column(Text, nullable=False)  # JSON
    retrieved_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("provider_key", name="uq_provider_key"),)
