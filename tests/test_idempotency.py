"""Tests for idempotency utilities."""

import pytest

from snack_gpt.services.idempotency import IdempotencyKey


class TestIdempotencyKeyGeneration:
    """Tests for idempotency key generation."""

    def test_generate_from_transcript_deterministic(self):
        """Test that transcript-based keys are deterministic."""
        transcript = "I ate 100 grams of chicken"
        
        key1 = IdempotencyKey.generate_from_transcript(transcript)
        key2 = IdempotencyKey.generate_from_transcript(transcript)
        
        assert key1 == key2

    def test_generate_from_transcript_different_for_different_input(self):
        """Test that different transcripts produce different keys."""
        key1 = IdempotencyKey.generate_from_transcript("I ate 100 grams of chicken")
        key2 = IdempotencyKey.generate_from_transcript("I ate 200 grams of chicken")
        
        assert key1 != key2

    def test_generate_unique_returns_uuid(self):
        """Test that unique generation returns a valid UUID."""
        key = IdempotencyKey.generate_unique()
        
        # Should be a valid UUID string (36 chars with hyphens)
        assert len(key) == 36
        assert key.count("-") == 4

    def test_generate_unique_returns_different_values(self):
        """Test that unique generation returns different values each time."""
        key1 = IdempotencyKey.generate_unique()
        key2 = IdempotencyKey.generate_unique()
        
        assert key1 != key2

    def test_generate_from_event_with_all_components(self):
        """Test event-based key generation with all components."""
        from datetime import datetime
        
        transcript = "I ate 100 grams of chicken"
        timestamp = datetime(2024, 1, 15, 12, 30, 45)
        metadata = {"speaker": "alice", "context": "lunch"}
        
        key1 = IdempotencyKey.generate_from_event(transcript, timestamp, metadata)
        key2 = IdempotencyKey.generate_from_event(transcript, timestamp, metadata)
        
        # Should be deterministic with same inputs
        assert key1 == key2

    def test_generate_from_event_different_with_different_timestamp(self):
        """Test that different timestamps produce different keys."""
        from datetime import datetime
        
        transcript = "I ate 100 grams of chicken"
        metadata = {"speaker": "alice"}
        
        timestamp1 = datetime(2024, 1, 15, 12, 30, 45)
        timestamp2 = datetime(2024, 1, 15, 12, 30, 46)
        
        key1 = IdempotencyKey.generate_from_event(transcript, timestamp1, metadata)
        key2 = IdempotencyKey.generate_from_event(transcript, timestamp2, metadata)
        
        assert key1 != key2

    def test_generate_from_event_with_only_transcript(self):
        """Test event-based key generation with only transcript."""
        transcript = "I ate 100 grams of chicken"
        
        key1 = IdempotencyKey.generate_from_event(transcript)
        key2 = IdempotencyKey.generate_from_event(transcript)
        
        # Should be deterministic
        assert key1 == key2
        # Should be a hex string
        assert len(key1) == 64  # SHA-256 hex is 64 chars
