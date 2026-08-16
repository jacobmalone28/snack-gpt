"""Database backup and recovery utilities."""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class BackupManager:
    """Manage SQLite database backups."""

    DEFAULT_BACKUP_DIR = Path("./backups")
    MAX_BACKUPS = 30  # Keep last 30 backups

    def __init__(self, backup_dir: Optional[Path] = None, db_path: str = "snack_gpt.db"):
        """
        Initialize backup manager.

        Args:
            backup_dir: Directory to store backups. Uses DEFAULT_BACKUP_DIR if not provided.
            db_path: Path to the SQLite database file.
        """
        self.backup_dir = Path(backup_dir) if backup_dir else self.DEFAULT_BACKUP_DIR
        self.db_path = Path(db_path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self) -> Optional[Path]:
        """
        Create a backup of the database.

        Returns:
            Path to the backup file, or None if backup failed.
        """
        if not self.db_path.exists():
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = self.backup_dir / f"snack_gpt_{timestamp}.db"

        try:
            shutil.copy2(self.db_path, backup_path)
            self._cleanup_old_backups()
            return backup_path
        except (IOError, OSError) as e:
            return None

    def list_backups(self) -> list[dict[str, object]]:
        """
        List all available backups.

        Returns:
            List of dicts with 'path' and 'timestamp' keys, sorted by newest first.
        """
        if not self.backup_dir.exists():
            return []

        backups = []
        for backup_file in self.backup_dir.glob("snack_gpt_*.db"):
            try:
                stat = backup_file.stat()
                backups.append({
                    "path": str(backup_file),
                    "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "size_bytes": stat.st_size,
                })
            except OSError:
                continue

        return sorted(backups, key=lambda x: x["timestamp"], reverse=True)  # type: ignore[arg-type, return-value]

    def restore_backup(self, backup_path: Path) -> bool:
        """
        Restore database from a backup.

        Args:
            backup_path: Path to the backup file.

        Returns:
            True if successful, False otherwise.
        """
        if not backup_path.exists():
            return False

        try:
            # Create a backup of current state before restoring
            if self.db_path.exists():
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                pre_restore = self.backup_dir / f"snack_gpt_preRestore_{timestamp}.db"
                shutil.copy2(self.db_path, pre_restore)

            # Restore from backup
            shutil.copy2(backup_path, self.db_path)
            return True
        except (IOError, OSError):
            return False

    def verify_backup(self, backup_path: Path) -> bool:
        """
        Verify a backup file is valid.

        A valid SQLite backup should:
        - Exist and be readable
        - Start with SQLite format magic bytes

        Args:
            backup_path: Path to the backup file.

        Returns:
            True if backup appears valid, False otherwise.
        """
        if not backup_path.exists() or not backup_path.is_file():
            return False

        try:
            with open(backup_path, "rb") as f:
                header = f.read(16)
                # SQLite database files start with "SQLite format 3"
                return header == b"SQLite format 3\x00"
        except (IOError, OSError):
            return False

    def _cleanup_old_backups(self) -> None:
        """Remove old backups, keeping only the most recent MAX_BACKUPS."""
        backups = self.list_backups()
        if len(backups) > self.MAX_BACKUPS:
            for backup in backups[self.MAX_BACKUPS:]:
                try:
                    Path(backup["path"]).unlink()  # type: ignore[arg-type]
                except OSError:
                    pass
