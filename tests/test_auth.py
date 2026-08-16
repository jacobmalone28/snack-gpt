"""Tests for authentication and session management."""

import pytest
from datetime import datetime, timedelta, timezone

from snack_gpt.services.auth import PasswordManager, SessionManager


class TestPasswordManager:
    """Tests for PasswordManager."""

    def test_set_and_verify_password(self):
        """Test setting and verifying a password."""
        PasswordManager.set_password("test_password_123")
        assert PasswordManager.verify_password("test_password_123") is True

    def test_wrong_password_fails(self):
        """Test that wrong password fails verification."""
        PasswordManager.set_password("correct_password")
        assert PasswordManager.verify_password("wrong_password") is False

    def test_is_password_set(self):
        """Test checking if password is set."""
        # Reset state
        PasswordManager._password_hash = None
        assert PasswordManager.is_password_set() is False

        PasswordManager.set_password("some_password")
        assert PasswordManager.is_password_set() is True

    def test_password_hashing_is_salted(self):
        """Test that passwords are salted (different hashes for same password)."""
        PasswordManager._password_hash = None

        PasswordManager.set_password("password")
        hash1 = PasswordManager._password_hash

        PasswordManager._password_hash = None
        PasswordManager.set_password("password")
        hash2 = PasswordManager._password_hash

        # Different salts should produce different hashes
        assert hash1 != hash2
        # But both should verify correctly
        assert PasswordManager.verify_password("password") is True


class TestSessionManager:
    """Tests for SessionManager."""

    def setup_method(self):
        """Clear sessions before each test."""
        SessionManager._sessions = {}

    def test_create_session(self):
        """Test creating a session."""
        token = SessionManager.create_session(profile_id=1)
        assert token is not None
        assert len(token) > 0
        assert isinstance(token, str)

    def test_validate_valid_session(self):
        """Test validating a valid session."""
        token = SessionManager.create_session(profile_id=42)
        profile_id = SessionManager.validate_session(token)
        assert profile_id == 42

    def test_validate_invalid_token(self):
        """Test validating an invalid token."""
        profile_id = SessionManager.validate_session("invalid_token")
        assert profile_id is None

    def test_session_expires(self):
        """Test that sessions expire."""
        token = SessionManager.create_session(profile_id=1, session_duration_minutes=0)
        # Session with 0 minute duration should already be expired
        profile_id = SessionManager.validate_session(token)
        assert profile_id is None

    def test_invalidate_session(self):
        """Test invalidating a session."""
        token = SessionManager.create_session(profile_id=1)
        assert SessionManager.validate_session(token) == 1

        SessionManager.invalidate_session(token)
        assert SessionManager.validate_session(token) is None

    def test_multiple_sessions(self):
        """Test managing multiple sessions."""
        token1 = SessionManager.create_session(profile_id=1)
        token2 = SessionManager.create_session(profile_id=2)

        assert SessionManager.validate_session(token1) == 1
        assert SessionManager.validate_session(token2) == 2

        SessionManager.invalidate_session(token1)
        assert SessionManager.validate_session(token1) is None
        assert SessionManager.validate_session(token2) == 2
