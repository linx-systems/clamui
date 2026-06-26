# ClamUI SQLite Connection Pool Module
"""
SQLite connection pool for the quarantine database.

Manages a pool of SQLite connections to reduce connection overhead for
batch operations and UI updates that make multiple quick queries.

Security Considerations:
    This module applies the same security hardening as QuarantineDatabase, setting
    restrictive 0o600 permissions on database files to prevent unauthorized access
    to sensitive quarantine metadata (file paths, threat names, SHA-256 hashes) by
    other users on multi-user systems.
"""

import logging
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class ConnectionPool:
    """
    Thread-safe connection pool for SQLite database connections.

    Manages a pool of SQLite connections to reduce the overhead of creating
    and configuring new connections for each database operation. Connections
    are stored in a queue and reused across operations.

    Attributes:
        _db_path: Path to the SQLite database file
        _pool_size: Maximum number of connections in the pool
        _pool: Queue storing available connections
        _lock: Thread lock for thread-safe operations
        _total_connections: Total number of connections created
        _closed: Flag indicating if the pool has been closed
    """

    # Database file permissions: 0o600 (owner read/write only)
    # Protects sensitive quarantine metadata from unauthorized access:
    # - Original file paths (reveals system structure and user activity)
    # - Threat names (indicates which malware was detected)
    # - SHA-256 hashes (could be used to identify/recover malware samples)
    DB_FILE_PERMISSIONS = 0o600

    def __init__(self, db_path: str, pool_size: int = 5):
        """
        Initialize the connection pool.

        Args:
            db_path: Path to the SQLite database file
            pool_size: Maximum number of connections to maintain in the pool (default: 5)

        Raises:
            ValueError: If pool_size is less than 1
        """
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")

        self._db_path = Path(db_path)
        self._pool_size = pool_size
        self._pool: queue.Queue = queue.Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._total_connections = 0  # Track total connections created
        self._closed = False  # Track if pool has been closed

    def _create_connection(self) -> sqlite3.Connection:
        """
        Create a new SQLite connection with WAL mode and foreign keys enabled.

        This method creates a connection with the same configuration as used
        in QuarantineDatabase._get_connection() to ensure consistency.

        Returns:
            Configured SQLite connection object

        Raises:
            sqlite3.Error: If connection creation or configuration fails
        """
        conn = sqlite3.connect(str(self._db_path), timeout=30.0, check_same_thread=False)
        try:
            # Enable WAL mode for better concurrency and corruption prevention
            conn.execute("PRAGMA journal_mode=WAL")
            # Enable foreign key constraints
            conn.execute("PRAGMA foreign_keys=ON")

            # SECURITY: Secure database file permissions after WAL mode is enabled
            # Applies 0o600 permissions to prevent unauthorized access to sensitive metadata
            # (file paths, threat names, SHA-256 hashes) by other users on the system.
            # This runs when the database file is first created to ensure the main database
            # file and WAL/SHM files (created by SQLite's Write-Ahead Logging mode) have
            # restrictive permissions. See _secure_db_file_permissions() for details.
            self._secure_db_file_permissions()

            return conn
        except sqlite3.Error:
            # Close connection on configuration failure
            conn.close()
            raise

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
                # Silently handle permission errors to avoid breaking database functionality
                # on systems with restrictive security policies or immutable files
                logger.debug("Failed to enforce SQLite permissions on %s", db_file, exc_info=True)
            finally:
                os.close(fd)

    def acquire(self, timeout: float | None = None) -> sqlite3.Connection:
        """
        Acquire a connection from the pool.

        Returns a connection from the pool if available, or creates a new one
        if the pool is empty and the maximum pool size has not been reached.

        Args:
            timeout: Maximum time in seconds to wait for a connection.
                    None means wait indefinitely (default).

        Returns:
            A configured SQLite connection

        Raises:
            queue.Empty: If timeout expires while waiting for a connection
            RuntimeError: If the pool has been closed
        """
        # Check if pool is closed
        if self._closed:
            raise RuntimeError("Connection pool has been closed")

        # STEP 1: Try to get from pool first (non-blocking)
        try:
            return self._pool.get(block=False)
        except queue.Empty:
            logger.debug(
                "SQLite connection pool is empty; attempting to create or wait for a connection"
            )

        # STEP 2: Pool empty - check if we can create new connection
        with self._lock:
            if self._total_connections < self._pool_size:
                # We can create a new connection
                conn = self._create_connection()
                self._total_connections += 1
                return conn

        # STEP 3: At max capacity - wait for a released connection. Poll instead of
        # blocking forever on the queue so that if capacity frees up (a broken
        # connection was discarded by release(), decrementing _total_connections),
        # this waiter can create a fresh connection rather than stranding on an
        # empty queue that no one will ever put to.
        deadline = None if timeout is None else time.monotonic() + timeout
        poll_interval = 0.1
        while True:
            # Re-check capacity under the lock: a concurrent release() may have
            # discarded an invalid connection, leaving room to create a new one.
            with self._lock:
                if self._closed:
                    raise RuntimeError("Connection pool has been closed")
                if self._total_connections < self._pool_size:
                    conn = self._create_connection()
                    self._total_connections += 1
                    return conn
            if deadline is None:
                wait = poll_interval
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                wait = min(poll_interval, remaining)
            try:
                return self._pool.get(block=True, timeout=wait)
            except queue.Empty:
                continue

    def release(self, conn: sqlite3.Connection) -> None:
        """
        Release a connection back to the pool.

        Validates the connection is still usable before returning it to the pool.
        Invalid connections are closed and discarded instead of being returned.

        Args:
            conn: The connection to release back to the pool

        Raises:
            RuntimeError: If the pool has been closed
        """
        # Check if pool is closed
        if self._closed:
            # Pool is closed - just close the connection
            conn.close()
            return

        # Validate connection health before returning to pool
        try:
            # Execute a simple query to verify connection is usable
            conn.execute("SELECT 1")
            # Connection is valid - return to pool
            self._pool.put(conn, block=False)
        except (sqlite3.Error, sqlite3.ProgrammingError, queue.Full):
            # Connection is invalid, has thread issues, or pool is full - close and discard
            # This handles: database locked, connection closed, thread affinity, or pool overflow
            conn.close()
            # Decrement total connections count since we're discarding this one
            with self._lock:
                self._total_connections -= 1

    @contextmanager
    def get_connection(
        self, timeout: float | None = None
    ) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager that acquires and releases a connection automatically.

        Provides the same interface as QuarantineDatabase._get_connection() for
        easy integration. Acquires a connection on entry, commits transactions
        on normal exit, and ensures the connection is released even on exceptions.

        Args:
            timeout: Maximum time in seconds to wait for a connection.
                    None means wait indefinitely (default).

        Yields:
            A configured SQLite connection from the pool

        Raises:
            queue.Empty: If timeout expires while waiting for a connection
            RuntimeError: If the pool has been closed

        Example:
            >>> pool = ConnectionPool("path/to/db.sqlite")
            >>> with pool.get_connection() as conn:
            ...     conn.execute("INSERT INTO table VALUES (?)", (value,))
        """
        conn = self.acquire(timeout=timeout)
        try:
            yield conn
            # Commit transaction on normal exit
            conn.commit()
        except Exception:
            # Rollback transaction on exception
            try:
                conn.rollback()
            except sqlite3.Error:
                # Ignore rollback errors - connection may be invalid
                logger.debug("Failed to rollback SQLite transaction", exc_info=True)
            raise
        finally:
            # Always release connection back to pool
            self.release(conn)

    def get_stats(self) -> dict:
        """
        Get current pool statistics for debugging and monitoring.

        Returns a dictionary containing pool statistics including pool size,
        available connections, total connections created, and active connections.

        Returns:
            Dictionary with the following keys:
                - pool_size: Maximum number of connections in the pool
                - available_count: Number of connections currently available in the pool
                - total_created: Total number of connections created
                - active_count: Number of connections currently in use (total - available)
                - is_closed: Whether the pool has been closed

        Thread-safe operation using internal lock.

        Example:
            >>> pool = ConnectionPool("path/to/db.sqlite", pool_size=5)
            >>> stats = pool.get_stats()
            >>> print(f"Active: {stats['active_count']}/{stats['pool_size']}")
            Active: 0/5
        """
        with self._lock:
            available_count = self._pool.qsize()
            active_count = self._total_connections - available_count

            return {
                "pool_size": self._pool_size,
                "available_count": available_count,
                "total_created": self._total_connections,
                "active_count": active_count,
                "is_closed": self._closed,
            }

    def __del__(self) -> None:
        """Safety-net destructor to close leaked connections on GC."""
        if getattr(self, "_closed", True) is False:
            self.close_all()

    def close_all(self) -> None:
        """
        Close all connections in the pool and prevent new connections.

        This method drains the connection pool, closes all connections, and sets
        a flag to prevent new connections from being created. Safe to call multiple
        times. Essential for proper resource cleanup.

        After calling this method:
        - All connections in the pool are closed
        - acquire() will raise RuntimeError
        - release() will close connections instead of returning them to pool

        Thread-safe operation using internal lock.
        """
        with self._lock:
            # Set closed flag to prevent new connections
            self._closed = True

            # Drain and close all connections from the pool
            while True:
                try:
                    # Get connection without blocking
                    conn = self._pool.get(block=False)
                    # Close the connection
                    try:
                        conn.close()
                    except sqlite3.Error:
                        # Ignore errors closing already-closed connections
                        logger.debug(
                            "Failed to close SQLite connection during pool shutdown", exc_info=True
                        )
                    # Decrement total connections count
                    self._total_connections -= 1
                except queue.Empty:
                    # Pool is empty - we're done
                    break
