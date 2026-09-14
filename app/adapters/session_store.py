"""练习会话生命周期的持久化适配器。"""

import os
import socket
import uuid
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, or_, update

from app.adapters.persistence import (
    AnswerRecord,
    PracticeSessionRecord,
    Question,
    SessionLocal,
    TeacherDecision,
)


ReviewDecision = Literal["accepted", "rejected"]
LEASE_OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def acquire_practice_lease(
    session_id: str,
    owner: str | None = None,
    ttl_seconds: int = 120,
) -> bool:
    """获取会话写租约；有效租约未过期时拒绝其他 worker。"""
    owner = owner or LEASE_OWNER
    now = datetime.now()
    expires_at = now + timedelta(seconds=max(1, ttl_seconds))
    with SessionLocal() as s:
        result = s.execute(
            update(PracticeSessionRecord)
            .where(
                PracticeSessionRecord.session_id == session_id,
                or_(
                    PracticeSessionRecord.lease_owner.is_(None),
                    PracticeSessionRecord.lease_owner == owner,
                    PracticeSessionRecord.lease_expires_at < now,
                ),
            )
            .values(lease_owner=owner, lease_expires_at=expires_at)
        )
        s.commit()
        return bool(result.rowcount)


def release_practice_lease(
    session_id: str,
    owner: str | None = None,
) -> None:
    """释放当前 worker 持有的会话租约；其他 owner 不受影响。"""
    owner = owner or LEASE_OWNER
    with SessionLocal() as s:
        s.execute(
            update(PracticeSessionRecord)
            .where(
                PracticeSessionRecord.session_id == session_id,
                PracticeSessionRecord.lease_owner == owner,
            )
            .values(lease_owner=None, lease_expires_at=None)
        )
        s.commit()


def start_practice_session(
    session_id: str,
    student_id: int,
    kp_id: int,
    data_source: str = "real",
) -> None:
    """幂等创建会话；重复调用不覆盖已发生的生命周期。"""
    if data_source not in ("real", "demo", "test"):
        raise ValueError("data_source 必须是 real/demo/test")
    with SessionLocal() as s:
        if s.get(PracticeSessionRecord, session_id) is not None:
            return
        s.add(PracticeSessionRecord(
            session_id=session_id,
            student_id=student_id,
            kp_id=kp_id,
            status="started",
            review_status="pending",
            data_source=data_source,
        ))
        s.commit()


def set_practice_session_data_source(
    session_id: str,
    data_source: str,
) -> None:
    """更新会话数据来源；test/demo 不进入掌握度证据。"""
    if data_source not in ("real", "demo", "test"):
        raise ValueError("data_source 必须是 real/demo/test")
    with SessionLocal() as s:
        row = s.get(PracticeSessionRecord, session_id)
        if row is None:
            raise ValueError(f"会话不存在：{session_id}")
        row.data_source = data_source
        s.commit()


def mark_practice_session_test(session_id: str) -> None:
    """把整场会话标记为测试数据，排除出画像证据。"""
    set_practice_session_data_source(session_id, "test")


def complete_practice_session(session_id: str) -> None:
    """将会话标记为已完成并进入待审核；重复调用保持幂等。"""
    with SessionLocal() as s:
        row = s.get(PracticeSessionRecord, session_id)
        if row is None:
            raise ValueError(f"会话不存在：{session_id}")
        if row.status == "completed":
            return
        if row.status != "started":
            raise ValueError(f"不能完成 {row.status} 状态的会话")
        row.status = "completed"
        row.review_status = "pending"
        row.completed_at = datetime.now()
        s.commit()


def abort_practice_session(session_id: str) -> None:
    """标记中断/失败会话；重复调用保持幂等，已结束会话不再改写。"""
    with SessionLocal() as s:
        row = s.get(PracticeSessionRecord, session_id)
        if row is None or row.status != "started":
            return
        row.status = "aborted"
        row.review_status = "pending"
        s.commit()


def review_practice_session(
    session_id: str, decision: ReviewDecision
) -> None:
    """写入老师对已完成会话的审核结果；同一决定可安全重放。"""
    if decision not in ("accepted", "rejected"):
        raise ValueError("decision 必须是 accepted/rejected")
    with SessionLocal() as s:
        row = s.get(PracticeSessionRecord, session_id)
        if row is None:
            raise ValueError(f"会话不存在：{session_id}")
        if row.status != "completed":
            raise ValueError("只有已完成的会话可以审核")
        if row.review_status == decision:
            return
        if row.review_status != "pending":
            raise ValueError("会话审核结果只能写入一次")
        row.review_status = decision
        s.commit()


def eligible_session_ids(student_id: int, kp_id: int) -> set[str]:
    """返回可进入掌握度计算的会话：真实、完成、老师已接受。"""
    with SessionLocal() as s:
        rows = (
            s.query(PracticeSessionRecord.session_id)
            .filter(
                PracticeSessionRecord.student_id == student_id,
                PracticeSessionRecord.kp_id == kp_id,
                PracticeSessionRecord.status == "completed",
                PracticeSessionRecord.review_status == "accepted",
                PracticeSessionRecord.data_source == "real",
            )
            .all()
        )
    return {row[0] for row in rows}


def backfill_legacy_session(
    session_id: str, data_source: str = "real"
) -> bool:
    """按既有作答与老师决定回填历史会话；无法唯一归属时拒绝回填。"""
    if data_source not in ("real", "demo", "test"):
        raise ValueError("data_source 必须是 real/demo/test")
    with SessionLocal() as s:
        identity = (
            s.query(AnswerRecord.student_id, Question.kp_id)
            .join(Question, Question.id == AnswerRecord.question_id)
            .filter(AnswerRecord.session_id == session_id)
            .distinct()
            .all()
        )
        if not identity:
            return False
        student_ids = {row[0] for row in identity}
        kp_ids = {row[1] for row in identity}
        if len(student_ids) != 1 or len(kp_ids) != 1:
            raise ValueError("历史会话跨学生或跨知识点，不能自动回填")

        decisions = {
            row[0]
            for row in (
                s.query(TeacherDecision.decision)
                .filter(TeacherDecision.session_id == session_id)
                .all()
            )
        }
        if "accept" in decisions:
            review_status = "accepted"
        elif "reject" in decisions:
            review_status = "rejected"
        else:
            review_status = "pending"

        row = s.get(PracticeSessionRecord, session_id)
        if row is None:
            row = PracticeSessionRecord(
                session_id=session_id,
                student_id=next(iter(student_ids)),
                kp_id=next(iter(kp_ids)),
            )
            s.add(row)
        row.status = "completed"
        row.review_status = review_status
        row.data_source = data_source
        row.completed_at = (
            s.query(func.max(AnswerRecord.created_at))
            .filter(AnswerRecord.session_id == session_id)
            .scalar()
        )
        s.commit()
    return True
