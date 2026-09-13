"""会话级 LangGraph（§16.2，一次会话打断老师 ≤2 次）.

节点序列（2026-09-09 审计后定稿）：
    read_profile → generate_question_set（按掌握度混难度 + 挑库优先，
        缺库槽位用 Send 扇出并发生成设计题）→ H1 组卷预审(interrupt①，
        approve/swap/regroup 循环) → 单题循环×N（批改子图：程序判分 +
        AI 归因 + 逐空断点 + 事实落库，零打断）→ summarize_profile
        → H3 批量确认(interrupt②) → write_back

P2 落地项：
- Send 扇出：组卷中缺库槽位用程序化设计器并发生成（LangGraph Send），
  每任务产出一条 generated 记录（reducer 累加），check_assemble 汇合
- 子图：单题批改管线（判分→逐空断点→落库）编译为子图挂入主图，
  状态隔离、只通过共享键读写
- LLM 兜底：生成/归因异常不炸图——批改子图降级为"仅程序证据"，
  组卷失败置 llm_error 走 failed 节点，CLI/Web 据此提示重试

求助机制随 P3 Web，不进本图（§8.5/§361 已定）。
"""

import random
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt

from app.adapters.llm import get_llm, grade_question
from app.adapters.checkpoint import default_checkpointer
from app.adapters.persistence import Question as QuestionRow, SessionLocal
from app.adapters.review_store import (
    apply_to_db,
    record_answer,
    record_teacher_decision,
)
from app.adapters.session_store import (
    abort_practice_session,
    complete_practice_session,
    review_practice_session,
)
from app.application.profile_evidence import propose_mastery_change
from app.domain.adaptation import (
    evidence_weighted_rate,
    order_questions_for_target,
    select_next_target,
)
from app.domain.answer_template import first_wrong_blank, judge_blanks
from app.domain.grading import (
    pick_difficulty,
)
from app.domain.question_design import build_designed_question
from app.domain.question_edit import recompute_edited_question
from app.harness.question_assembly import (
    check_assemble_node,
    gen_candidate_node,
    generate_question_set_node,
    is_selectable_seed as _is_selectable_seed,
    parse_intent_bias,
    parse_ratio_instruction as _parse_ratio_instruction,
    persist_ai_question as _persist_ai_question,
    plan_assembly as _plan_assembly,
    route_after_check,
    seed_candidate as _seed_candidate,
)
from app.harness.state import SessionState


def read_profile_node(state: SessionState) -> dict:
    """一次会话读一次画像快照（§16.2）；无画像按 weak 起步。"""
    from app.adapters.persistence import Mastery as MasteryRow

    with SessionLocal() as s:
        row = (
            s.query(MasteryRow)
            .filter_by(
                student_id=int(state["student_id"]),
                kp_id=int(state["kp_id"]),
            )
            .first()
        )
    if row is None:
        snapshot = {
            "kp_id": state["kp_id"], "level": "weak",
            "confidence": 0.5, "evidence": "会话初始画像",
        }
    else:
        snapshot = {
            "kp_id": state["kp_id"], "level": row.level,
            "confidence": row.confidence, "evidence": row.last_status or "",
        }
    return {"profile_snapshot": snapshot}


def _select_question_from_pool(
    pool: list[dict],
    used_ids: set,
    target: str,
) -> dict | None:
    for question in order_questions_for_target(pool, target):
        if question.get("id") not in used_ids:
            return question
    return None


def _parse_h1_decision(raw) -> tuple[str, str | None]:
    if isinstance(raw, dict):
        action = str(raw.get("action") or "").strip().lower()
        if action == "edit":
            return "edit", {
                "index": int(raw.get("index") or 0),
                "stem": str(raw.get("stem") or "").strip(),
                "a": float(raw["a"]),
                "b": float(raw["b"]),
                "c": float(raw["c"]),
                "structure_tag": str(raw.get("structure_tag") or ""),
            }
        if action in ("approve", "swap", "regroup"):
            return action, str(raw.get("value") or "").strip()
    text = (raw or "").strip()
    lowered = text.lower()
    if lowered == "approve":
        return "approve", None
    if lowered.startswith("swap:"):
        return "swap", text.split(":", 1)[1].strip()
    if lowered.startswith("regroup:"):
        return "regroup", text.split(":", 1)[1].strip()
    if lowered.startswith("edit:"):
        _, index, stem = text.split(":", 2)
        return "edit", {"index": int(index), "stem": stem.strip()}
    if lowered == "regroup":
        return "regroup", None
    raise ValueError(
        f"H1 决策必须是 approve / swap:序号 / regroup:意图，实际收到：{raw!r}"
    )


