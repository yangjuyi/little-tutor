"""运行路径解析与测试环境隔离。"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
_IS_TEST_RUNTIME = "unittest" in sys.modules and "TUTOR_RUNTIME_DIR" not in os.environ
_RUNTIME_DIR = (
    Path(tempfile.mkdtemp(prefix="little-tutor-tests-"))
    if _IS_TEST_RUNTIME
    else Path(os.getenv("TUTOR_RUNTIME_DIR", str(BASE_DIR)))
)

DATABASE_PATH = Path(
    os.getenv("TUTOR_DB_PATH", str(_RUNTIME_DIR / "tutor.db"))
)
CHECKPOINT_DB_PATH = Path(
    os.getenv("TUTOR_CHECKPOINT_PATH", str(_RUNTIME_DIR / "checkpoints.db"))
)


def _cleanup_test_runtime() -> None:
    if not _IS_TEST_RUNTIME:
        return
    try:
        from app.adapters.checkpoint import close_default_checkpointer
        from app.adapters.persistence import engine

        close_default_checkpointer()
        engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_RUNTIME_DIR, ignore_errors=True)


atexit.register(_cleanup_test_runtime)
