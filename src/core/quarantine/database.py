# ClamUI Quarantine Database Module
"""
Quarantine database module for ClamUI providing metadata persistence.

Stores information about quarantined files including original path, threat info, and file hash.

Security Considerations:
    The quarantine database contains sensitive information that could be valuable to
    attackers on multi-user systems:
    - Original file paths revealing system structure and user activity
    - Threat names indicating which malware was detected
    - SHA-256 file hashes that could be used to identify/recover malware samples

    To protect this metadata, the database file and associated WAL/SHM files are
    created with restrictive 0o600 permissions (owner read/write only), preventing
    other users from accessing quarantine information.
"""

import logging
import os
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .connection_pool import ConnectionPool

logger = logging.getLogger(__name__)


@dataclass
class QuarantineEntry:
    """A single quarantine entry representing an isolated threat."""

    id: int
    original_path: str
    quarantine_path: str
    threat_name: str
    detection_date: str  # ISO format string for portability
    file_size: int
    file_hash: str  # SHA256 hash for integrity verification
    original_permissions: int  # Original file permissions (st_mode & 0o777)

    def to_dict(self) -> dict:
        """Convert QuarantineEntry to dictionary."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple) -> "QuarantineEntry":
        """
        Create QuarantineEntry from database row.

        Args:
            row: Database row tuple (id, original_path, quarantine_path,
                 threat_name, detection_date, file_size, file_hash,
                 original_permissions)

        Returns:
            New QuarantineEntry instance
        """
        # VULN-004: defense-in-depth — mask permission bits read from DB to
        # the low 9 bits (rwx for user/group/other). Prevents setuid/setgid/
        # sticky bits from propagating out of a tampered or corrupted DB row.
        raw_perms = row[7] if len(row) > 7 else None
        if raw_perms is None:
            masked_perms = 0o644
        else:
            masked_perms = raw_perms & 0o777
        return cls(
            id=row[0],
            original_path=row[1],
            quarantine_path=row[2],
            threat_name=row[3],
            detection_date=row[4],
            file_size=row[5],
            file_hash=row[6],
            original_permissions=masked_perms,
        )


class QuarantineDatabase:
    """
    Manager for quarantine metadata persistence using SQLite.

    Provides methods for adding, retrieving, updating, and removing
    quarantine entries with thread-safe operations.
    """

    # Database file permissions: 0o600 (owner read/write only)
    # Protects sensitive quarantine metadata from unauthorized access:
    # - Original file paths (reveals system structure and user activity)
    # - Threat names (indicates which malware was detected)
    # - SHA-256 hashes (could be used to identify/recover malware samples)
    DB_FILE_PERMISSIONS = 0o600

    def __init__(self, db_path: str | None = None, pool_size: int = 3):
        """
        Initialize the QuarantineDatabase.

        Args:
            db_path: Optional custom database path. Defaults to XDG_DATA_HOME/clamui/quarantine.db
            pool_size: Size of the connection pool. Set to 0 to disable pooling and use
                      per-operation connections. Default is 3 for optimal performance.
        """
        if db_path:
            self._db_path = Path(db_path)
        else:
            xdg_data_home = os.environ.get("XDG_DATA_HOME", "~/.local/share")
            self._db_path = Path(xdg_data_home).expanduser() / "clamui" / "quarantine.db"

        # Thread lock for safe concurrent access
        self._lock = threading.Lock()

        # Initialize connection pool if enabled
        if pool_size > 0:
            self._pool: ConnectionPool | None = ConnectionPool(
                str(self._db_path), pool_size=pool_size
            )
        else:
            self._pool = None

        # Ensure parent directory exists
        self._ensure_db_dir()

        # Initialize database schema
        self._init_database()

    def _ensure_db_dir(self) -> None:
        """Ensure the database directory exists."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            # Handle silently - will fail on database operations
            logger.debug("Failed to create quarantine database directory", exc_info=True)

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection as a context manager with WAL mode enabled.

        Connection Pool vs Per-Operation Behavior:
        - WITH POOL (pool_size > 0, default=3):
          * Connections are pre-created and reused across operations
          * ConnectionPool.get_connection() returns an existing idle connection
          * Connection is returned to pool after use (not closed)
          * Faster for frequent operations (no connection overhead)
          * Small memory overhead (~1-2MB per connection)

        - WITHOUT POOL (pool_size = 0):
          * New connection created for each database operation
          * Connection is fully closed after operation completes
          * Slower but uses less memory for infrequent operations
          * Useful for resource-constrained environments or testing

        When connection pooling is enabled (pool_size > 0), connections are
        obtained from the pool. Otherwise, creates a new connection per operation.

        The connection is properly closed after use, preventing resource warnings.
        Transactions are automatically committed on success or rolled back on error.

        Yields:
            SQLite connection object
        """
        # Use connection pool if available
        if self._pool is not None:
            with self._pool.get_connection() as conn:
                yield conn
        else:
            # Fallback to per-operation connections when pooling is disabled
            conn = sqlite3.connect(str(self._db_path), timeout=30.0)
            try:
                # WAL (Write-Ahead Log) mode concurrency implications:
                # - Allows MULTIPLE concurrent readers + ONE writer (vs rollback journal: exclusive writer lock)
                # - Readers don't block writers, writers don't block readers
                # - Better performance for mixed read/write workloads
                # - Creates .db-wal and .db-shm files (also secured to 0o600)
                # - Auto-checkpoints every 1000 pages (configurable with PRAGMA wal_autocheckpoint)
                # Enable WAL mode for better concurrency and corruption prevention
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                yield conn
            finally:
                conn.close()

    def _secure_db_file_permissions(self) -> None:
        """
        Set restrictive permissions on database files to prevent unauthorized access.

        Secures the main database file and associated WAL/SHM files created by
        SQLite's Write-Ahead Logging mode. All files are set to 0o600 (owner read/write only)
        to prevent other users from reading sensitive quarantine metadata.

        Security Rationale:
            On multi-user systems, the quarantine database is a valuable information source
            for attackers. It reveals:
            - Which files were detected as threats (threat intelligence)
            - Original file locations (system reconnaissance)
            - File hashes for potential malware recovery

        SQLite WAL Mode Files:
            - .db: Main database file containing all quarantine metadata
            - .db-wal: Write-Ahead Log file with uncommitted transactions
            - .db-shm: Shared Memory file for WAL mode coordination

            All three files can contain sensitive data and must be secured.

        Error Handling:
            Permission errors are handled gracefully without raising exceptions.
            This prevents database functionality from breaking on systems with:
            - Restrictive security policies (SELinux, AppArmor)
            - Immutable file attributes
            - Unusual filesystem configurations
        """
        # Database files to secure (main db + WAL mode files)
        db_files = [
            self._db_path,  # Main database file
            Path(str(self._db_path) + "-wal"),  # Write-Ahead Log file
            Path(str(self._db_path) + "-shm"),  # Shared Memory file
        ]

        for db_file in db_files:
            # Open with O_NOFOLLOW so a symlink planted here cannot redirect chmod
            # to an arbitrary file. ENOENT is expected for WAL/SHM when SQLite hasn't
            # created them yet; ELOOP means a symlink — both are silently skipped.
            try:
                fd = os.open(db_file, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError:
                continue
            try:
                os.fchmod(fd, self.DB_FILE_PERMISSIONS)
            except OSError:
                logger.debug("Failed to enforce permissions on %s", db_file, exc_info=True)
            finally:
                os.close(fd)

    def _init_database(self) -> None:
        """Initialize the database schema if it doesn't exist."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS quarantine (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            original_path TEXT NOT NULL,
                            quarantine_path TEXT NOT NULL UNIQUE,
                            threat_name TEXT NOT NULL,
                            detection_date TEXT NOT NULL,
                            file_size INTEGER NOT NULL,
                            file_hash TEXT NOT NULL,
                            original_permissions INTEGER NOT NULL DEFAULT 420
                                CHECK (original_permissions BETWEEN 0 AND 511),
                            state TEXT NOT NULL DEFAULT 'active'
                                CHECK (state IN ('active', 'restored', 'deleted'))
                        )
                        """
                    )
                    # Create index for faster lookups
                    conn.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_quarantine_detection_date
                        ON quarantine(detection_date)
                        """
                    )
                    conn.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_quarantine_original_path
                        ON quarantine(original_path)
                        """
                    )

                    # Migration: Add original_permissions column if it doesn't exist
                    # This handles existing databases that were created before this column
                    cursor = conn.execute("PRAGMA table_info(quarantine)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if "original_permissions" not in columns:
                        conn.execute(
                            """
                            ALTER TABLE quarantine
                            ADD COLUMN original_permissions INTEGER NOT NULL DEFAULT 420
                                CHECK (original_permissions BETWEEN 0 AND 511)
                            """
                        )
                    if "state" not in columns:
                        conn.execute(
                            """
                            ALTER TABLE quarantine
                            ADD COLUMN state TEXT NOT NULL DEFAULT 'active'
                                CHECK (state IN ('active', 'restored', 'deleted'))
                            """
                        )

                    conn.commit()

                    # SECURITY: Secure database file permissions after schema creation
                    # Applies 0o600 permissions to prevent unauthorized access to sensitive metadata
                    # (file paths, threat names, SHA-256 hashes) by other users on the system.
                    # This runs for both new and existing databases to ensure the main database file
                    # and WAL/SHM files (created by SQLite's Write-Ahead Logging mode) have
                    # restrictive permissions. See _secure_db_file_permissions() for details.
                    self._secure_db_file_permissions()
            except sqlite3.Error as e:
                logger.error("Failed to initialize quarantine database at %s: %s", self._db_path, e)

    def add_entry(
        self,
        original_path: str,
        quarantine_path: str,
        threat_name: str,
        file_size: int,
        file_hash: str,
        original_permissions: int = 0o644,
    ) -> int | None:
        """
        Add a new quarantine entry to the database.

        Args:
            original_path: Original file path before quarantine
            quarantine_path: Path to the quarantined file
            threat_name: Name of the detected threat
            file_size: Size of the file in bytes
            file_hash: SHA256 hash of the file for integrity verification
            original_permissions: Original file permissions (st_mode & 0o777)

        Returns:
            The ID of the newly created entry, or None if failed
        """
        # VULN-004: defense-in-depth — mask permission bits before insert so
        # the DB only ever stores the low 9 bits (rwx user/group/other).
        # Prevents accidental or malicious propagation of setuid/setgid/sticky.
        original_permissions = original_permissions & 0o777
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO quarantine
                        (original_path, quarantine_path, threat_name, detection_date,
                         file_size, file_hash, original_permissions)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            original_path,
                            quarantine_path,
                            threat_name,
                            datetime.now().isoformat(),
                            file_size,
                            file_hash,
                            original_permissions,
                        ),
                    )
                    conn.commit()
                    return cursor.lastrowid
            except sqlite3.Error as e:
                logger.error("Failed to add quarantine entry for %s: %s", original_path, e)
                return None

    def get_entry(self, entry_id: int) -> QuarantineEntry | None:
        """
        Retrieve a specific quarantine entry by ID.

        Args:
            entry_id: The ID of the quarantine entry

        Returns:
            QuarantineEntry if found, None otherwise
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT id, original_path, quarantine_path, threat_name,
                               detection_date, file_size, file_hash, original_permissions
                        FROM quarantine WHERE id = ?
                        """,
                        (entry_id,),
                    )
                    row = cursor.fetchone()
                    if row:
                        return QuarantineEntry.from_row(row)
            except sqlite3.Error as e:
                logger.error("Failed to get quarantine entry id=%s: %s", entry_id, e)
        return None

    def get_entry_by_original_path(self, original_path: str) -> QuarantineEntry | None:
        """
        Retrieve a quarantine entry by original file path.

        Args:
            original_path: The original path of the quarantined file

        Returns:
            QuarantineEntry if found, None otherwise
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT id, original_path, quarantine_path, threat_name,
                               detection_date, file_size, file_hash, original_permissions
                        FROM quarantine WHERE original_path = ?
                        """,
                        (original_path,),
                    )
                    row = cursor.fetchone()
                    if row:
                        return QuarantineEntry.from_row(row)
            except sqlite3.Error as e:
                logger.error(
                    "Failed to get quarantine entry by original_path=%s: %s",
                    original_path,
                    e,
                )
        return None

    def get_all_entries(self) -> list[QuarantineEntry]:
        """
        Retrieve all quarantine entries, sorted by detection date (newest first).

        Returns:
            List of QuarantineEntry objects
        """
        entries = []
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT id, original_path, quarantine_path, threat_name,
                               detection_date, file_size, file_hash, original_permissions
                        FROM quarantine
                        ORDER BY detection_date DESC
                        """
                    )
                    for row in cursor.fetchall():
                        entries.append(QuarantineEntry.from_row(row))
            except sqlite3.Error as e:
                logger.error("Failed to get all quarantine entries: %s", e)
        return entries

    def remove_entry(self, entry_id: int) -> bool:
        """
        Remove a quarantine entry from the database.

        Args:
            entry_id: The ID of the entry to remove

        Returns:
            True if removed successfully, False otherwise
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        "DELETE FROM quarantine WHERE id = ?",
                        (entry_id,),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error("Failed to remove quarantine entry id=%s: %s", entry_id, e)
                return False

    def get_total_size(self) -> int:
        """
        Calculate the total size of all quarantined files.

        Returns:
            Total size in bytes
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM quarantine")
                    row = cursor.fetchone()
                    if row:
                        return row[0]
            except sqlite3.Error as e:
                logger.error("Failed to get quarantine total size: %s", e)
        return 0

    def get_entry_count(self) -> int:
        """
        Get the total number of quarantine entries.

        Returns:
            Number of entries
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM quarantine")
                    row = cursor.fetchone()
                    if row:
                        return row[0]
            except sqlite3.Error as e:
                logger.error("Failed to get quarantine entry count: %s", e)
        return 0

    def get_old_entries(self, days: int = 30) -> list[QuarantineEntry]:
        """
        Get entries older than the specified number of days.

        Args:
            days: Number of days threshold (default 30)

        Returns:
            List of QuarantineEntry objects older than the threshold
        """
        entries = []
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT id, original_path, quarantine_path, threat_name,
                               detection_date, file_size, file_hash, original_permissions
                        FROM quarantine
                        WHERE detection_date < ?
                        ORDER BY detection_date ASC
                        """,
                        (cutoff_date,),
                    )
                    for row in cursor.fetchall():
                        entries.append(QuarantineEntry.from_row(row))
            except sqlite3.Error as e:
                logger.error("Failed to get old quarantine entries (days=%s): %s", days, e)
        return entries

    def cleanup_old_entries(self, days: int = 30) -> int:
        """
        Remove entries older than the specified number of days.

        Note: This only removes database entries. The caller is responsible
        for deleting the actual quarantined files before calling this.

        Args:
            days: Number of days threshold (default 30)

        Returns:
            Number of entries removed
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        "DELETE FROM quarantine WHERE detection_date < ?",
                        (cutoff_date,),
                    )
                    conn.commit()
                    return cursor.rowcount
            except sqlite3.Error as e:
                logger.error("Failed to cleanup old quarantine entries (days=%s): %s", days, e)
                return 0

    def entry_exists(self, original_path: str) -> bool:
        """
        Check if an entry already exists for the given original path.

        Args:
            original_path: The original file path to check

        Returns:
            True if an entry exists, False otherwise
        """
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT 1 FROM quarantine WHERE original_path = ? LIMIT 1",
                        (original_path,),
                    )
                    return cursor.fetchone() is not None
            except sqlite3.Error as e:
                logger.error(
                    "Failed to check quarantine entry existence for %s: %s",
                    original_path,
                    e,
                )
                return False

    def close(self) -> None:
        """
        Close database connections and cleanup.

        When connection pooling is enabled, this closes all connections in the pool.
        """
        if self._pool is not None:
            self._pool.close_all()
