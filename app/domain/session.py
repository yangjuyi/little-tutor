"""练习会话的生命周期契约。

会话状态用于隔离答题事实与画像证据。LangGraph checkpoint 只负责恢复流程，
不能替代业务会话状态。
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal


SessionStatus = Literal["started", "completed", "aborted"]
ReviewStatus = Literal["pending", "accepted", "rejected"]
DataSource = Literal["real", "demo", "test"]


@dataclass(frozen=True, slots=True)
class PracticeSession:
    """一次练习会话的业务状态，不包含 LangGraph 运行时数据。"""

    session_id: str
    student_id: int
    kp_id: int
    status: SessionStatus = "started"
    review_status: ReviewStatus = "pending"
    data_source: DataSource = "real"
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def allows_mastery_evidence(self) -> bool:
        """只有真实、完成且老师确认的会话可以形成画像证据。"""
        return (
            self.status == "completed"
            and self.review_status == "accepted"
            and self.data_source == "real"
        )


def complete_session(
    session: PracticeSession, completed_at: datetime | None = None
) -> PracticeSession:
    """结束一场进行中的会话，进入待老师确认状态。"""
    if session.status != "started":
        raise ValueError("只有 started 会话可以结束")
    return replace(
        session,
        status="completed",
        review_status="pending",
        completed_at=completed_at or datetime.now(),
    )


def abandon_session(session: PracticeSession) -> PracticeSession:
    """标记中断或放弃会话；该会话不得形成画像证据。"""
    if session.status != "started":
        raise ValueError("只有 started 会话可以中断")
    return replace(session, status="aborted", review_status="pending")


def review_session(
    session: PracticeSession, decision: Literal["accepted", "rejected"]
) -> PracticeSession:
    """提交老师对已完成会话的最终决定。"""
    if session.status != "completed":
        raise ValueError("只有 completed 会话可以提交审核决定")
    if session.review_status != "pending":
        raise ValueError("会话审核决定只能提交一次")
    return replace(session, review_status=decision)
