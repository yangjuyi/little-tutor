"""旧 SQLite 文件兼容迁移测试。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

import app.adapters.persistence as persistence


class TestAnswerEvidenceMigration(unittest.TestCase):
    def test_old_answer_records_receive_evidence_columns(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_engine(f"sqlite:///{tmp.name}")
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "CREATE TABLE answer_records ("
                    "id INTEGER PRIMARY KEY, is_correct BOOLEAN NOT NULL)"
                )
                conn.exec_driver_sql(
                    "INSERT INTO answer_records (id, is_correct) "
                    "VALUES (1, 1), (2, 0)"
                )
            with patch.object(persistence, "engine", engine):
                persistence._ensure_answer_evidence_columns()
            with engine.connect() as conn:
                rows = conn.exec_driver_sql(
                    "SELECT attempt_no, first_attempt_correct, hint_count, "
                    "scaffold_level, assistance_level, evidence_weight "
                    "FROM answer_records ORDER BY id"
                ).fetchall()
            self.assertEqual(
                rows,
                [
                    (1, 1, 0, 0, "independent", 1.0),
                    (1, 0, 0, 0, "independent", 0.0),
                ],
            )
        finally:
            engine.dispose()
            os.unlink(tmp.name)

    def test_old_practice_sessions_receive_lease_columns(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_engine(f"sqlite:///{tmp.name}")
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "CREATE TABLE practice_sessions ("
                    "session_id TEXT PRIMARY KEY)"
                )
            with patch.object(persistence, "engine", engine):
                persistence._ensure_practice_lease_columns()
            with engine.connect() as conn:
                columns = {
                    row[1]
                    for row in conn.exec_driver_sql(
                        "PRAGMA table_info(practice_sessions)"
                    ).fetchall()
                }
            self.assertIn("lease_owner", columns)
            self.assertIn("lease_expires_at", columns)
        finally:
            engine.dispose()
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
