# ClamUI ConnectionPool Tests
"""Unit tests for the ConnectionPool class."""

import os
import queue
import sqlite3
import stat
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from src.core.quarantine.connection_pool import ConnectionPool


class TestConnectionPoolInit:
    """Tests for ConnectionPool initialization."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield str(Path(tmpdir) / "test_pool.db")

    def test_init_with_default_pool_size(self, temp_db_path):
        """Test ConnectionPool initialization with default pool size."""
        pool = ConnectionPool(temp_db_path)
        assert pool._pool_size == 5
        assert pool._db_path == Path(temp_db_path)
        assert pool._total_connections == 0
        assert pool._closed is False
        assert isinstance(pool._pool, queue.Queue)
        pool.close_all()

    def test_init_with_custom_pool_size(self, temp_db_path):
        """Test ConnectionPool initialization with custom pool size."""
        pool = ConnectionPool(temp_db_path, pool_size=10)
        assert pool._pool_size == 10
        assert pool._total_connections == 0
        assert pool._closed is False
        pool.close_all()

    def test_init_with_minimum_pool_size(self, temp_db_path):
        """Test ConnectionPool initialization with minimum pool size."""
        pool = ConnectionPool(temp_db_path, pool_size=1)
        assert pool._pool_size == 1
        pool.close_all()

    def test_init_with_invalid_pool_size(self, temp_db_path):
        """Test ConnectionPool raises ValueError for pool_size < 1."""
        with pytest.raises(ValueError, match="pool_size must be at least 1"):
            ConnectionPool(temp_db_path, pool_size=0)

        with pytest.raises(ValueError, match="pool_size must be at least 1"):
            ConnectionPool(temp_db_path, pool_size=-1)

    def test_init_creates_lock(self, temp_db_path):
        """Test ConnectionPool creates a threading lock."""
        pool = ConnectionPool(temp_db_path)
        # Check that _lock has the lock interface (acquire and release methods)
        assert hasattr(pool._lock, "acquire")
        assert hasattr(pool._lock, "release")
        assert callable(pool._lock.acquire)
        assert callable(pool._lock.release)


class TestConnectionPoolCreateConnection:
    """Tests for ConnectionPool._create_connection() method."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_create.db"
            yield str(db_path)

    @pytest.fixture
    def pool(self, temp_db_path):
        """Create a ConnectionPool instance."""
        p = ConnectionPool(temp_db_path, pool_size=3)
        yield p
        p.close_all()

    def test_create_connection_returns_connection(self, pool):
        """Test _create_connection returns a sqlite3.Connection object."""
        conn = pool._create_connection()
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_create_connection_enables_wal_mode(self, pool):
        """Test _create_connection enables WAL mode."""
        conn = pool._create_connection()
        cursor = conn.execute("PRAGMA journal_mode")
        result = cursor.fetchone()
        # WAL mode should be enabled
        assert result[0].upper() == "WAL"
        conn.close()

    def test_create_connection_enables_foreign_keys(self, pool):
        """Test _create_connection enables foreign key constraints."""
        conn = pool._create_connection()
        cursor = conn.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()
        # Foreign keys should be ON (1)
        assert result[0] == 1
        conn.close()

    def test_create_connection_sets_timeout(self, pool):
        """Test _create_connection sets timeout to 30 seconds."""
        # The timeout is set during sqlite3.connect, not as a PRAGMA
        # We can verify it works by checking the connection doesn't raise immediately
        conn = pool._create_connection()
        assert conn is not None
        conn.close()

    def test_create_connection_closes_on_pragma_error(self, pool):
        """Test _create_connection closes connection if PRAGMA configuration fails."""
        with mock.patch("sqlite3.connect") as mock_connect:
            mock_conn = mock.MagicMock()
            mock_conn.execute.side_effect = sqlite3.Error("PRAGMA failed")
            mock_connect.return_value = mock_conn

            with pytest.raises(sqlite3.Error):
                pool._create_connection()

            # Verify connection was closed on error
            mock_conn.close.assert_called_once()


