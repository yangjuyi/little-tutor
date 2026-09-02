"""
app/db.py — SQLite 连接与建表（SQLAlchemy 2.x）
=================================================

数据层设计见 PROJECT_SPEC.md 第 6 章 + §16：
- 7 张表：students / knowledge_points / questions / mastery / answer_records /
  profiles / teacher_decisions
- 掌握度 3 级（MasteryLevel，与难度混合矩阵同一套词汇），学生画像存 JSON
- SQLAlchemy ORM 抽象，未来可平滑切换 Postgres

用法：
    from app.db import init_db, SessionLocal
    init_db()                 # 建表（幂等）
    with SessionLocal() as s: # 操作数据库
        ...
命令行直接初始化：
    python -m app.db
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = f"sqlite:///{BASE_DIR / 'tutor.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # FastAPI 多线程访问 SQLite 需要
    echo=False,                                 # 调试 SQL 可改为 True
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""


class MasteryLevel(str, Enum):
    """知识点掌握度 3 级（spec §16；与 DIFFICULTY_RATIOS 词汇一致）"""

    WEAK = "weak"                 # 薄弱
    MID = "mid"                   # 中等
    STRONG = "strong"             # 扎实


# ============================================================
# 学生
# ============================================================
class Student(Base):
    """学生表（先 1 个，架构支持多个）"""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    grade: Mapped[str] = mapped_column(String(20), default="初三")
    subjects: Mapped[str] = mapped_column(String(100), default="数学,物理,化学")
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 目标/中考目标
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    mastery: Mapped[list[Mastery]] = relationship(back_populates="student")
    answers: Mapped[list[AnswerRecord]] = relationship(back_populates="student")
    profile: Mapped[Profile | None] = relationship(back_populates="student", uselist=False)


# ============================================================
# 知识点
# ============================================================
class KnowledgePoint(Base):
    """知识点表（知识卡片，见规格 6.2）"""

    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(20), index=True)      # 数学/物理/化学
    grade: Mapped[str] = mapped_column(String(20), default="初三")
    chapter: Mapped[str] = mapped_column(String(100))                 # 章节
    kp_name: Mapped[str] = mapped_column(String(100))                 # 知识点名称
    concept: Mapped[str] = mapped_column(Text)                        # 概念
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)  # 公式
    difficulty: Mapped[str] = mapped_column(String(20), default="中等")  # 简单/中等/难
    exam_importance: Mapped[str] = mapped_column(
        String(10), default="medium"
    )                                                      # 中考重要性 high/medium/low
    common_errors: Mapped[list] = mapped_column(JSON, default=list)  # 易错点列表
    typical_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_style: Mapped[str | None] = mapped_column(Text, nullable=True)

    questions: Mapped[list[Question]] = relationship(back_populates="knowledge_point")


# ============================================================
# 题库
# ============================================================
class Question(Base):
    """题库表（题目 AI 原创，无版权风险，见规格 6.1）"""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id"), index=True)
    stem: Mapped[str] = mapped_column(Text)                             # 题干
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)   # 选项（选择题）
    answer: Mapped[str] = mapped_column(Text)                           # 答案
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)   # 解析
    difficulty: Mapped[str] = mapped_column(String(20), default="中等")
    source: Mapped[str] = mapped_column(String(20), default="AI")       # AI/人工

    knowledge_point: Mapped[KnowledgePoint] = relationship(back_populates="questions")


# ============================================================
# 掌握度（自适应引擎的心脏）
# ============================================================
class Mastery(Base):
    """掌握度表：每个学生在每个知识点的掌握情况（见规格 6.1/6.3）"""

    __tablename__ = "mastery"
    __table_args__ = (UniqueConstraint("student_id", "kp_id", name="uq_student_kp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id"), index=True)
    level: Mapped[str] = mapped_column(String(20), default=MasteryLevel.WEAK.value)
    confidence: Mapped[float] = mapped_column(default=0.0)              # 0~1 置信度
    wrong_count: Mapped[int] = mapped_column(default=0)
    last_status: Mapped[str | None] = mapped_column(Text, nullable=True)  # 最近一次作答情况
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    student: Mapped[Student] = relationship(back_populates="mastery")
    knowledge_point: Mapped[KnowledgePoint] = relationship()


# ============================================================
# 做题记录
# ============================================================
class AnswerRecord(Base):
    """做题记录表（喂给画像更新，见规格 6.1）"""

    __tablename__ = "answer_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    answer: Mapped[str] = mapped_column(Text)                            # 学生提交的答案
    is_correct: Mapped[bool] = mapped_column(default=False)
    used_seconds: Mapped[int] = mapped_column(default=0)
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 8 类易错之一
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    student: Mapped[Student] = relationship(back_populates="answers")


# ============================================================
# 老师仲裁记录（HITL 可追溯：AI 建议了什么，老师怎么裁）
# ============================================================
class TeacherDecision(Base):
    """老师对画像更新建议的仲裁记录（spec §16：题级→批级可追溯）"""

    __tablename__ = "teacher_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    kp_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(10))          # accept / reject / edit
    proposal: Mapped[dict] = mapped_column(JSON, default=dict)  # AI 当时的建议原文
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ============================================================
# 学生画像（完整 JSON，老师可改，见规格 6.3/6.5）
# ============================================================
class Profile(Base):
    """学生画像表：完整画像存 JSON；AI 建议，老师确认后写回"""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id"), unique=True, index=True
    )
    profile: Mapped[dict] = mapped_column(JSON, default=dict)          # 6.3 完整画像结构
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    student: Mapped[Student] = relationship(back_populates="profile")


# ============================================================
# 初始化
# ============================================================
def init_db() -> None:
    """创建所有表（幂等：已存在则跳过）"""
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    import sys

    # Windows 控制台默认 GBK，重配 UTF-8 避免 emoji/中文打印崩溃
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    init_db()
    print("✅ 数据库已初始化：", (BASE_DIR / "tutor.db"))
