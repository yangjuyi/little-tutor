"""会话级 LangGraph（§16.2，一次会话打断老师 ≤2 次）.

节点序列（2026-09-09 审计后定稿）：
    read_profile → generate_question_set（按掌握度混难度 + 挑库优先，
        缺库槽位用 Send 扇出并发生成设计题）→ H1 组卷预审(interrupt①，
        approve/swap/regroup 循环) → 单题循环×N（批改子图：程序事实 →
        LLM 归因建议 → 合并 → 事实落库，零打断）→ summarize_profile
        → H3 批量确认(interrupt②) → write_back

P2 落地项：
- Send 扇出：组卷中缺库槽位用程序化设计器并发生成（LangGraph Send），
  每任务产出一条 generated 记录（reducer 累加），check_assemble 汇合
- 子图：单题批改管线（程序判分→归因建议→合并→落库）编译为子图挂入主图，
  状态隔离、只通过共享键读写
- LLM 兜底：生成/归因异常不炸图——批改子图降级为"仅程序证据"，
  组卷失败置 llm_error 走 failed 节点，CLI/Web 据此提示重试

求助机制随 P3 Web，不进本图（§8.5/§361 已定）。
"""

import random

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt

from app.adapters.checkpoint import default_checkpointer
from app.adapters.persistence import (
    AnswerRecord,
    Question as QuestionRow,
    SessionLocal,
)
from app.adapters.review_store import (
    persist_teacher_review_bundle,
)
from app.adapters.session_store import (
    abort_practice_session,
    complete_practice_session,
)
from app.application.profile_evidence import propose_mastery_change
from app.domain.adaptation import (
    evidence_weighted_rate,
    order_questions_for_target,
    select_next_target,
)
from app.domain.assessment.subquestions import combine_subquestion_results
from app.domain.grading import (
    difficulty_ratios_percent,
    pick_difficulty,
)
from app.domain.teaching_plan import (
    build_teaching_plan,
    build_training_focus,
    rank_questions_for_focus,
)
from app.domain.question_design import build_designed_question
from app.domain.question_edit import recompute_edited_question
from app.domain.types import ERROR_TYPE_OPTIONS
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
from app.harness.grade_pipeline import (
    _validate_grade_input_node,
    grade_pipeline,
)


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
    training_focus = None
    with SessionLocal() as s:
        latest_error = (
            s.query(AnswerRecord.error_type, QuestionRow.params)
            .join(QuestionRow, QuestionRow.id == AnswerRecord.question_id)
            .filter(
                AnswerRecord.student_id == int(state["student_id"]),
                QuestionRow.kp_id == int(state["kp_id"]),
            )
            .order_by(AnswerRecord.created_at.desc())
            .first()
        )
    if latest_error is not None:
        training_focus = build_training_focus(
            latest_error[0],
            (latest_error[1] or {}).get("design_id"),
        )
    return {
        "profile_snapshot": snapshot,
        "difficulty_ratios": difficulty_ratios_percent(
            snapshot["level"]
        ),
        "training_focus": training_focus,
        "focus_remaining": 2 if training_focus else 0,
        "teaching_plan": build_teaching_plan(training_focus),
    }


