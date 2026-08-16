"""Command handling and idempotency utilities."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Optional


class IdempotencyKey:
    """Generate and validate idempotency keys for commands."""

    @staticmethod
    def generate_from_transcript(transcript: str) -> str:
        """
        Generate an idempotency key from a transcript.

        This is deterministic but should be combined with a timestamp
        for production use to avoid collisions across time.

        Args:
            transcript: The command transcript.

        Returns:
            A hex-encoded hash suitable as an idempotency key.
        """
        # Hash the transcript to create a stable key
        return hashlib.sha256(transcript.encode()).hexdigest()

    @staticmethod
    def generate_unique() -> str:
        """
        Generate a unique idempotency key.

        Args:
            None

        Returns:
            A UUID-based key.
        """
        return str(uuid.uuid4())

    @staticmethod
    def generate_from_event(
        transcript: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Generate an idempotency key from event components.

        Combines transcript, timestamp, and optional metadata for
        maximum uniqueness.

        Args:
            transcript: The command transcript.
            timestamp: Optional timestamp of the command.
            metadata: Optional additional metadata to include.

        Returns:
            A hex-encoded composite key.
        """
        components = [transcript]

        if timestamp:
            components.append(timestamp.isoformat())

        if metadata:
            components.append(json.dumps(metadata, sort_keys=True))

        combined = "|".join(components)
        return hashlib.sha256(combined.encode()).hexdigest()
