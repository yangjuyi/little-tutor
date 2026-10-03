"""Cross-process lease contention against a real SQLite file."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestMultiprocessLease(unittest.TestCase):
    def test_only_one_process_acquires_same_lease(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "lease.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE practice_sessions ("
                "session_id TEXT PRIMARY KEY, "
                "lease_owner TEXT, "
                "lease_expires_at DATETIME)"
            )
            connection.execute(
                "INSERT INTO practice_sessions(session_id) VALUES ('shared')"
            )
            connection.commit()
            connection.close()

            env = os.environ.copy()
            env["TUTOR_DB_PATH"] = str(db_path)
            env["TUTOR_LEASE_TTL_SECONDS"] = "30"
            code = (
                "from app.adapters.session_store import acquire_practice_lease;"
                "print('ok' if acquire_practice_lease("
                "'shared', owner=__import__('sys').argv[1], "
                "ttl_seconds=30) else 'busy')"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", code, owner],
                    cwd=project_root,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for owner in ("worker-a", "worker-b")
            ]
            outputs = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(stdout.strip())
            self.assertEqual(sorted(outputs), ["busy", "ok"])


if __name__ == "__main__":
    unittest.main()
