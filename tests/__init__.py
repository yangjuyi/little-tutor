"""测试包：评测与单元测试。"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path


_TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="little-tutor-tests-"))
os.environ["TUTOR_DB_PATH"] = str(_TEST_RUNTIME_DIR / "tutor.db")
os.environ["TUTOR_CHECKPOINT_PATH"] = str(_TEST_RUNTIME_DIR / "checkpoints.db")
os.environ["TUTOR_LOAD_SEED_CATALOG"] = "0"


def _cleanup_test_runtime() -> None:
    try:
        from app.adapters.checkpoint import close_default_checkpointer
        from app.adapters.persistence import engine

        close_default_checkpointer()
        engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_TEST_RUNTIME_DIR, ignore_errors=True)


atexit.register(_cleanup_test_runtime)
