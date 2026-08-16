"""Authentication and session management."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from snack_gpt.models.domain import Profile


class SessionManager:
    """Manage authenticated sessions."""

    # Sessions stored in memory with timestamp validation
    # In production, use Redis or database
    _sessions: dict[str, dict[str, object]] = {}
    SESSION_TIMEOUT_MINUTES = 1440  # 24 hours

    @staticmethod
    def create_session(profile_id: int, session_duration_minutes: int = 1440) -> str:
        """
        Create a new authenticated session.

        Args:
            profile_id: Profile ID for the session.
            session_duration_minutes: How long the session lasts.

        Returns:
            Session token (secure random string).
        """
        token = secrets.token_urlsafe(32)
        SessionManager._sessions[token] = {
            "profile_id": profile_id,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=session_duration_minutes),
        }
        return token

    @staticmethod
    def validate_session(token: str) -> int | None:
        """
        Validate a session token and return profile ID if valid.

        Args:
            token: Session token to validate.

        Returns:
            Profile ID if valid, None otherwise.
        """
        if token not in SessionManager._sessions:
            return None

        session = SessionManager._sessions[token]
        if datetime.now(timezone.utc) > session["expires_at"]:  # type: ignore[operator]
            del SessionManager._sessions[token]
            return None

        profile_id = session["profile_id"]
        return int(profile_id) if isinstance(profile_id, (int, str)) else None

    @staticmethod
    def invalidate_session(token: str) -> None:
        """Invalidate a session token."""
        SessionManager._sessions.pop(token, None)


class PasswordManager:
    """Manage admin password authentication."""

    # Store hashed password (in production, use proper secret management)
    _password_hash: Optional[str] = None

    @staticmethod
    def set_password(password: str) -> None:
        """
        Set the admin password (hashed).

        Args:
            password: Plain text password.
        """
        salt = secrets.token_hex(16)
        hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        PasswordManager._password_hash = f"{salt}${hash_obj.hex()}"

    @staticmethod
    def verify_password(password: str) -> bool:
        """
        Verify an admin password.

        Args:
            password: Plain text password to verify.

        Returns:
            True if password matches, False otherwise.
        """
        if not PasswordManager._password_hash:
            return False

        salt, hash_hex = PasswordManager._password_hash.split("$")
        hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return hash_obj.hex() == hash_hex

    @staticmethod
    def is_password_set() -> bool:
        """Check if admin password has been set."""
        return PasswordManager._password_hash is not None
