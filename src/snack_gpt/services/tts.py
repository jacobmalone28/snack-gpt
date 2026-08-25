"""Text-to-speech service using Piper."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TTSConfig:
    """Configuration for text-to-speech."""

    model_name: str = "en_US-lessac-medium"  # Compact medium voice
    sample_rate: int = 22050
    speaker_id: int = 0
    length_scale: float = 1.0  # Speed; < 1.0 is faster
    noise_scale: float = 0.667  # Default from Piper
    noise_w: float = 0.8  # Default from Piper


class TextToSpeechService:
    """Generate speech using Piper TTS."""

    # Pre-generated common acknowledgements (bypasses TTS generation)
    PREGENERATED_RESPONSES = {
        "confirmed": b"\x00\x00\x00\x00",  # Placeholder - would be audio bytes
        "pending": b"\x00\x00\x00\x00",
        "error": b"\x00\x00\x00\x00",
        "undo_success": b"\x00\x00\x00\x00",
    }

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        """
        Initialize TTS service.

        Args:
            config: TTS configuration. Uses defaults if not provided.
        """
        self.config = config or TTSConfig()
        self.piper = None  # Would load Piper runtime here
        self.init_piper()

    def init_piper(self) -> None:
        """Initialize Piper runtime."""
        try:
            import piper  # type: ignore[import-not-found]
            self.piper = piper
        except ImportError:
            # Piper not installed - use fallback empty implementation
            self.piper = None

    def synthesize(self, text: str, pregenerated_key: Optional[str] = None) -> bytes:
        """
        Synthesize text to speech.

        Args:
            text: Text to synthesize.
            pregenerated_key: If provided, use pregenerated audio instead of synthesizing.

        Returns:
            Raw audio bytes (WAV format, PCM).
        """
        if pregenerated_key and pregenerated_key in self.PREGENERATED_RESPONSES:
            return self.PREGENERATED_RESPONSES[pregenerated_key]

        if not self.piper:
            # Fallback: return empty audio placeholder
            return b""

        # Would call piper.synthesize(text, model=self.config.model_name, ...)
        # For now, return placeholder
        return b""

    def synthesize_confirmation(self, foods: list[str], quantity_grams: int) -> bytes:
        """
        Synthesize confirmation message for consumed foods.

        Args:
            foods: List of food names.
            quantity_grams: Total grams consumed.

        Returns:
            Audio bytes.
        """
        food_list = ", ".join(foods)
        text = f"Confirmed {quantity_grams} grams of {food_list}"
        return self.synthesize(text, pregenerated_key="confirmed")

    def synthesize_pending(self, pending_items: list[str]) -> bytes:
        """
        Synthesize message for pending items.

        Args:
            pending_items: Descriptions of pending items.

        Returns:
            Audio bytes.
        """
        items_list = ", ".join(pending_items)
        text = f"Pending clarification on {items_list}"
        return self.synthesize(text, pregenerated_key="pending")

    def synthesize_clarification_request(self, description: str, suggestions: list[str]) -> bytes:
        """
        Synthesize a clarification request.

        Args:
            description: What was unclear.
            suggestions: Suggested items to confirm.

        Returns:
            Audio bytes.
        """
        suggestions_text = ", ".join(suggestions)
        text = f"Did you mean {suggestions_text}?"
        return self.synthesize(text)

    def synthesize_error(self, error: str) -> bytes:
        """
        Synthesize error message.

        Args:
            error: Error description.

        Returns:
            Audio bytes.
        """
        return self.synthesize(f"Error: {error}", pregenerated_key="error")

    def synthesize_undo_success(self) -> bytes:
        """Synthesize undo confirmation."""
        return self.synthesize("Undone", pregenerated_key="undo_success")
