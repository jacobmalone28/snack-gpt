"""Tests for backup management."""

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from snack_gpt.services.backup import BackupManager


class TestBackupManager:
    """Tests for BackupManager."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        with TemporaryDirectory() as backup_dir:
            with TemporaryDirectory() as data_dir:
                yield Path(backup_dir), Path(data_dir)

    def test_create_backup(self, temp_dirs):
        """Test creating a backup."""
        backup_dir, data_dir = temp_dirs
        db_path = data_dir / "test.db"

        # Create a dummy database file
        db_path.write_text("SQLite format 3\x00" + "dummy data")

        manager = BackupManager(backup_dir=backup_dir, db_path=str(db_path))
        backup = manager.create_backup()

        assert backup is not None
        assert backup.exists()
        assert backup.parent == backup_dir

    def test_create_backup_nonexistent_db(self, temp_dirs):
        """Test creating backup when database doesn't exist."""
        backup_dir, data_dir = temp_dirs
        db_path = data_dir / "nonexistent.db"

        manager = BackupManager(backup_dir=backup_dir, db_path=str(db_path))
        backup = manager.create_backup()

        assert backup is None

    def test_list_backups(self, temp_dirs):
        """Test listing backups."""
        backup_dir, data_dir = temp_dirs
        db_path = data_dir / "test.db"
        db_path.write_text("SQLite format 3\x00" + "dummy")

        manager = BackupManager(backup_dir=backup_dir, db_path=str(db_path))

        # Create multiple backups - microsecond timestamps ensure uniqueness
        backup1 = manager.create_backup()
        backup2 = manager.create_backup()
        
        assert backup1 is not None
        assert backup2 is not None
        assert backup1 != backup2

        backups = manager.list_backups()
        assert len(backups) == 2
        assert all("timestamp" in b and "path" in b for b in backups)

    def test_list_backups_empty(self, temp_dirs):
        """Test listing backups when none exist."""
        backup_dir, data_dir = temp_dirs
        manager = BackupManager(backup_dir=backup_dir)

        backups = manager.list_backups()
        assert backups == []

    def test_verify_backup_valid(self, temp_dirs):
        """Test verifying a valid backup."""
        backup_dir, data_dir = temp_dirs
        db_path = data_dir / "test.db"

        # Create a valid SQLite file
        db_path.write_bytes(b"SQLite format 3\x00" + b"dummy data")

        manager = BackupManager(backup_dir=backup_dir, db_path=str(db_path))
        backup = manager.create_backup()

        assert manager.verify_backup(backup) is True

    def test_verify_backup_invalid(self, temp_dirs):
        """Test verifying an invalid backup."""
        backup_dir, data_dir = temp_dirs
        invalid_backup = backup_dir / "invalid.db"
        invalid_backup.write_text("not a sqlite database")

        manager = BackupManager(backup_dir=backup_dir)
        assert manager.verify_backup(invalid_backup) is False

    def test_restore_backup(self, temp_dirs):
        """Test restoring from a backup."""
        backup_dir, data_dir = temp_dirs
        db_path = data_dir / "test.db"

        # Create original database
        original_content = b"SQLite format 3\x00" + b"original data"
        db_path.write_bytes(original_content)

        manager = BackupManager(backup_dir=backup_dir, db_path=str(db_path))
        backup = manager.create_backup()

        # Modify database
        db_path.write_bytes(b"SQLite format 3\x00" + b"modified data")
        assert db_path.read_bytes() != original_content

        # Restore
        success = manager.restore_backup(backup)
        assert success is True
        assert db_path.read_bytes() == original_content

    def test_restore_nonexistent_backup(self, temp_dirs):
        """Test restoring from a nonexistent backup."""
        backup_dir, data_dir = temp_dirs
        manager = BackupManager(backup_dir=backup_dir)

        nonexistent = backup_dir / "does_not_exist.db"
        success = manager.restore_backup(nonexistent)
        assert success is False