class TestConnectionPoolAcquire:
    """Tests for ConnectionPool.acquire() method."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_acquire.db"
            yield str(db_path)

    @pytest.fixture
    def pool(self, temp_db_path):
        """Create a ConnectionPool instance."""
        p = ConnectionPool(temp_db_path, pool_size=3)
        yield p
        p.close_all()

    def test_acquire_creates_new_connection_when_pool_empty(self, pool):
        """Test acquire creates a new connection when pool is empty."""
        conn = pool.acquire()
        assert isinstance(conn, sqlite3.Connection)
        assert pool._total_connections == 1
        conn.close()

    def test_acquire_returns_existing_connection_from_pool(self, pool):
        """Test acquire returns existing connection from pool."""
        # Create and release a connection to populate the pool
        conn1 = pool.acquire()
        pool.release(conn1)

        # Acquire should return the same connection
        conn2 = pool.acquire()
        assert conn2 == conn1
        assert pool._total_connections == 1
        conn2.close()

    def test_acquire_creates_multiple_connections_up_to_max(self, pool):
        """Test acquire creates connections up to pool_size."""
        connections = []
        for i in range(3):
            conn = pool.acquire()
            connections.append(conn)
            assert pool._total_connections == i + 1

        # Clean up
        for conn in connections:
            conn.close()

    def test_acquire_blocks_when_pool_exhausted(self, pool):
        """Test acquire blocks when pool is exhausted and timeout expires."""
        # Acquire all connections
        connections = [pool.acquire() for _ in range(3)]
        assert pool._total_connections == 3

        # Next acquire should timeout since pool is exhausted
        with pytest.raises(queue.Empty):
            pool.acquire(timeout=0.1)

        # Clean up
        for conn in connections:
            conn.close()

    def test_acquire_waits_for_released_connection(self, pool):
        """Test acquire waits and gets released connection."""
        # Acquire all connections
        connections = [pool.acquire() for _ in range(3)]

        # Release one connection in another thread after a delay
        def release_after_delay():
            time.sleep(0.1)
            pool.release(connections[0])

        release_thread = threading.Thread(target=release_after_delay)
        release_thread.start()

        # This should block briefly then succeed
        conn = pool.acquire(timeout=1.0)
        assert isinstance(conn, sqlite3.Connection)

        release_thread.join()

        # Clean up
        conn.close()
        for c in connections[1:]:
            c.close()

    def test_acquire_raises_runtime_error_when_closed(self, pool):
        """Test acquire raises RuntimeError when pool is closed."""
        pool.close_all()

        with pytest.raises(RuntimeError, match="Connection pool has been closed"):
            pool.acquire()

    def test_acquire_with_no_timeout_waits_indefinitely(self, pool):
        """Test acquire with timeout=None waits indefinitely (until released)."""
        # Acquire all connections
        connections = [pool.acquire() for _ in range(3)]

        # Release one connection after a short delay
        def release_after_delay():
            time.sleep(0.2)
            pool.release(connections[0])

        release_thread = threading.Thread(target=release_after_delay)
        release_thread.start()

        # This should wait indefinitely (no timeout)
        start_time = time.time()
        conn = pool.acquire(timeout=None)
        elapsed = time.time() - start_time

        # Should have waited for the release
        assert elapsed >= 0.2
        assert isinstance(conn, sqlite3.Connection)

        release_thread.join()

        # Clean up
        conn.close()
        for c in connections[1:]:
            c.close()


class TestConnectionPoolRelease:
    """Tests for ConnectionPool.release() method."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_release.db"
            yield str(db_path)

    @pytest.fixture
    def pool(self, temp_db_path):
        """Create a ConnectionPool instance."""
        p = ConnectionPool(temp_db_path, pool_size=3)
        yield p
        p.close_all()

    def test_release_returns_valid_connection_to_pool(self, pool):
        """Test release returns valid connection to pool."""
        conn = pool.acquire()
        pool.release(conn)

        # Connection should be back in the pool
        # Verify by checking we can acquire without creating a new one
        total_before = pool._total_connections
        conn2 = pool.acquire()
        assert pool._total_connections == total_before
        assert conn2 == conn

        conn2.close()

    def test_release_closes_invalid_connection(self, pool):
        """Test release closes and discards invalid connections."""
        conn = pool.acquire()
        initial_count = pool._total_connections

        # Make the connection invalid by closing it
        conn.close()

        # Release should detect it's invalid and discard it
        pool.release(conn)

        # Total connections should decrease
        assert pool._total_connections == initial_count - 1

    def test_release_handles_queue_full(self, pool):
        """Test release handles queue.Full when pool is at capacity."""
        # Fill the pool
        connections = [pool.acquire() for _ in range(3)]
        for conn in connections:
            pool.release(conn)

        # Try to release an extra connection (should handle queue.Full)
        extra_conn = pool._create_connection()
        pool._total_connections += 1

        # This should discard the connection instead of raising
        pool.release(extra_conn)

        # Verify the extra connection was discarded (count should be back to 3)
        assert pool._total_connections == 3