def h1_review_node(state: SessionState) -> dict:
    """H1 组卷预审（interrupt①）：每次执行最多一个 interrupt，决策由条件边路由。"""
    payload = [
        {
            "index": i + 1,
            "id": q["id"],
            "difficulty": q["difficulty"],
            "stem": q["stem"],
            "answer": q["answer"],
            "params": dict(q.get("params") or {}),
        }
        for i, q in enumerate(state["candidates"])
    ]
    decision = interrupt({
        "candidates": payload,
        "actions": "approve / swap:序号 / regroup:重组意图",
        "validation_error": state.get("h1_validation_error"),
    })
    action, arg = _parse_h1_decision(decision)
    updates = {
        "h1_decision": action,
        "teacher_instruction": arg,
        "h1_validation_error": None,
    }
    if action == "edit":
        index = int(arg["index"]) - 1
        candidates = list(state["candidates"])
        if not 0 <= index < len(candidates):
            raise ValueError("修改题号超出预审池范围")
        try:
            edited = recompute_edited_question(
                candidates[index],
                stem=str(arg["stem"]),
                a=float(arg["a"]),
                b=float(arg["b"]),
                c=float(arg["c"]),
                structure_tag=str(arg.get("structure_tag") or ""),
            )
        except ValueError as exc:
            return {
                "h1_decision": "edit_error",
                "teacher_instruction": None,
                "h1_validation_error": str(exc),
            }
        candidates[index] = edited
        return {
            "h1_decision": "edit",
            "teacher_instruction": edited["stem"],
            "h1_validation_error": None,
            "candidates": candidates,
        }
    if action == "regroup":
        ratios = _parse_ratio_instruction(arg) or parse_intent_bias(arg)
        if ratios:
            updates["difficulty_ratios"] = {
                difficulty: int(round(weight * 100))
                for difficulty, weight in ratios.items()
            }
    if action == "approve":
        # AI 生成题落库换真实主键（answer_records 外键需要 int）；
        # 在图内做保证 CLI / Web 两条入口不漏步骤
        approved = list(state["candidates"])
        for q in approved:
            if not isinstance(q["id"], int):
                _persist_ai_question(q, state["kp_id"])
        updates.update({
            "approved_pool": approved,
            "phase": "answer",
        })
        if approved:
            initial_target = pick_difficulty(state["profile_snapshot"]["level"])
            initial = _select_question_from_pool(
                approved, set(), initial_target
            )
            updates.update({
                "approved_questions": [initial] if initial else [],
                "adaptive_target": (
                    initial["difficulty"] if initial else initial_target
                ),
            })
        else:
            updates.update({
                "approved_questions": [],
                "adaptive_target": None,
            })
    return updates


def route_after_h1(state: SessionState) -> str:
    return {
        "approve": END,
        "edit": "h1_review",
        "edit_error": "h1_review",
        "swap": "regen_one",
        "regroup": "regen_all",
    }[
        state["h1_decision"]
    ]


def regen_one_node(state: SessionState) -> dict:
    """换题：优先从题库换同难度未用题（秒级），库空才 AI 生成（慢路径兜底）。"""
    try:
        idx = int(str(state["teacher_instruction"])) - 1
        candidates = list(state["candidates"])
        if not 0 <= idx < len(candidates):
            raise ValueError(f"换题序号超出范围：{state['teacher_instruction']}")
        difficulty = candidates[idx]["difficulty"]
        used_ids = {
            q["id"] for q in candidates if isinstance(q["id"], int)
        }
        with SessionLocal() as s:
            pool = (
                s.query(QuestionRow)
                .filter(
                    QuestionRow.kp_id == int(state["kp_id"]),
                    QuestionRow.source.in_(["ai_generated", "private"]),
                    QuestionRow.difficulty == difficulty,
                )
                .all()
            )
        pool = [
            row for row in pool
            if row.id not in used_ids and _is_selectable_seed(row)
        ]
        if pool:
            replacement = _seed_candidate(random.choice(pool), state["kp_id"])
        else:
            # 库空兜底：程序化题目设计器（即时，不使用 LLM 猜参数）
            replacement = build_designed_question(
                difficulty,
                sequence=idx + random.randint(1000, 9999),
                kp_id=state["kp_id"],
            )
        candidates[idx] = replacement
    except Exception as exc:
        # Command 路由：节点返回 Command 时条件边不再评估，避免双重调度
        return Command(update={"llm_error": f"换题生成失败：{exc}"}, goto="failed")
    return Command(update={"candidates": candidates}, goto="h1_review")


