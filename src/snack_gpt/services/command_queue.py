"""Command queue service for managing persistent command processing."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from snack_gpt.db import SessionLocal
from snack_gpt.models.domain import Command
from snack_gpt.models.voice import CommandStatus


class CommandQueueService:
    """Manage command queue for async processing and offline support."""

    @staticmethod
    def enqueue_command(profile_id: int, idempotency_key: str, transcript: str, source: str = "voice", db: Optional[Session] = None) -> Command:
        """Queue a command for processing.

        Replaying the same idempotency key must return the existing command instead
        of creating a second row, which would duplicate voice entries when the user
        retries the same spoken action.
        """
        owns_session = db is None
        session = db or SessionLocal()
        try:
            existing = session.execute(
                select(Command).where(Command.idempotency_key == idempotency_key)
            ).scalar_one_or_none()
            if existing is not None:
                return existing

            command = Command(
                profile_id=profile_id,
                idempotency_key=idempotency_key,
                transcript=transcript,
                source=source,
                status=CommandStatus.QUEUED.value,
            )
            session.add(command)
            session.commit()
            session.refresh(command)
            return command
        finally:
            if owns_session:
                session.close()

    @staticmethod
    def get_queued_commands(profile_id: int, limit: int = 10, db: Optional[Session] = None) -> list[Command]:
        """Return the newest queued commands for a profile."""
        owns_session = db is None
        session = db or SessionLocal()
        try:
            query = (
                select(Command)
                .where((Command.profile_id == profile_id) & (Command.status == CommandStatus.QUEUED.value))
                .order_by(Command.created_at.desc(), Command.id.desc())
                .limit(limit)
            )
            return list(session.execute(query).scalars().all())
        finally:
            if owns_session:
                session.close()

    @staticmethod
    def update_command_status(command_id: int, status: CommandStatus, parsed_intent: Optional[dict[str, object]] = None, llm_response: Optional[dict[str, object]] = None, entry_ids: Optional[list[int]] = None, error_message: Optional[str] = None, db: Optional[Session] = None) -> Command:
        """Update command status and processing metadata."""
        owns_session = db is None
        session = db or SessionLocal()
        try:
            command = session.execute(select(Command).where(Command.id == command_id)).scalar_one_or_none()
            if command is None:
                raise ValueError(f"Command {command_id} not found")
            command.status = status.value  # type: ignore[assignment]
            if status in (CommandStatus.CONFIRMED, CommandStatus.PENDING, CommandStatus.FAILED):
                command.processed_at = datetime.now(timezone.utc)  # type: ignore[assignment]
            if parsed_intent is not None:
                command.parsed_intent = json.dumps(parsed_intent)  # type: ignore[assignment]
            if llm_response is not None:
                command.llm_response = json.dumps(llm_response)  # type: ignore[assignment]
            if entry_ids is not None:
                command.entry_ids = json.dumps(entry_ids)  # type: ignore[assignment]
            if error_message is not None:
                command.error_message = error_message
            session.commit()
            session.refresh(command)
            return command
        finally:
            if owns_session:
                session.close()

    @staticmethod
    def undo_latest_command(profile_id: int, db: Optional[Session] = None) -> bool:
        """Undo the latest confirmed or pending command with entries."""
        owns_session = db is None
        session = db or SessionLocal()
        try:
            query = (
                select(Command)
                .where((Command.profile_id == profile_id) & Command.status.in_([CommandStatus.CONFIRMED.value, CommandStatus.PENDING.value]))
                .order_by(Command.processed_at.desc())
            )
            command = session.execute(query).scalars().first()
            if command is None or not command.entry_ids:
                return False
            command.status = CommandStatus.UNDONE.value  # type: ignore[assignment]
            session.commit()
            from snack_gpt.models.domain import ConsumptionEntry
            for entry_id in json.loads(str(command.entry_ids)):
                entry = session.execute(select(ConsumptionEntry).where(ConsumptionEntry.id == entry_id)).scalar_one_or_none()
                if entry is not None:
                    session.delete(entry)
            session.commit()
            return True
        finally:
            if owns_session:
                session.close()
