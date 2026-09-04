"""
build_knowledge_base.py — 知识库生成脚本
=========================================

作用
- 根据种子清单生成知识卡片；数学卡片用于当前 V1/V2 教学闭环，
  物理/化学卡片仅作为 V3 学科扩展的数据预留
- 知识卡片结构见规格 6.2：concept / formula / common_errors / exam_importance 等
- 优先覆盖：易错点（common_errors）与中考难考点（exam_importance: high）
- 输出：`data/generated/{学科}_knowledge.json`（供人工审校）+ 写入 SQLite

⚠️ 使用注意
1. 需要 `.env` 里配好 OPENAI_API_KEY（DeepSeek 等兼容接口）
2. 每张卡片 = 一次 LLM 调用；按 `--subject` 可只生成某一科
3. 已入库的知识点会跳过（幂等），可反复运行
4. 生成结果请**人工审校**后再用于教学（AI 可能出错）

▶️ 运行
    python data/build_knowledge_base.py                    # 生成种子清单全部卡片（含 V3 预留）
    python data/build_knowledge_base.py --subject 数学       # 只生成数学
    python data/build_knowledge_base.py --dry-run           # 只看清单，不调 API
    python data/build_knowledge_base.py --limit 5           # 只生成前 5 个
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows 控制台默认 GBK，重配 UTF-8 避免 emoji/中文打印崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ⭐ 让脚本所在目录的父目录（项目根）可被 import
#    这样才能 `from app.db import ...`（脚本放在 data/ 下）
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

# ============================================================
# 📚 种子清单：初三核心考点（可自行增删）
#    优先放：易错点多、中考高频的知识点
# ============================================================
SEED = [
    # ---- 数学 ----
    {"subject": "数学", "chapter": "一元二次方程", "kp_name": "一元二次方程的解法（公式法/配方法/因式分解法）"},
    {"subject": "数学", "chapter": "一元二次方程", "kp_name": "根的判别式与根的讨论"},
    {"subject": "数学", "chapter": "一元二次方程", "kp_name": "一元二次方程的实际应用"},
    {"subject": "数学", "chapter": "二次函数", "kp_name": "二次函数的图像与性质"},
    {"subject": "数学", "chapter": "二次函数", "kp_name": "二次函数与一元二次方程的关系"},
    {"subject": "数学", "chapter": "二次函数", "kp_name": "二次函数实际应用（最值问题）"},
    {"subject": "数学", "chapter": "相似三角形", "kp_name": "相似三角形的判定"},
    {"subject": "数学", "chapter": "相似三角形", "kp_name": "相似三角形的性质与应用"},
    {"subject": "数学", "chapter": "圆", "kp_name": "垂径定理"},
    {"subject": "数学", "chapter": "圆", "kp_name": "直线与圆的位置关系"},
    {"subject": "数学", "chapter": "圆", "kp_name": "圆周角定理"},
    {"subject": "数学", "chapter": "锐角三角函数", "kp_name": "三角函数定义与特殊角函数值"},
    {"subject": "数学", "chapter": "锐角三角函数", "kp_name": "解直角三角形"},
    {"subject": "数学", "chapter": "概率与统计", "kp_name": "概率的计算"},
    {"subject": "数学", "chapter": "概率与统计", "kp_name": "数据分析（平均数/方差）"},
    # ---- 物理 ----
    {"subject": "物理", "chapter": "力学", "kp_name": "力与重力"},
    {"subject": "物理", "chapter": "力学", "kp_name": "压强（固体/液体/大气压）"},
    {"subject": "物理", "chapter": "力学", "kp_name": "浮力（阿基米德原理）"},
    {"subject": "物理", "chapter": "力学", "kp_name": "简单机械（杠杆/滑轮）"},
    {"subject": "物理", "chapter": "力学", "kp_name": "功与机械效率"},
    {"subject": "物理", "chapter": "力学", "kp_name": "密度"},
    {"subject": "物理", "chapter": "电学", "kp_name": "电路识别与串并联"},
    {"subject": "物理", "chapter": "电学", "kp_name": "欧姆定律"},
    {"subject": "物理", "chapter": "电学", "kp_name": "电功率与电热"},
    {"subject": "物理", "chapter": "热学", "kp_name": "物态变化"},
    {"subject": "物理", "chapter": "热学", "kp_name": "比热容与热值"},
    {"subject": "物理", "chapter": "光学", "kp_name": "光的反射与折射"},
    # ---- 化学 ----
    {"subject": "化学", "chapter": "物质的构成", "kp_name": "分子、原子与离子"},
    {"subject": "化学", "chapter": "物质的构成", "kp_name": "元素与化学式"},
    {"subject": "化学", "chapter": "物质的构成", "kp_name": "化合价"},
    {"subject": "化学", "chapter": "化学变化", "kp_name": "质量守恒定律"},
    {"subject": "化学", "chapter": "化学变化", "kp_name": "化学方程式的书写与配平"},
    {"subject": "化学", "chapter": "身边的化学", "kp_name": "空气与氧气"},
    {"subject": "化学", "chapter": "身边的化学", "kp_name": "碳及其氧化物"},
    {"subject": "化学", "chapter": "身边的化学", "kp_name": "金属的化学性质"},
    {"subject": "化学", "chapter": "身边的化学", "kp_name": "酸、碱、盐"},
    {"subject": "化学", "chapter": "身边的化学", "kp_name": "溶液与溶解度"},
    {"subject": "化学", "chapter": "身边的化学", "kp_name": "燃料与能源"},
]

# ============================================================
# 🧠 LLM + 结构化输出（规格 6.2 的知识卡片结构）
# ============================================================
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
    base_url=os.getenv("OPENAI_API_BASE"),
    temperature=0,  # 知识卡片要求准确，温度 0
    # 关闭 DeepSeek 思考模式（2026-08-20）：
    #   1) 省 token（思考链很耗钱，17号还涨价了）
    #   2) 让 function_calling 可用（思考模式下不支持工具调用）
    # ⚠️ 若 LangChain 版本不认 extra_body，改用 openai SDK 直接传
    model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
)


class KnowledgeCard(BaseModel):
    """知识卡片（规格 6.2）—— 用 Pydantic 约束 LLM 的输出结构"""

    subject: str = Field(description="学科：数学/物理/化学")
    grade: str = Field(default="初三", description="年级")
    chapter: str = Field(description="所属章节")
    kp_name: str = Field(description="知识点名称")
    concept: str = Field(description="核心概念，通俗准确，初三学生能听懂")
    formula: str | None = Field(default=None, description="公式（若适用），否则留空")
    difficulty: str = Field(description="难度：简单/中等/难")
    exam_importance: str = Field(description="中考重要性：high/medium/low")
    common_errors: list[str] = Field(description="易错点列表（2-4 条，务必具体、写真实常见错误）")
    typical_question: str = Field(description="典型例题题干")
    explanation_style: str = Field(description="推荐讲解方式（如：类比/图形/生活实例/口诀）")


# ⭐ with_structured_output：让 LLM 直接返回符合 KnowledgeCard 的 JSON
#    ⚠️ 用 method="json_mode"（而非默认的 function_calling）：
#    DeepSeek 的思考模式不支持 tool_choice，而 json_mode 只要 prompt 里含 "json" 即可
structured_llm = llm.with_structured_output(KnowledgeCard, method="json_mode")


def generate_card(seed: dict) -> KnowledgeCard:
    """为一个知识点生成知识卡片"""
    prompt = f"""你是深耕初三{seed['subject']}中考的金牌教师。请为以下知识点制作一张高质量知识卡片，并以 JSON 格式返回。

