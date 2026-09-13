"""Checkpointer 装配（P2 持久化）。

生产默认用文件级 SqliteSaver（checkpoints.db）：进程重启 / 内存清零后，
老师未批完的审批可凭 thread_id 续跑（spec：会话状态落库）。
测试注入 InMemorySaver 保持隔离；并发写入留 P2 Send 阶段一并处理。
"""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from app.runtime import CHECKPOINT_DB_PATH

CHECKPOINT_DB = CHECKPOINT_DB_PATH

_default_saver: SqliteSaver | None = None


def close_default_checkpointer() -> None:
    """关闭进程级 checkpointer 连接，供临时环境清理与测试退出使用。"""
    global _default_saver
    if _default_saver is None:
        return
    conn = getattr(_default_saver, "conn", None)
    if conn is not None:
        conn.close()
    _default_saver = None


def default_checkpointer() -> SqliteSaver:
    """进程级共享的文件 SqliteSaver（懒加载单连接）。

    WAL 模式 + busy_timeout：多线程并发写不再立即报 locked，
    写操作排队等锁释放（30s 上限）。
    """
    global _default_saver
    if _default_saver is None:
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        _default_saver = SqliteSaver(conn)
    return _default_saver
