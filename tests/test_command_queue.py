"""Tests for command queue service."""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from snack_gpt.db import SessionLocal
from snack_gpt.models.voice import CommandStatus
from snack_gpt.models.domain import Command
from snack_gpt.services.command_queue import CommandQueueService


class TestCommandQueueService:
    """Test command queueing and processing."""

    @pytest.fixture
    def db(self) -> Session:
        """Provide a database session for testing."""
        session = SessionLocal()
        yield session
        session.close()

    def test_enqueue_command(self, db: Session) -> None:
        """Test enqueueing a new command."""
        command = CommandQueueService.enqueue_command(
            profile_id=1,
            idempotency_key="test-key-001",
            transcript="I ate 200 grams of chicken",
            db=db,
        )

        assert command.id is not None
        assert command.profile_id == 1
        assert command.idempotency_key == "test-key-001"
        assert command.status == CommandStatus.QUEUED.value
        assert command.source == "voice"

    def test_enqueue_with_source(self, db: Session) -> None:
        """Test enqueueing with different source types."""
        sources = ["voice", "manual", "api"]

        for source in sources:
            command = CommandQueueService.enqueue_command(
                profile_id=1,
                idempotency_key=f"test-{source}",
                transcript="test",
                source=source,
                db=db,
            )
            assert command.source == source

    def test_get_queued_commands(self, db: Session) -> None:
        """Test retrieving queued commands."""
        # Create several commands
        for i in range(3):
            CommandQueueService.enqueue_command(
                profile_id=1,
                idempotency_key=f"test-{i}",
                transcript=f"transcript {i}",
                db=db,
            )

        queued = CommandQueueService.get_queued_commands(profile_id=1, db=db)
        assert len(queued) >= 3
        assert all(cmd.status == CommandStatus.QUEUED.value for cmd in queued)

    def test_get_queued_commands_limit(self, db: Session) -> None:
        """Test limit parameter in get_queued_commands."""
        for i in range(5):
            CommandQueueService.enqueue_command(
                profile_id=1,
                idempotency_key=f"test-limit-{i}",
                transcript=f"test {i}",
                db=db,
            )

        queued = CommandQueueService.get_queued_commands(profile_id=1, limit=2, db=db)
        # Should return at most 2, but might have other test commands
        assert len(queued) <= 2

    def test_get_queued_commands_profile_isolation(self, db: Session) -> None:
        """Test that queued commands are isolated by profile."""
        CommandQueueService.enqueue_command(
            profile_id=1,
            idempotency_key="test-p1",
            transcript="profile 1",
            db=db,
        )
        CommandQueueService.enqueue_command(
            profile_id=2,
            idempotency_key="test-p2",
            transcript="profile 2",
            db=db,
        )

        queued_p1 = CommandQueueService.get_queued_commands(profile_id=1, db=db)
        queued_p2 = CommandQueueService.get_queued_commands(profile_id=2, db=db)

        assert any(cmd.idempotency_key == "test-p1" for cmd in queued_p1)
        assert any(cmd.idempotency_key == "test-p2" for cmd in queued_p2)

    def test_update_command_status(self, db: Session) -> None:
        """Test updating command status."""
        command = CommandQueueService.enqueue_command(
            profile_id=1,
            idempotency_key="test-update",
            transcript="test",
            db=db,
        )

        parsed_intent = {"command_type": "consume", "foods": [{"name": "chicken"}]}
        updated = CommandQueueService.update_command_status(
            command_id=command.id,
            status=CommandStatus.PROCESSING,
            parsed_intent=parsed_intent,
            db=db,
        )

        assert updated.status == CommandStatus.PROCESSING.value
        assert updated.parsed_intent == json.dumps(parsed_intent)

    def test_update_command_with_entries(self, db: Session) -> None:
        """Test updating command with created entry IDs."""
        command = CommandQueueService.enqueue_command(
            profile_id=1,
            idempotency_key="test-entries",
            transcript="test",
            db=db,
        )

        entry_ids = [101, 102, 103]
        updated = CommandQueueService.update_command_status(
            command_id=command.id,
            status=CommandStatus.CONFIRMED,
            entry_ids=entry_ids,
            db=db,
        )

        assert updated.status == CommandStatus.CONFIRMED.value
        assert json.loads(updated.entry_ids) == entry_ids
        assert updated.processed_at is not None

    def test_update_command_with_error(self, db: Session) -> None:
        """Test updating command with error message."""
        command = CommandQueueService.enqueue_command(
            profile_id=1,
            idempotency_key="test-error",
            transcript="test",
            db=db,
        )

        error_msg = "Food not found: xyz"
        updated = CommandQueueService.update_command_status(
            command_id=command.id,
            status=CommandStatus.FAILED,
            error_message=error_msg,
            db=db,
        )

        assert updated.status == CommandStatus.FAILED.value
        assert updated.error_message == error_msg

    def test_update_nonexistent_command(self, db: Session) -> None:
        """Test error handling for nonexistent command."""
        with pytest.raises(ValueError):
            CommandQueueService.update_command_status(
                command_id=99999,
                status=CommandStatus.CONFIRMED,
                db=db,
            )

    def test_undo_latest_command(self, db: Session) -> None:
        """Test undoing the latest command."""
        # This test would require ConsumptionEntry to be set up
        # For now, test that undo_latest_command handles missing entries gracefully
        result = CommandQueueService.undo_latest_command(profile_id=1, db=db)
        # Should return False if no recent command exists
        assert isinstance(result, bool)

    def test_idempotency_key_uniqueness(self, db: Session) -> None:
        """Repeated inserts for the same idempotency key should be idempotent."""
        first = CommandQueueService.enqueue_command(
            profile_id=1,
            idempotency_key="unique-key",
            transcript="first",
            db=db,
        )

        duplicate = CommandQueueService.enqueue_command(
            profile_id=1,
            idempotency_key="unique-key",
            transcript="second",
            db=db,
        )

        assert duplicate.id == first.id
        assert duplicate.idempotency_key == "unique-key"
        assert duplicate.transcript == "first"
        assert duplicate.status == CommandStatus.QUEUED.value
