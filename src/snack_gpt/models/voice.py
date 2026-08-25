"""Voice-related enums and dataclasses for Phase 3."""

from dataclasses import dataclass
from enum import Enum


class CommandStatus(Enum):
    """Status of a command in the processing pipeline."""

    QUEUED = "queued"  # Waiting to be processed
    PROCESSING = "processing"  # Currently being processed
    CONFIRMED = "confirmed"  # Entries created, committed
    PENDING = "pending"  # Awaiting user clarification
    FAILED = "failed"  # Processing failed
    UNDONE = "undone"  # User issued undo


class CommandSource(Enum):
    """Origin of the command."""

    VOICE = "voice"  # Captured from wake-word activation
    MANUAL = "manual"  # Entered via web interface
    API = "api"  # Submitted via HTTP API


@dataclass
class ParsedCommand:
    """Result of parsing a command transcript."""

    command_type: str  # "consume", "draft", "confirm", "undo", "clarify"
    confidence: float  # 0.0-1.0, based on fuzzy matching
    foods: list[dict[str, object]]  # List of {description, quantity, unit, confidence}
    raw_transcript: str
    requires_clarification: bool = False
    clarification_reason: str = ""
    alternatives: list["ParsedCommand"] | None = None


@dataclass
class LLMResponse:
    """Structured response from language model."""

    command_type: str
    foods: list[dict[str, object]]  # {name, quantity, unit, confidence}
    confidence: float
    reasoning: str
