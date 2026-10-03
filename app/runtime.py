"""运行路径解析与测试环境隔离。"""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
_RUNTIME_DIR = Path(os.getenv("TUTOR_RUNTIME_DIR", str(BASE_DIR)))

DATABASE_PATH = Path(
    os.getenv("TUTOR_DB_PATH", str(_RUNTIME_DIR / "tutor.db"))
)
CHECKPOINT_DB_PATH = Path(
    os.getenv("TUTOR_CHECKPOINT_PATH", str(_RUNTIME_DIR / "checkpoints.db"))
)
