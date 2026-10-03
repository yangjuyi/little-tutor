"""Tests for runtime SQLite backups and retention."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from scripts.backup_databases import backup_sqlite, prune_backups


class TestBackupDatabases(unittest.TestCase):
    def test_sqlite_backup_copies_committed_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.db"
            target = root / "backup" / "copy.db"
            connection = sqlite3.connect(source)
            connection.execute("CREATE TABLE t (value TEXT)")
            connection.execute("INSERT INTO t VALUES ('ok')")
            connection.commit()
            connection.close()

            backup_sqlite(source, target)

            copied = sqlite3.connect(target)
            try:
                row = copied.execute("SELECT value FROM t").fetchone()
            finally:
                copied.close()
            self.assertEqual(row, ("ok",))

    def test_prune_backups_keeps_newest_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            now = time.time()
            for index in range(3):
                path = root / f"backup-{index}.db"
                path.write_bytes(b"x")
                os.utime(path, (now + index, now + index))
            prune_backups(root, keep=2)
            self.assertEqual(
                {path.name for path in root.glob("*.db")},
                {"backup-1.db", "backup-2.db"},
            )


if __name__ == "__main__":
    unittest.main()