def _select_question_from_pool(
    pool: list[dict],
    used_ids: set,
    target: str,
    focus: dict | None = None,
) -> dict | None:
    candidates = order_questions_for_target(pool, target)
    candidates = rank_questions_for_focus(candidates, focus)
    for question in candidates:
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
        "training_focus": state.get("training_focus"),
        "teaching_plan": state.get("teaching_plan"),
    })
    try:
        action, arg = _parse_h1_decision(decision)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "h1_decision": "edit_error",
            "teacher_instruction": None,
            "h1_validation_error": str(exc),
        }
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
        teaching_plan = dict(state.get("teaching_plan") or {})
        if teaching_plan:
            teaching_plan["teacher_review_status"] = "accepted"
            updates["teaching_plan"] = teaching_plan
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
    }.get(state.get("h1_decision"), "failed")


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
    last_result = state.get("result") or {}
    last_error = last_result.get("error") or {}
    new_focus = build_training_focus(
        last_error.get("error_type"),
        (state.get("current_question") or {}).get("params", {}).get("design_id"),
    )
    previous_focus = state.get("training_focus")
    previous_remaining = int(state.get("focus_remaining") or 0)
    if new_focus:
        training_focus = new_focus
        focus_remaining = 2
    elif previous_focus and previous_remaining > 1:
        training_focus = previous_focus
        focus_remaining = previous_remaining - 1
    else:
        training_focus = None
        focus_remaining = 0
    next_target = select_next_target(current_target, rounds)
    if len(selected) < question_count:
        used_ids = {question.get("id") for question in selected}
        next_question = _select_question_from_pool(
            pool, used_ids, next_target, training_focus
        )
        if next_question is not None:
            selected.append(next_question)
    # 批改子图不写父图 phase，这里把流程拨回作答阶段（供"去汇总"的守卫判断）
    return {
        "round_results": rounds,
        "approved_questions": selected,
        "adaptive_target": next_target,
        "training_focus": training_focus,
        "focus_remaining": focus_remaining,
        "teaching_plan": build_teaching_plan(training_focus),
        "hint_level": 0,
        "scaffold_level": 0,
        "skip": False,
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
    """H3 批量确认：老师可修正对错、等级、错因和测试标记。"""
    raw_decision = interrupt({
        "proposals": state["session_proposals"],
        "validation_error": state.get("h3_validation_error"),
        "actions": (
            "accept / reject / override result / correct error type / "
            "mark test session"
        ),
    })
    corrections: dict[str, str] = {}
    error_corrections: dict[str, str] = {}
    result_corrections: dict[str, str] = {}
    subquestion_corrections: dict[str, str] = {}
    test_mode = False
    if isinstance(raw_decision, dict):
        text = str(raw_decision.get("decision") or "").strip().lower()
        corrections = {
            str(key): str(value)
            for key, value in (raw_decision.get("corrections") or {}).items()
        }
        error_corrections = {
            str(key): str(value)
            for key, value in (raw_decision.get("error_corrections") or {}).items()
        }
        result_corrections = {
            str(key): str(value)
            for key, value in (raw_decision.get("result_corrections") or {}).items()
        }
        subquestion_corrections = {
            str(key): str(value)
            for key, value in (
                raw_decision.get("subquestion_corrections") or {}
            ).items()
        }
        test_mode = bool(raw_decision.get("test_mode"))
    else:
        text = str(raw_decision or "").strip().lower()
    if text not in ("accept", "reject"):
        return Command(
            update={
                "h3_validation_error": "H3 决策必须是 accept / reject",
            },
            goto="h3_write_back",
        )

    round_results = [
        dict(result) for result in (state.get("round_results") or [])
    ]
    questions = state.get("approved_questions") or []
    overrides: list[dict] = []
    error_edits: list[dict] = []
    for idx, result in enumerate(round_results):
        subquestion_results = [
            dict(item)
            for item in (result.get("subquestion_results") or [])
        ]
        subquestion_changed = False
        for subquestion in subquestion_results:
            key = f"{idx}:{subquestion['id']}"
            correction = subquestion_corrections.get(key)
            if not correction:
                continue
            if correction not in ("keep", "correct", "wrong"):
                return Command(
                    update={
                        "h3_validation_error": (
                            f"修正子问题结果非法：{correction}"
                        ),
                    },
                    goto="h3_write_back",
                )
            if correction == "keep":
                subquestion["teacher_is_correct"] = None
                subquestion["effective_is_correct"] = bool(
                    subquestion.get("is_correct")
                )
            else:
                effective = correction == "correct"
                subquestion["teacher_is_correct"] = effective
                subquestion["effective_is_correct"] = effective
            subquestion_changed = True
        if subquestion_results:
            result["subquestion_results"] = subquestion_results

        result_correction = result_corrections.get(str(idx))
        if result_correction and result_correction not in (
            "keep", "correct", "wrong",
        ):
            return Command(
                update={
                    "h3_validation_error": (
                        f"修正对错非法：{result_correction}"
                    ),
                },
                goto="h3_write_back",
            )
        effective_is_correct = (
            combine_subquestion_results(subquestion_results)
            if subquestion_results
            else bool(result.get("is_correct"))
        )
        if result_correction == "correct":
            effective_is_correct = True
        elif result_correction == "wrong":
            effective_is_correct = False
        result["effective_is_correct"] = effective_is_correct
        result["teacher_is_correct"] = (
            effective_is_correct
            if result_correction in ("correct", "wrong")
            else None
        )
        if result_correction in ("correct", "wrong") or subquestion_changed:
            question = questions[idx] if idx < len(questions) else {}
            overrides.append({
                "question_id": str(question.get("id")),
                "kp_id": str(question.get("kp_id")),
                "after": effective_is_correct,
                "subquestion_results": subquestion_results or None,
            })
        if subquestion_changed:
            error = dict(result.get("error") or {})
            if effective_is_correct:
                error.update({
                    "error_type": "无错",
                    "confidence": 1.0,
                    "evidence": "老师确认各子问题最终结果正确",
                    "teacher_reviewed": True,
                    "teacher_corrected": True,
                    "insufficient_evidence": False,
                })
            elif error.get("error_type") == "无错":
                error.update({
                    "error_type": "未归因",
                    "confidence": 0.0,
                    "evidence": "老师确认存在错误子问题，具体错因待补充",
                    "teacher_reviewed": True,
                    "teacher_corrected": True,
                    "insufficient_evidence": True,
                })
            result["error"] = error
        if result_correction in ("correct", "wrong"):
            error = dict(result.get("error") or {})
            if effective_is_correct:
                error.update({
                    "error_type": "无错",
                    "confidence": 1.0,
                    "evidence": "老师确认本题最终结果正确",
                    "teacher_reviewed": True,
                    "teacher_corrected": True,
                    "insufficient_evidence": False,
                })
            elif error.get("error_type") == "无错":
                error.update({
                    "error_type": "未归因",
                    "confidence": 0.0,
                    "evidence": "老师确认本题最终结果错误，具体错因待补充",
                    "teacher_reviewed": True,
                    "teacher_corrected": True,
                    "insufficient_evidence": True,
                })
            result["error"] = error

        if effective_is_correct:
            continue
        corrected = error_corrections.get(str(idx))
        if not corrected:
            continue
        if corrected not in ERROR_TYPE_OPTIONS:
            return Command(
                update={
                    "h3_validation_error": (
                        f"修正错因非法：{corrected}"
                    ),
                },
                goto="h3_write_back",
            )
        error = dict(result.get("error") or {})
        before = error.get("error_type")
        if corrected == before:
            continue
        error["error_type"] = corrected
        error["teacher_corrected"] = True
        error["teacher_reviewed"] = True
        result["error"] = error
        question = questions[idx] if idx < len(questions) else {}
        error_edits.append({
            "question_id": str(question.get("id")),
            "kp_id": str(question.get("kp_id")),
            "before": str(before) if before is not None else None,
            "after": corrected,
        })

    weighted_rate = evidence_weighted_rate(round_results)
    proposals = []
    by_kp: dict[str, list] = {}
    for result in round_results:
        by_kp.setdefault(str(result["error"]["error_kp_id"]), []).append(result)
    for kp_id, results in by_kp.items():
        total = len(results)
        correct = sum(
            1 for result in results
            if result.get("effective_is_correct", result.get("is_correct"))
        )
        rate = correct / total if total else 0.0
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
            "reason": "老师确认后的有效作答结果",
        })
        proposals.append(proposal)

    for proposal in proposals:
        corrected = corrections.get(str(proposal["kp_id"]))
        if corrected:
            if corrected not in ("weak", "mid", "strong"):
                return Command(
                    update={
                        "h3_validation_error": (
                            "修正掌握度必须是 weak / mid / strong"
                        ),
                    },
                    goto="h3_write_back",
                )
            proposal["suggest_level"] = corrected
            proposal["teacher_corrected"] = True

    persist_teacher_review_bundle(
        state["student_id"],
        proposals,
        text,
        state.get("session_id"),
        overrides=overrides,
        error_edits=error_edits,
        note="测试会话" if test_mode else None,
        apply_mastery=not test_mode,
        test_mode=test_mode,
        review_decision="accepted" if text == "accept" else "rejected",
    )
    return {
        "session_proposals": proposals,
        "h3_decision": text,
        "h3_validation_error": None,
        "test_session": test_mode,
        "round_results": round_results,
        "phase": "done",
    }


def route_by_phase(state: SessionState) -> str:
    phase = state.get("phase")
    if phase == "grade_round":
        return "grade_round"
    if phase == "summarize":
        return "summarize_profile"
    if phase == "assemble":
        return "read_profile"
    return "failed"


def route_after_grade_round(state: SessionState) -> str:
    return "failed" if state.get("llm_error") else "collect_round"


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
        "failed": "failed",
    })
    graph.add_conditional_edges("grade_round", route_after_grade_round, {
        "collect_round": "collect_round",
        "failed": "failed",
    })
    graph.add_edge("collect_round", END)
    graph.add_edge("summarize_profile", "h3_write_back")
    graph.add_edge("h3_write_back", END)
    return graph.compile(checkpointer=checkpointer or default_checkpointer())