def regen_all_node(state: SessionState) -> dict:
    """重新组：重跑组卷管线（§16.2：按老师意图重新生成整份清单，含挑库优先），
    老师意图在 teacher_instruction 留痕，回 H1 再审。"""
    try:
        plan_id = int(state.get("plan_id") or 0) + 1
        instruction = state.get("teacher_instruction")
        bias = _parse_ratio_instruction(instruction) or parse_intent_bias(instruction)
        plan, sends = _plan_assembly(state, plan_id=plan_id, bias=bias)
    except Exception as exc:
        return Command(update={"llm_error": f"重组生成失败：{exc}"}, goto="failed")
    update = {"plan": plan, "plan_id": plan_id}
    if sends:
        return Command(update=update, goto=sends)
    return Command(update=update, goto="check_assemble")


def failed_node(state: SessionState) -> dict:
    """LLM 异常汇点：状态带 llm_error，CLI/Web 据此提示重试，图正常收束。"""
    if state.get("session_id"):
        abort_practice_session(str(state["session_id"]))
    return {"phase": "done"}


# ---------- 批改子图（P2：compiled subgraph，状态隔离、共享键读写）----------

class GradeState(TypedDict):
    """子图只认这几个键；与主图 SessionState 以共享键衔接"""
    student_id: str
    session_id: Optional[str]
    current_question: dict
    template: Optional[dict]
    student_steps: list
    attempt_no: int
    assistance_level: Optional[str]
    hint_count: int
    scaffold_level: int
    result: Optional[dict]


def _grade_compute_node(state: GradeState) -> dict:
    result = grade_question(
        state["current_question"], state["student_steps"], get_llm("grade")
    )
    result["difficulty"] = state["current_question"].get("difficulty")
    result["attempt_no"] = int(state.get("attempt_no") or 1)
    result["assistance_level"] = (
        state.get("assistance_level") or "independent"
    )
    result["hint_count"] = int(state.get("hint_count") or 0)
    result["scaffold_level"] = int(state.get("scaffold_level") or 0)
    template = state.get("template")
    if template:
        blank_results = judge_blanks(template, state["student_steps"])
        result["blank_results"] = blank_results
        breakpoint = first_wrong_blank(blank_results)
        if breakpoint:
            result["error"]["program_breakpoint"] = (
                f"程序定位断点：{breakpoint['blank_id']}（{breakpoint['basis']}）"
            )
    return {"result": result}


def _record_fact_node(state: GradeState) -> dict:
    """事实当轮落库（§16.2：单题循环内写 answer_record，带 session_id）"""
    record_answer(
        state["student_id"], state["current_question"],
        state["result"], state.get("session_id"),
        attempt_no=int(state.get("attempt_no") or 1),
        hint_count=int(state.get("hint_count") or 0),
        scaffold_level=int(state.get("scaffold_level") or 0),
    )
    return {}


grade_pipeline = (
    StateGraph(GradeState)
    .add_node("grade_compute", _grade_compute_node)
    .add_node("record_fact", _record_fact_node)
    .add_edge(START, "grade_compute")
    .add_edge("grade_compute", "record_fact")
    .add_edge("record_fact", END)
    .compile()
)


def collect_round_node(state: SessionState) -> dict:
    rounds = list(state.get("round_results") or [])
    if state.get("result"):
        rounds.append(state["result"])
    selected = list(state.get("approved_questions") or [])
    pool = list(state.get("approved_pool") or selected)
    question_count = int(state.get("question_count") or len(pool))
    current_target = (
        state.get("adaptive_target")
        or (rounds[-1].get("difficulty") if rounds else None)
        or "simple"
    )
    next_target = select_next_target(current_target, rounds)
    if len(selected) < question_count:
        used_ids = {question.get("id") for question in selected}
        next_question = _select_question_from_pool(
            pool, used_ids, next_target
        )
        if next_question is not None:
            selected.append(next_question)
    # 批改子图不写父图 phase，这里把流程拨回作答阶段（供"去汇总"的守卫判断）
    return {
        "round_results": rounds,
        "approved_questions": selected,
        "adaptive_target": next_target,
        "hint_level": 0,
        "phase": "answer",
    }