- 学科：{seed['subject']}
- 章节：{seed['chapter']}
- 知识点：{seed['kp_name']}

要求：
1. concept：概念准确、表述通俗，初三学生能听懂
2. common_errors：写 2-4 条真实高频易错点，越具体越好（例如"忘记先判断判别式 b²-4ac 的正负"）
3. exam_importance：按中考出题频率标 high / medium / low
4. typical_question：出一道该知识点的典型中考题（只要题干）
5. explanation_style：推荐一种最有效的讲解方式
6. 全程用中文回答
7. JSON 字段包括：subject, grade, chapter, kp_name, concept, formula, difficulty, exam_importance, common_errors, typical_question, explanation_style"""
    return structured_llm.invoke(prompt)


# ============================================================
# 🗄️ 写入 SQLite
# ============================================================
def insert_to_db(cards: list[dict]) -> int:
    """把知识卡片写入 knowledge_points 表（已存在的跳过）"""
    from app.db import SessionLocal, KnowledgePoint
    from sqlalchemy import select

    count = 0
    with SessionLocal() as session:
        for c in cards:
            exists = session.execute(
                select(KnowledgePoint).where(
                    KnowledgePoint.subject == c["subject"],
                    KnowledgePoint.kp_name == c["kp_name"],
                )
            ).scalar_one_or_none()
            if exists:
                continue
            session.add(
                KnowledgePoint(
                    subject=c["subject"],
                    grade=c.get("grade", "初三"),
                    chapter=c["chapter"],
                    kp_name=c["kp_name"],
                    concept=c["concept"],
                    formula=c.get("formula"),
                    difficulty=c["difficulty"],
                    exam_importance=c["exam_importance"],
                    common_errors=c["common_errors"],
                    typical_question=c["typical_question"],
                    explanation_style=c["explanation_style"],
                )
            )
            count += 1
        session.commit()
    return count


def export_json() -> None:
    """从数据库导出各学科完整知识卡片 JSON。

    数据库是唯一事实来源，JSON 只是它的导出——
    这样每次运行写入的是"该学科全部卡片"，不会被单次运行覆盖。
    """
    from app.db import SessionLocal, KnowledgePoint
    from sqlalchemy import select

    out_dir = BASE_DIR / "data" / "generated"
    out_dir.mkdir(exist_ok=True)

    with SessionLocal() as session:
        rows = session.execute(
            select(KnowledgePoint).order_by(KnowledgePoint.chapter, KnowledgePoint.id)
        ).scalars().all()

    by_subject: dict[str, list[dict]] = {}
    for k in rows:
        by_subject.setdefault(k.subject, []).append(
            {
                "subject": k.subject,
                "grade": k.grade,
                "chapter": k.chapter,
                "kp_name": k.kp_name,
                "concept": k.concept,
                "formula": k.formula,
                "difficulty": k.difficulty,
                "exam_importance": k.exam_importance,
                "common_errors": k.common_errors,
                "typical_question": k.typical_question,
                "explanation_style": k.explanation_style,
            }
        )

    for subject, cards in by_subject.items():
        path = out_dir / f"{subject}_knowledge.json"
        path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"📄 已导出 {len(cards)} 张卡片 → {path}")


# ============================================================
# 🚀 主流程
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成知识库：数学用于 V1/V2，物理/化学为 V3 扩展预留"
    )
    parser.add_argument("--subject", choices=["数学", "物理", "化学", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="只生成前 N 个知识点（0=不限制）")
    parser.add_argument("--dry-run", action="store_true", help="只列出待生成清单，不调用 API")
    parser.add_argument("--no-db", action="store_true", help="生成后不写入数据库（只存 JSON）")
    parser.add_argument("--export", action="store_true", help="只从数据库导出 JSON，不调用 LLM")
    args = parser.parse_args()

    # 0. 导出模式：从数据库（唯一事实来源）导出各学科完整 JSON
    if args.export:
        export_json()
        return

    # 1. 过滤种子
    seeds = SEED if args.subject == "all" else [s for s in SEED if s["subject"] == args.subject]
    if args.limit > 0:
        seeds = seeds[: args.limit]

    if args.dry_run:
        print(f"🔍 共 {len(seeds)} 个知识点待生成：")
        for s in seeds:
            print(f"  - [{s['subject']}] {s['chapter']} / {s['kp_name']}")
        return

    # 2. 查已有知识点（幂等跳过）
    from app.db import SessionLocal, KnowledgePoint
    from sqlalchemy import select

    with SessionLocal() as session:
        rows = session.execute(select(KnowledgePoint.subject, KnowledgePoint.kp_name)).all()
    existing = {(r[0], r[1]) for r in rows}

    # 3. 批量生成
    print(f"🚀 开始生成 {len(seeds)} 张知识卡片...")
    new_cards: list[dict] = []
    for i, seed in enumerate(seeds, 1):
        key = (seed["subject"], seed["kp_name"])
        if key in existing:
            print(f"  [{i}/{len(seeds)}] ⏭️ 已存在，跳过：{seed['kp_name']}")
            continue
        # ⚠️ LLM 输出不稳定，json_mode 偶发 JSON 解析失败 → 自动重试
        card = None
        for attempt in range(1, 4):  # 最多重试 3 次
            try:
                card = generate_card(seed)
                break
            except Exception as e:
                print(f"  [{i}/{len(seeds)}] ⚠️ 第 {attempt} 次失败（{str(e)[:50]}），重试...")
        if card is None:
            print(f"  [{i}/{len(seeds)}] ❌ 重试仍失败，跳过：{seed['kp_name']}")
            continue
        new_cards.append(card.model_dump())
        print(f"  [{i}/{len(seeds)}] ✅ {seed['subject']} · {seed['kp_name']}")

    if not new_cards:
        print("ℹ️ 没有新卡片（全部已存在或被跳过）。")
        print("💡 如只想重新导出 JSON：python build_knowledge_base.py --export")
        return

    # 4. 写入 SQLite + 导出 JSON
    if args.no_db:
        # --no-db：不入库，直接按本次新卡片写 JSON
        by_subject: dict[str, list[dict]] = {}
        for card in new_cards:
            by_subject.setdefault(card["subject"], []).append(card)
        out_dir = BASE_DIR / "data" / "generated"
        out_dir.mkdir(exist_ok=True)
        for subject, cards in by_subject.items():
            path = out_dir / f"{subject}_knowledge.json"
            path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n📄 已保存 {len(cards)} 张卡片 → {path}")
    else:
        inserted = insert_to_db(new_cards)
        print(f"🗄️ 已写入数据库 {inserted} 条（knowledge_points 表）")
        export_json()

    print(f"\n🎉 完成！本次新增 {len(new_cards)} 张卡片。建议打开 JSON 人工审校一遍。")


if __name__ == "__main__":
    main()