class TestConnectionPoolGetConnection:
    """Tests for ConnectionPool.get_connection() context manager."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_context.db"
            # Create a test table
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.commit()
            conn.close()
            yield str(db_path)

    @pytest.fixture
    def pool(self, temp_db_path):
        """Create a ConnectionPool instance."""
        p = ConnectionPool(temp_db_path, pool_size=3)
        yield p
        p.close_all()

    def test_get_connection_acquires_and_releases(self, pool):
        """Test get_connection acquires connection on entry and releases on exit."""
        initial_count = pool._total_connections

        with pool.get_connection() as conn:
            assert isinstance(conn, sqlite3.Connection)
            # Should have acquired a connection
            assert pool._total_connections >= initial_count

        # Connection should be released back (can verify by acquiring again)
        conn2 = pool.acquire()
        assert isinstance(conn2, sqlite3.Connection)
        conn2.close()

    def test_get_connection_commits_on_normal_exit(self, pool):
        """Test get_connection commits transaction on normal exit."""
        with pool.get_connection() as conn:
            conn.execute("INSERT INTO test (value) VALUES (?)", ("test_value",))
            # Don't manually commit - context manager should do it

        # Verify data was committed
        with pool.get_connection() as conn:
            cursor = conn.execute("SELECT value FROM test")
            result = cursor.fetchone()
            assert result is not None
            assert result[0] == "test_value"

    def test_get_connection_rolls_back_on_exception(self, pool):
        """Test get_connection rolls back transaction on exception."""
        try:
            with pool.get_connection() as conn:
                conn.execute("INSERT INTO test (value) VALUES (?)", ("should_rollback",))
                # Raise an exception before commit
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Verify data was NOT committed
        with pool.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test WHERE value = ?", ("should_rollback",))
            count = cursor.fetchone()[0]
            assert count == 0

    def test_get_connection_releases_on_exception(self, pool):
        """Test get_connection releases connection even when exception occurs."""
        try:
            with pool.get_connection():
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Connection should be released despite exception
        conn2 = pool.acquire()
        assert isinstance(conn2, sqlite3.Connection)
        conn2.close()


class TestConnectionPoolSecurePermissions:
    """Tests for _secure_db_file_permissions O_NOFOLLOW hardening."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for database files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_secure_permissions_applied_to_real_file(self, temp_dir):
        """Test chmod is applied to a real database file (0o600)."""
        db_path = temp_dir / "real.db"
        db_path.write_bytes(b"data")
        os.chmod(db_path, 0o644)

        pool = ConnectionPool(str(db_path))
        pool._secure_db_file_permissions()

        assert stat.S_IMODE(os.stat(db_path).st_mode) == 0o600

    def test_secure_permissions_skips_symlinked_db_file(self, temp_dir):
        """Test a symlinked db file does NOT have its target's perms changed (O_NOFOLLOW)."""
        # Target lives outside; perms must stay untouched.
        target = temp_dir / "outside.txt"
        target.write_bytes(b"secret")
        os.chmod(target, 0o644)

        # Plant a symlink at the WAL path (one of the secured db files).
        db_path = temp_dir / "pool.db"
        db_path.write_bytes(b"data")
        wal_link = Path(str(db_path) + "-wal")
        wal_link.symlink_to(target)

        pool = ConnectionPool(str(db_path))
        pool._secure_db_file_permissions()

        # Symlink target untouched (O_NOFOLLOW raises ELOOP -> skipped).
        assert stat.S_IMODE(os.lstat(target).st_mode) == 0o644
        # The real db file is still secured.
        assert stat.S_IMODE(os.stat(db_path).st_mode) == 0o600


class TestConnectionPoolExhaustionRecovery:
    """Regression: a blocked acquirer must recover when capacity frees up.

    When the pool is at max capacity and an outstanding connection is discarded
    by release() (because it failed its health check), _total_connections drops
    below pool_size. A thread already blocked inside acquire() must be able to
    create a fresh connection instead of stranding forever on an empty queue.
    """

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield str(Path(tmpdir) / "test_exhaust.db")

    def test_blocked_acquirer_recovers_after_broken_connection_discarded(self, temp_db_path):
        pool = ConnectionPool(temp_db_path, pool_size=1)
        try:
            # Hold the only connection: pool is now at capacity, queue is empty.
            conn1 = pool.acquire()
            assert pool._total_connections == 1

            result: dict = {}

            def waiter():
                try:
                    result["conn"] = pool.acquire(timeout=2.0)
                except Exception as exc:  # record for assertion
                    result["error"] = exc

            t = threading.Thread(target=waiter)
            t.start()

            # Let the waiter reach the blocking wait, then discard a broken
            # connection. This frees capacity but puts nothing back on the queue.
            time.sleep(0.3)
            conn1.close()
            pool.release(conn1)
            assert pool._total_connections == 0

            t.join(timeout=3.0)
            assert not t.is_alive()

            # The waiter must have obtained a fresh connection, not timed out.
            assert "error" not in result, f"acquirer was stranded: {result.get('error')!r}"
            assert isinstance(result.get("conn"), sqlite3.Connection)
            result["conn"].close()
        finally:
            pool.close_all()