def summarize_profile_node(state: SessionState) -> dict:
    """会话汇总：按 kp 聚合本轮正确率 → §16.5 批量画像建议。"""
    complete_practice_session(str(state["session_id"]))
    by_kp: dict[str, list] = {}
    for result in state.get("round_results") or []:
        by_kp.setdefault(str(result["error"]["error_kp_id"]), []).append(result)
    proposals = []
    for kp_id, results in by_kp.items():
        total = len(results)
        correct = sum(1 for r in results if r["is_correct"])
        rate = correct / total
        weighted_rate = evidence_weighted_rate(results)
        # 会话内答题已逐题落库（§16.2），这里直接读库计算，不再注入 current_rate
        proposal = propose_mastery_change(
            int(state["student_id"]),
            int(kp_id),
            current_rate=weighted_rate,
        )
        proposal.update({
            "kp_id": kp_id,
            "kp_name": state.get("kp_name") or f"知识点 {kp_id}",
            "correct_count": correct,
            "confirmed_wrong_count_delta": total - correct,
            "session_rate": round(rate, 4),
            "weighted_rate": weighted_rate,
            "round_count": total,
            "adaptive_target": state.get("adaptive_target"),
            "reason": "证据加权会话汇总",
        })
        proposals.append(proposal)
    return {"session_proposals": proposals, "phase": "summarize"}


def h3_write_back_node(state: SessionState) -> dict:
    """H3 批量确认（interrupt②）：允许老师修正等级后再 accept/reject。"""
    raw_decision = interrupt({
        "proposals": state["session_proposals"],
        "actions": "accept / reject",
    })
    corrections: dict[str, str] = {}
    if isinstance(raw_decision, dict):
        text = str(raw_decision.get("decision") or "").strip().lower()
        corrections = {
            str(key): str(value)
            for key, value in (raw_decision.get("corrections") or {}).items()
        }
    else:
        text = str(raw_decision or "").strip().lower()
    if text not in ("accept", "reject"):
        raise ValueError("H3 决策必须是 accept / reject")
    proposals = []
    for original in state["session_proposals"]:
        proposal = dict(original)
        corrected = corrections.get(str(proposal["kp_id"]))
        if corrected:
            if corrected not in ("weak", "mid", "strong"):
                raise ValueError("修正掌握度必须是 weak / mid / strong")
            proposal["suggest_level"] = corrected
            proposal["teacher_corrected"] = True
        proposals.append(proposal)
    if text == "accept":
        for proposal in proposals:
            apply_to_db(state["student_id"], proposal)
    for proposal in proposals:
        record_teacher_decision(
            state["student_id"], proposal, text,
            state.get("session_id"), None,
        )
    review_practice_session(
        str(state["session_id"]),
        "accepted" if text == "accept" else "rejected",
    )
    return {
        "session_proposals": proposals,
        "h3_decision": text,
        "phase": "done",
    }


def route_by_phase(state: SessionState) -> str:
    return {
        "grade_round": "grade_round",
        "summarize": "summarize_profile",
    }.get(state.get("phase"), "read_profile")


def build_session_graph(checkpointer=None):
    graph = StateGraph(SessionState)
    graph.add_node("read_profile", read_profile_node)
    graph.add_node("generate_question_set", generate_question_set_node)
    graph.add_node("gen_candidate", gen_candidate_node)
    graph.add_node("check_assemble", check_assemble_node)
    graph.add_node("failed", failed_node)
    graph.add_node("h1_review", h1_review_node)
    graph.add_node("regen_one", regen_one_node)
    graph.add_node("regen_all", regen_all_node)
    graph.add_node("grade_round", grade_pipeline)  # 批改子图
    graph.add_node("collect_round", collect_round_node)
    graph.add_node("summarize_profile", summarize_profile_node)
    graph.add_node("h3_write_back", h3_write_back_node)

    graph.add_conditional_edges(START, route_by_phase, {
        "read_profile": "read_profile",
        "grade_round": "grade_round",
        "summarize_profile": "summarize_profile",
    })
    graph.add_edge("read_profile", "generate_question_set")
    # generate_question_set 用 Command goto：有缺库槽位 → Send 扇出，否则直达 H1
    graph.add_edge("gen_candidate", "check_assemble")
    graph.add_conditional_edges("check_assemble", route_after_check, {
        "h1_review": "h1_review", "failed": "failed",
    })
    graph.add_edge("failed", END)
    graph.add_conditional_edges("h1_review", route_after_h1, {
        END: END,
        "h1_review": "h1_review",
        "regen_one": "regen_one",
        "regen_all": "regen_all",
    })
    graph.add_edge("grade_round", "collect_round")
    graph.add_edge("collect_round", END)
    graph.add_edge("summarize_profile", "h3_write_back")
    graph.add_edge("h3_write_back", END)
    return graph.compile(checkpointer=checkpointer or default_checkpointer())
