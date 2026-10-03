"""C 会话级图测试：组卷/H1 循环审批/单题落库/H3 批量确认（离线，临时库）"""

import itertools
import os
import sqlite3
import tempfile
import unittest
from collections import Counter
from unittest.mock import patch

from langgraph.types import Command
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db
import app.adapters.review_store as review_store
import app.adapters.session_store as session_store
import app.application.profile_evidence as profile_evidence
import app.harness.grade_pipeline as grade_pipeline
import app.harness.question_assembly as question_assembly
import app.harness.session_graph as sg
from app.domain.answer_template import build_template, supports_question_template
from app.domain.exam.main_chain import check_structured_exam_answer
from app.domain.question_design import build_designed_question as _real_build_design
from app.adapters.real_exam_bank import load_growth_main_chain_questions
from app.harness.session_graph import (
    _parse_ratio_instruction,
    build_session_graph,
    parse_intent_bias,
)


SEEDS = [
    ("simple", {"a": 1, "b": -6, "c": 8, "structure_tag": "", "design_id": "direct"}),
    ("simple", {"a": 1, "b": 2, "c": -8, "structure_tag": "", "design_id": "direct"}),
    ("mid", {"a": 2, "b": -8, "c": 6, "structure_tag": "", "design_id": "direct"}),
    ("mid", {"a": 3, "b": -12, "c": 9, "structure_tag": "", "design_id": "direct"}),
    ("hard", {"a": 2, "b": 4, "c": -30, "structure_tag": "建模", "design_id": "rectangle"}),
    ("hard", {"a": 3, "b": -18, "c": 24, "structure_tag": "根与系数", "design_id": "root_relation"}),
]

_FAKE_ID = itertools.count(1)


def seed_stem(params: dict) -> str:
    """构造与测试种子参数一致的题干，供图与 Web 测试共用。"""
    a, b, c = params["a"], params["b"], params["c"]
    design_id = params["design_id"]
    if design_id == "rectangle":
        relation = (
            f"长比宽的 {a} 倍多 {b} 米"
            if a != 1
            else f"长比宽多 {b} 米"
        )
        return (
            f"一块长方形菜地的宽为 x 米，{relation}，"
            f"面积为 {-c} 平方米。求这块菜地的宽。"
        )
    if design_id == "root_relation":
        return (
            f"已知一个一元二次方程的两个根的和为 {-b / a:g}，"
            f"积为 {c / a:g}，且二次项系数为 {a:g}。"
            "请写出这个方程并求它的两个根。"
        )
    if design_id == "consecutive_even":
        return (
            f"两个连续偶数的积是 {-c:g}。设较小的偶数为 x，"
            "列出方程并求这两个偶数。"
        )
    equation = f"{a:g}x² {b:+g}x {c:+g} = 0"
    return f"解方程 {equation}，求 x 的全部值。"


def conflicting_stem(params: dict) -> str:
    """构造参数不变但题干事实冲突的题目。"""
    design_id = params["design_id"]
    if design_id == "rectangle":
        return (
            f"一块长方形菜地的宽为 x 米，长比宽的 {params['a']:g} 倍多 "
            f"{params['b']:g} 米，面积为 {-params['c'] + 1:g} 平方米。"
            "求这块菜地的宽。"
        )
    if design_id == "root_relation":
        return (
            f"已知一个一元二次方程的两个根的和为 "
            f"{-params['b'] / params['a'] + 1:g}，"
            f"积为 {params['c'] / params['a']:g}，"
            f"且二次项系数为 {params['a']:g}。"
            "请写出这个方程并求它的两个根。"
        )
    if design_id == "consecutive_even":
        return (
            f"两个连续偶数的积是 {-params['c'] + 2:g}。"
            "设较小的偶数为 x，列出方程并求这两个偶数。"
        )
    a, b, c = params["a"], params["b"], params["c"] + 1
    return f"解方程 {a:g}x² {b:+g}x {c:+g} = 0，求 x 的全部值。"


def _fake_attribution(error_type: str = "计算"):
    return {
        "error_type": error_type,
        "confidence": 0.5,
        "evidence": "test attribution",
        "evidence_source": "llm",
        "ai_certain": False,
        "teacher_reviewed": False,
        "steps_analyzed": 1,
        "insufficient_evidence": False,
    }


class TestSessionGraph(unittest.TestCase):
    """会话级图端到端（离线）：H1 一次定稿、单题零打断、H3 一次批量确认"""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.engine = engine
        db.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self.session = Session
        self._patches = [
            patch.object(sg, "SessionLocal", Session),
            patch.object(question_assembly, "SessionLocal", Session),
            patch.object(review_store, "SessionLocal", Session),
            patch.object(profile_evidence, "SessionLocal", Session),
            patch.object(session_store, "SessionLocal", Session),
        ]
        for p in self._patches:
            p.start()

        with Session() as s:
            stu = db.Student(name="测试学生")
            kp = db.KnowledgePoint(
                subject="数学", chapter="一元二次方程",
                kp_name="配方法解一元二次方程", concept="c",
            )
            s.add_all([stu, kp])
            s.flush()
            self.questions = []
            for difficulty, params in SEEDS:
                q = db.Question(
                    kp_id=kp.id,
                    stem=seed_stem(params),
                    answer="x₁=2.0, x₂=3.0" if params["a"] == 1 else "x₁=3.0, x₂=0.5",
                    difficulty=difficulty, source="ai_generated",
                    params=params,
                )
                s.add(q)
                self.questions.append(q)
            s.commit()
            self.student_id, self.kp_id = stu.id, kp.id

        ckpt = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        ckpt.close()
        self.ckpt_path = ckpt.name
        self._connections = []

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        for conn in self._connections:
            conn.close()
        os.unlink(self.db_path)
        os.unlink(self.ckpt_path)

    def _graph(self):
        conn = sqlite3.connect(self.ckpt_path, check_same_thread=False)
        self._connections.append(conn)
        return build_session_graph(SqliteSaver(conn))

    def _assemble(self, count=4, session_id="sess-1"):
        graph = self._graph()
        config = {"configurable": {"thread_id": f"t-{next(_FAKE_ID)}"}}
        graph.invoke(
            {
                "student_id": str(self.student_id),
                "kp_id": str(self.kp_id),
                "kp_name": "配方法解一元二次方程",
                "session_id": session_id,
                "question_count": count,
                "phase": "assemble",
            },
            config,
        )
        return graph, config

    def _seed_mastery(self, level: str, confidence: float = 1.0) -> None:
        with self.session() as s:
            s.add(db.Mastery(
                student_id=self.student_id,
                kp_id=self.kp_id,
                level=level,
                confidence=confidence,
                last_status="双会话测试预置画像",
            ))
            s.commit()

    def _complete_session(
        self,
        graph,
        config,
        *,
        correct: bool,
        count: int,
        finalize: bool = True,
    ) -> None:
        graph.invoke(Command(resume="approve"), config)
        for _ in range(count):
            values = graph.get_state(config).values
            question = values["approved_questions"][-1]
            steps = [{
                "basis": "最终作答",
                "result": question["answer"] if correct else "x=999",
            }]
            with patch.object(
                grade_pipeline,
                "attribute_error",
                return_value=_fake_attribution(
                    "无错" if correct else "计算"
                ),
            ):
                graph.invoke(
                    {
                        "student_id": str(self.student_id),
                        "session_id": values["session_id"],
                        "current_question": question,
                        "template": None,
                        "student_steps": steps,
                        "attempt_no": 1,
                        "assistance_level": "independent",
                        "hint_count": 0,
                        "scaffold_level": 0,
                        "phase": "grade_round",
                    },
                    config,
                )
        graph.invoke(
            {
                "student_id": str(self.student_id),
                "session_id": graph.get_state(config).values["session_id"],
                "phase": "summarize",
            },
            config,
        )
        if finalize:
            graph.invoke(Command(resume={"decision": "accept"}), config)

    def _mastery_level(self) -> str:
        with self.session() as s:
            return (
                s.query(db.Mastery)
                .filter_by(student_id=self.student_id, kp_id=self.kp_id)
                .one()
                .level
            )

    def _correct_steps(self, params):
        template = build_template(params)
        steps = []
        for blank in template["blanks"]:
            result = (
                str(blank["answer_index"] + 1)
                if blank["kind"] == "choice"
                else f"{blank['expected']:g}"
            )
            steps.append({"basis": blank["basis"], "result": result})
        by_id = {
            blank["id"]: step["result"]
            for blank, step in zip(template["blanks"], steps)
        }
        roots = [by_id[blank_id] for blank_id in template["answer_blank_ids"]]
        builder = template.get("final_answer_builder")
        if builder == "growth_rate":
            final_answer = roots[0]
        elif builder == "choice_text":
            selected = int(roots[0]) - 1
            final_answer = template["blanks"][0]["options"][selected]
        elif builder == "growth_equation":
            final_answer = str(template["computed_final_answer"])
        else:
            final_answer = (
                f"x={roots[0]}" if len(roots) == 1
                else f"x1={roots[0]}, x2={roots[1]}"
            )
        steps.append({
            "basis": "最终作答",
            "result": final_answer,
        })
        return template, steps

    def _wrong_process_steps(self, params):
        template, steps = self._correct_steps(params)
        blank = template["blanks"][0]
        if blank["kind"] == "choice":
            selected = int(steps[0]["result"]) - 1
            steps[0]["result"] = str(
                ((selected + 1) % len(blank["options"])) + 1
            )
        else:
            steps[0]["result"] = f"{float(blank['expected']) + 1:g}"
        return template, steps

    def test_assemble_pauses_at_h1_with_candidates(self):
        graph, config = self._assemble(4)
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h1_review",))
        payload = snap.tasks[0].interrupts[0].value
        self.assertEqual(len(payload["candidates"]), 8)
        with self.session() as s:
            session = s.get(db.PracticeSessionRecord, "sess-1")
            self.assertEqual(session.status, "started")
            self.assertEqual(session.review_status, "pending")
        self.assertEqual(
            snap.values["difficulty_ratios"],
            {"simple": 60, "mid": 40, "hard": 0},
        )
        # weak 画像：难度只落在 simple/mid（hard 权重 0）
        for c in payload["candidates"]:
            self.assertIn(c["difficulty"], ("simple", "mid"))

    def test_stale_seed_answer_is_recomputed_and_persisted(self):
        params = {
            "a": 2,
            "b": 4,
            "c": -6,
            "design_id": "rectangle",
            "structure_tag": "",
        }
        with self.session() as s:
            row = db.Question(
                kp_id=self.kp_id,
                stem=seed_stem(params),
                answer="x₁=1, x₂=-3",
                analysis="旧解析",
                difficulty="mid",
                source="ai_generated",
                params=params,
            )
            s.add(row)
            s.commit()
            question_id = row.id

        with self.session() as s:
            row = s.get(db.Question, question_id)
            candidate = sg._seed_candidate(row, str(self.kp_id))
        self.assertEqual(candidate["answer"], "x=1")
        self.assertEqual(candidate["params"]["valid_roots"], [1])

        with self.session() as s:
            row = s.get(db.Question, question_id)
            self.assertEqual(row.answer, "x=1")
            self.assertEqual(row.params["valid_roots"], [1])

    def test_no_send_path_still_deduplicates_seed_stems(self):
        params = {
            "a": 2,
            "b": 4,
            "c": -6,
            "design_id": "rectangle",
            "structure_tag": "",
        }
        with self.session() as s:
            s.query(db.Question).delete()
            for index, difficulty in enumerate(
                ("simple", "simple", "mid", "mid")
            ):
                s.add(db.Question(
                    kp_id=self.kp_id,
                    stem=seed_stem(params),
                    answer="x=1",
                    analysis=f"解析 {index}",
                    difficulty=difficulty,
                    source="ai_generated",
                    params=params,
                ))
            s.commit()

        graph, config = self._assemble(2)
        candidates = graph.get_state(config).values["candidates"]
        self.assertEqual(len(candidates), 4)
        self.assertEqual(len({q["stem"] for q in candidates}), 4)

    def test_pre_review_pool_is_double_the_requested_count_and_keeps_ratio(self):
        state = {
            "student_id": str(self.student_id),
            "kp_id": str(self.kp_id),
            "kp_name": "配方法解一元二次方程",
            "session_id": "sess-ratio",
            "question_count": 10,
            "profile_snapshot": {"level": "weak", "kp_id": str(self.kp_id)},
        }
        plan, _ = sg._plan_assembly(
            state,
            plan_id=1,
            bias={"simple": 0.4, "mid": 0.4, "hard": 0.2},
        )
        counts = Counter(slot["difficulty"] for slot in plan)
        self.assertEqual(len(plan), 20)
        self.assertEqual(
            counts,
            {"simple": 8, "mid": 8, "hard": 4},
        )

    def test_confirmed_success_promotes_next_session_difficulty_mix(self):
        graph1, config1 = self._assemble(4, session_id="adaptive-a")
        state1 = graph1.get_state(config1).values
        self.assertEqual(state1["profile_snapshot"]["level"], "weak")
        self.assertEqual(
            state1["difficulty_ratios"],
            {"simple": 60, "mid": 40, "hard": 0},
        )
        weak_mix = Counter(
            candidate["difficulty"] for candidate in state1["candidates"]
        )
        self.assertEqual(weak_mix["hard"], 0)

        self._complete_session(graph1, config1, correct=True, count=4)
        self.assertEqual(self._mastery_level(), "mid")

        graph2, config2 = self._assemble(4, session_id="adaptive-b")
        state2 = graph2.get_state(config2).values
        self.assertEqual(state2["profile_snapshot"]["level"], "mid")
        self.assertEqual(
            state2["difficulty_ratios"],
            {"simple": 20, "mid": 50, "hard": 30},
        )
        mid_mix = Counter(
            candidate["difficulty"] for candidate in state2["candidates"]
        )
        self.assertGreater(mid_mix["hard"], 0)
        self.assertNotEqual(mid_mix, weak_mix)

        self._complete_session(graph2, config2, correct=True, count=4)
        self.assertEqual(self._mastery_level(), "strong")

        graph3, config3 = self._assemble(4, session_id="adaptive-c")
        state3 = graph3.get_state(config3).values
        self.assertEqual(state3["profile_snapshot"]["level"], "strong")
        self.assertEqual(
            state3["difficulty_ratios"],
            {"simple": 10, "mid": 50, "hard": 40},
        )
        strong_mix = Counter(
            candidate["difficulty"] for candidate in state3["candidates"]
        )
        self.assertGreater(strong_mix["hard"], 0)
        self.assertNotEqual(strong_mix, weak_mix)

    def test_confirmed_failure_demotes_next_session_difficulty_mix(self):
        self._seed_mastery("strong")
        graph1, config1 = self._assemble(4, session_id="adaptive-fail-a")
        state1 = graph1.get_state(config1).values
        self.assertEqual(state1["profile_snapshot"]["level"], "strong")
        strong_mix = Counter(
            candidate["difficulty"] for candidate in state1["candidates"]
        )
        self.assertGreater(strong_mix["hard"], 0)

        self._complete_session(graph1, config1, correct=False, count=4)
        self.assertEqual(self._mastery_level(), "weak")

        graph2, config2 = self._assemble(4, session_id="adaptive-fail-b")
        state2 = graph2.get_state(config2).values
        self.assertEqual(state2["profile_snapshot"]["level"], "weak")
        weak_mix = Counter(
            candidate["difficulty"] for candidate in state2["candidates"]
        )
        self.assertEqual(weak_mix["hard"], 0)
        self.assertNotEqual(weak_mix, strong_mix)

    def test_teacher_can_edit_candidate_stem_before_approval(self):
        graph, config = self._assemble(2)
        candidate = graph.get_state(config).values["candidates"][0]
        params = candidate["params"]
        edited_stem = candidate["stem"] + "（老师已校对）"
        graph.invoke(
            Command(resume={
                "action": "edit",
                "index": 1,
                "stem": edited_stem,
                "a": params["a"],
                "b": params["b"],
                "c": params["c"],
                "structure_tag": params.get("structure_tag", ""),
            }),
            config,
        )
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h1_review",))
        self.assertEqual(snap.values["candidates"][0]["stem"], edited_stem)
        graph.invoke(Command(resume="approve"), config)
        approved = graph.get_state(config).values["approved_pool"]
        self.assertIn(edited_stem, [question["stem"] for question in approved])

    def test_semantic_conflict_is_rejected_and_h1_stays_resumable(self):
        graph, config = self._assemble(2)
        candidate = graph.get_state(config).values["candidates"][0]
        params = candidate["params"]
        graph.invoke(
            Command(resume={
                "action": "edit",
                "index": 1,
                "stem": conflicting_stem(params),
                "a": params["a"],
                "b": params["b"],
                "c": params["c"],
                "structure_tag": params.get("structure_tag", ""),
            }),
            config,
        )
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h1_review",))
        payload = snap.tasks[0].interrupts[0].value
        self.assertIn("题干与参数冲突", payload["validation_error"])
        graph.invoke(Command(resume="approve"), config)
        self.assertEqual(graph.get_state(config).next, ())

    def test_invalid_h1_decision_reinterrupts_instead_of_crashing(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="maybe"), config)
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h1_review",))
        payload = snap.tasks[0].interrupts[0].value
        self.assertIn("H1 决策", payload["validation_error"])
        graph.invoke(Command(resume="approve"), config)
        self.assertEqual(graph.get_state(config).values["phase"], "answer")

    def test_unknown_routes_fall_back_to_failed(self):
        self.assertEqual(
            sg.route_after_h1({"h1_decision": "unknown"}),
            "failed",
        )
        self.assertEqual(
            sg.route_by_phase({"phase": "unknown"}),
            "failed",
        )

    def test_grade_input_guard_rejects_missing_question(self):
        result = sg._validate_grade_input_node(
            {"student_steps": [], "skip": False}
        )
        self.assertIn("current_question", result["llm_error"])

    def test_approve_finalizes_without_further_pause(self):
        graph, config = self._assemble(4)
        graph.invoke(Command(resume="approve"), config)
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ())
        values = snap.values
        self.assertEqual(values["phase"], "answer")
        self.assertEqual(len(values["approved_pool"]), 8)
        self.assertEqual(len(values["approved_questions"]), 1)

    def test_assembled_candidates_are_unique(self):
        graph, config = self._assemble(12)
        snap = graph.get_state(config)
        candidates = snap.values["candidates"]
        self.assertEqual(len(candidates), 24)
        self.assertEqual(len({q["stem"] for q in candidates}), 24)

    def test_approve_persists_ai_generated_questions_with_int_ids(self):
        """P0 回归：AI 生成题定稿时落库换真实主键，answer_records 外键不会炸"""
        graph, config = self._assemble(6)  # 6 题必有 AI 槽位（库只有 6 题）
        graph.invoke(Command(resume="approve"), config)
        snap = graph.get_state(config)
        approved = snap.values["approved_pool"]
        self.assertEqual(len(approved), 12)
        for q in approved:
            self.assertIsInstance(q["id"], int, f"AI 题未落库：{q['stem']}")
        with self.session() as s:
            # 原有 6 题 + 至少部分 AI 新增题 = 库变大
            db_count = s.query(db.Question).count()
            self.assertGreater(db_count, 6)

    def test_swap_regenerates_then_repauses_for_review(self):
        graph, config = self._assemble(4)
        before = graph.get_state(config).values["candidates"][0]["stem"]
        graph.invoke(Command(resume="swap:1"), config)
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h1_review",))  # 换题后回审
        # 换题优先题库（秒级）：新题 ≠ 旧题且仍是合法候选
        after = snap.values["candidates"][0]["stem"]
        self.assertNotEqual(before, after)
        graph.invoke(Command(resume="approve"), config)
        self.assertEqual(graph.get_state(config).next, ())

    def test_regroup_regenerates_whole_list(self):
        graph, config = self._assemble(4)
        graph.invoke(Command(resume="regroup:太难了"), config)
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h1_review",))
        for c in snap.values["candidates"]:
            self.assertTrue(c["stem"])
        graph.invoke(Command(resume="approve"), config)
        self.assertEqual(graph.get_state(config).next, ())

    def test_send_fanout_fills_missing_seed_slots(self):
        # 库里 simple/mid 各 2 题，weak 出 6 题必有 ≥2 个 AI 槽位 → Send 扇出补齐
        calls = []

        def _tracking_generate(difficulty, sequence=0, kp_id=""):
            calls.append(difficulty)
            return _real_build_design(difficulty, sequence=sequence, kp_id=kp_id)

        graph = self._graph()
        config = {"configurable": {"thread_id": f"t-{next(_FAKE_ID)}"}}
        with patch.object(
            question_assembly,
            "build_designed_question",
            side_effect=_tracking_generate,
        ):
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "kp_id": str(self.kp_id),
                    "kp_name": "配方法解一元二次方程",
                    "session_id": "sess-1",
                    "question_count": 6,
                    "phase": "assemble",
                },
                config,
            )
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h1_review",))
        candidates = snap.values["candidates"]
        self.assertEqual(len(candidates), 12)
        ai_count = sum(1 for c in candidates if isinstance(c["id"], str))
        self.assertGreaterEqual(ai_count, 2)
        self.assertGreaterEqual(len(calls), 2)

    def test_generate_failure_sets_llm_error_and_skips_h1(self):
        def _boom(*args, **kwargs):
            raise RuntimeError("api down")

        graph = self._graph()
        config = {"configurable": {"thread_id": f"t-{next(_FAKE_ID)}"}}
        with patch.object(
            question_assembly,
            "build_designed_question",
            side_effect=_boom,
        ):
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "kp_id": str(self.kp_id),
                    "kp_name": "配方法解一元二次方程",
                    "session_id": "sess-1",
                    "question_count": 6,   # 6 题必含 AI 槽位 → 触发生成失败
                    "phase": "assemble",
                },
                config,
            )
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ())            # 图正常收束，不炸进程
        self.assertIn("AI 变式生成失败", snap.values["llm_error"])
        with self.session() as s:
            self.assertEqual(
                s.get(db.PracticeSessionRecord, "sess-1").status,
                "aborted",
            )

    def test_parse_intent_bias(self):
        self.assertEqual(
            parse_intent_bias("出简单点"),
            {"simple": 0.8, "mid": 0.2, "hard": 0.0},
        )
        self.assertEqual(
            parse_intent_bias("难一点，拔高"),
            {"simple": 0.1, "mid": 0.4, "hard": 0.5},
        )
        self.assertIsNone(parse_intent_bias("随便"))
        self.assertIsNone(parse_intent_bias(None))

    def test_full_intent_gives_pure_difficulty(self):
        self.assertEqual(parse_intent_bias("全出困难题"), {"hard": 1.0})
        self.assertEqual(parse_intent_bias("只要简单题"), {"simple": 1.0})

    def test_parse_ratio_instruction(self):
        self.assertEqual(
            _parse_ratio_instruction("70/20/10"),
            {"simple": 0.7, "mid": 0.2, "hard": 0.1},
        )
        self.assertIsNone(_parse_ratio_instruction("出简单点"))
        self.assertIsNone(_parse_ratio_instruction("50/60/10"))  # 和不为 100

    def test_regroup_applies_simple_intent(self):
        # mid 掌握度基础矩阵含 30% hard；"简单"意图下 hard 必须为 0
        with self.session() as s:
            s.add(db.Mastery(
                student_id=self.student_id, kp_id=self.kp_id,
                level="mid", confidence=0.6,
            ))
            s.commit()
        graph, config = self._assemble(4)
        graph.invoke(Command(resume="regroup:出简单点"), config)
        snap = graph.get_state(config)
        difficulties = {c["difficulty"] for c in snap.values["candidates"]}
        self.assertNotIn("hard", difficulties)

    def test_regroup_all_hard(self):
        with self.session() as s:
            s.add(db.Mastery(
                student_id=self.student_id, kp_id=self.kp_id,
                level="weak", confidence=0.5,
            ))
            s.commit()
        graph, config = self._assemble(4)
        graph.invoke(Command(resume="regroup:全出困难题"), config)
        snap = graph.get_state(config)
        difficulties = {c["difficulty"] for c in snap.values["candidates"]}
        self.assertEqual(difficulties, {"hard"})

    def test_regroup_explicit_ratios(self):
        # 全出困难题证明覆盖语义后，显式比例走同一条通道
        graph, config = self._assemble(4)
        graph.invoke(Command(resume="regroup:100/0/0"), config)
        snap = graph.get_state(config)
        difficulties = {c["difficulty"] for c in snap.values["candidates"]}
        self.assertEqual(difficulties, {"simple"})
        self.assertEqual(
            snap.values["difficulty_ratios"],
            {"simple": 100, "mid": 0, "hard": 0},
        )

    def test_grade_round_accumulates_and_persists_fact(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._correct_steps(question["params"])
        with patch.object(grade_pipeline, "attribute_error", return_value=_fake_attribution()):
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "session_id": "sess-1",
                    "current_question": question,
                    "template": template,
                    "student_steps": steps,
                    "phase": "grade_round",
                },
                config,
            )
        values = graph.get_state(config).values
        self.assertEqual(len(values["round_results"]), 1)
        self.assertEqual(len(values["round_results"][0]["blank_results"]), 6)
        with self.session() as s:
            rec = s.query(db.AnswerRecord).one()
            self.assertEqual(rec.session_id, "sess-1")
            self.assertTrue(rec.is_correct)
            self.assertEqual(rec.attempt_no, 1)
            self.assertTrue(rec.first_attempt_correct)
            self.assertEqual(rec.hint_count, 0)
            self.assertEqual(rec.scaffold_level, 0)
            self.assertEqual(rec.assistance_level, "independent")

    def test_grade_round_skips_llm_when_program_facts_are_clean(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._correct_steps(question["params"])
        with patch.object(
            grade_pipeline,
            "get_llm",
            side_effect=AssertionError("clean grading must not call LLM"),
        ):
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "session_id": "sess-1",
                    "current_question": question,
                    "template": template,
                    "student_steps": steps,
                    "phase": "grade_round",
                },
                config,
            )
        result = graph.get_state(config).values["result"]
        self.assertTrue(result["is_correct"])
        self.assertEqual(result["error"]["evidence_source"], "program")

    def test_attribution_failure_degrades_without_breaking_grade_round(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._wrong_process_steps(question["params"])
        with patch.object(
            grade_pipeline,
            "attribute_error",
            side_effect=RuntimeError("api down"),
        ):
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "session_id": "sess-1",
                    "current_question": question,
                    "template": template,
                    "student_steps": steps,
                    "phase": "grade_round",
                },
                config,
            )
        result = graph.get_state(config).values["result"]
        self.assertFalse(result["is_correct"])
        self.assertFalse(result["process_correct"])
        self.assertEqual(result["error"]["evidence_source"], "program")
        with self.session() as s:
            self.assertEqual(s.query(db.AnswerRecord).count(), 1)

    def test_adaptive_collection_reorders_only_approved_remaining_questions(self):
        questions = [
            {"id": 1, "difficulty": "simple", "stem": "s"},
            {"id": 2, "difficulty": "mid", "stem": "m"},
            {"id": 3, "difficulty": "simple", "stem": "s2"},
            {"id": 4, "difficulty": "hard", "stem": "h2"},
        ]
        state = {
            "approved_questions": questions[:2],
            "approved_pool": questions,
            "question_count": 4,
            "adaptive_target": "mid",
            "round_results": [{
                "is_correct": True,
                "difficulty": "simple",
                "assistance_level": "independent",
            }],
            "result": {
                "is_correct": True,
                "difficulty": "mid",
                "assistance_level": "independent",
            },
        }
        update = sg.collect_round_node(state)
        self.assertEqual(update["adaptive_target"], "hard")
        self.assertEqual(
            [question["difficulty"] for question in update["approved_questions"]],
            ["simple", "mid", "hard"],
        )
        self.assertEqual(
            {question["id"] for question in update["approved_questions"]},
            {1, 2, 4},
        )

    def test_h3_reject_keeps_mastery_clean_but_records_decision(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        approved = graph.get_state(config).values["approved_questions"]
        question = approved[0]
        template, steps = self._correct_steps(question["params"])
        with patch.object(grade_pipeline, "attribute_error", return_value=_fake_attribution()):
            graph.invoke(
                {"student_id": str(self.student_id), "session_id": "sess-1",
                 "current_question": question, "template": template,
                 "student_steps": steps, "phase": "grade_round"},
                config,
            )
        graph.invoke(
            {"student_id": str(self.student_id), "session_id": "sess-1",
             "phase": "summarize"},
            config,
        )
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h3_write_back",))
        payload = snap.tasks[0].interrupts[0].value
        self.assertEqual(payload["proposals"][0]["session_rate"], 1.0)
        self.assertEqual(payload["proposals"][0]["correct_count"], 1)
        self.assertEqual(
            payload["proposals"][0]["kp_name"], "配方法解一元二次方程",
        )
        self.assertEqual(payload["proposals"][0]["suggest_level"], "mid")
        graph.invoke(Command(resume="reject"), config)
        values = graph.get_state(config).values
        self.assertEqual(values["h3_decision"], "reject")
        with self.session() as s:
            self.assertEqual(s.query(db.Mastery).count(), 0)
            td = s.query(db.TeacherDecision).one()
            self.assertEqual(td.decision, "reject")
            self.assertIsNone(td.question_id)
            session = s.get(db.PracticeSessionRecord, "sess-1")
            self.assertEqual(session.status, "completed")
            self.assertEqual(session.review_status, "rejected")

    def test_invalid_h3_decision_reinterrupts_instead_of_crashing(self):
        graph, config = self._assemble(1)
        self._complete_session(
            graph,
            config,
            correct=True,
            count=1,
            finalize=False,
        )
        graph.invoke(Command(resume={"decision": "maybe"}), config)
        snap = graph.get_state(config)
        self.assertEqual(snap.next, ("h3_write_back",))
        payload = snap.tasks[0].interrupts[0].value
        self.assertIn("H3 决策", payload["validation_error"])
        graph.invoke(Command(resume={"decision": "accept"}), config)
        self.assertEqual(graph.get_state(config).values["phase"], "done")

    def test_h3_accept_writes_mastery_once(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        approved = graph.get_state(config).values["approved_questions"]
        for question in approved:
            template, steps = self._correct_steps(question["params"])
            with patch.object(grade_pipeline, "attribute_error", return_value=_fake_attribution()):
                graph.invoke(
                    {"student_id": str(self.student_id), "session_id": "sess-1",
                     "current_question": question, "template": template,
                     "student_steps": steps, "phase": "grade_round"},
                    config,
                )
        graph.invoke(
            {"student_id": str(self.student_id), "session_id": "sess-1",
             "phase": "summarize"},
            config,
        )
        graph.invoke(Command(resume="accept"), config)
        with self.session() as s:
            m = s.query(db.Mastery).filter_by(
                student_id=self.student_id, kp_id=self.kp_id
            ).one()
            self.assertEqual(m.level, "mid")   # 单会话全对：mid（strong 需连续两会话）
            self.assertEqual(m.confirmed_wrong_count, 0)
            self.assertEqual(s.query(db.TeacherDecision).count(), 1)
            session = s.get(db.PracticeSessionRecord, "sess-1")
            self.assertEqual(session.status, "completed")
            self.assertEqual(session.review_status, "accepted")

    def test_h3_accept_applies_teacher_corrected_level(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._correct_steps(question["params"])
        with patch.object(grade_pipeline, "attribute_error", return_value=_fake_attribution()):
            graph.invoke(
                {"student_id": str(self.student_id), "session_id": "sess-1",
                 "current_question": question, "template": template,
                 "student_steps": steps, "phase": "grade_round"},
                config,
            )
        graph.invoke(
            {"student_id": str(self.student_id), "session_id": "sess-1",
             "phase": "summarize"},
            config,
        )
        graph.invoke(
            Command(resume={
                "decision": "accept",
                "corrections": {str(self.kp_id): "strong"},
            }),
            config,
        )
        with self.session() as s:
            mastery = s.query(db.Mastery).one()
            decision = s.query(db.TeacherDecision).one()
            self.assertEqual(mastery.level, "strong")
            self.assertEqual(decision.proposal["suggest_level"], "strong")
            self.assertTrue(decision.proposal["teacher_corrected"])

    def test_h3_teacher_corrects_error_type_and_records_decision(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._wrong_process_steps(question["params"])
        with patch.object(
            grade_pipeline, "attribute_error", return_value=_fake_attribution()
        ):
            graph.invoke(
                {"student_id": str(self.student_id), "session_id": "sess-1",
                 "current_question": question, "template": template,
                 "student_steps": steps, "phase": "grade_round"},
                config,
            )
        graph.invoke(
            {"student_id": str(self.student_id), "session_id": "sess-1",
             "phase": "summarize"},
            config,
        )
        graph.invoke(
            Command(resume={
                "decision": "accept",
                "error_corrections": {"0": "漏根"},
            }),
            config,
        )
        values = graph.get_state(config).values
        self.assertEqual(values["round_results"][0]["error"]["error_type"], "漏根")
        self.assertTrue(values["round_results"][0]["error"]["teacher_corrected"])
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertEqual(answer.error_type, "漏根")
            decisions = (
                s.query(db.TeacherDecision)
                .order_by(db.TeacherDecision.id)
                .all()
            )
            self.assertEqual(len(decisions), 2)
            correction = next(
                decision for decision in decisions
                if decision.decision == "edit"
            )
            self.assertEqual(correction.decision, "edit")
            self.assertEqual(correction.question_id, int(question["id"]))
            self.assertEqual(
                correction.proposal["error_type_before"], "计算"
            )
            self.assertEqual(
                correction.proposal["error_type_after"], "漏根"
            )

    def test_h3_test_session_skips_mastery_and_marks_data_source(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._correct_steps(question["params"])
        with patch.object(
            grade_pipeline, "attribute_error", return_value=_fake_attribution()
        ):
            graph.invoke(
                {"student_id": str(self.student_id), "session_id": "sess-1",
                 "current_question": question, "template": template,
                 "student_steps": steps, "phase": "grade_round"},
                config,
            )
        graph.invoke(
            {"student_id": str(self.student_id), "session_id": "sess-1",
             "phase": "summarize"},
            config,
        )
        graph.invoke(
            Command(resume={"decision": "accept", "test_mode": True}),
            config,
        )
        values = graph.get_state(config).values
        self.assertTrue(values["test_session"])
        with self.session() as s:
            self.assertEqual(s.query(db.Mastery).count(), 0)
            session = s.get(db.PracticeSessionRecord, "sess-1")
            self.assertEqual(session.data_source, "test")
            self.assertEqual(session.review_status, "accepted")
            decision = s.query(db.TeacherDecision).one()
            self.assertEqual(decision.note, "测试会话")

    def test_teacher_can_override_program_result_before_mastery(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._wrong_process_steps(question["params"])
        with patch.object(
            grade_pipeline, "attribute_error", return_value=_fake_attribution()
        ):
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "session_id": "sess-1",
                    "current_question": question,
                    "template": template,
                    "student_steps": steps,
                    "phase": "grade_round",
                },
                config,
            )
        graph.invoke(
            {
                "student_id": str(self.student_id),
                "session_id": "sess-1",
                "phase": "summarize",
            },
            config,
        )
        graph.invoke(
            Command(resume={
                "decision": "accept",
                "result_corrections": {"0": "correct"},
            }),
            config,
        )
        values = graph.get_state(config).values
        self.assertFalse(values["round_results"][0]["is_correct"])
        self.assertTrue(values["round_results"][0]["effective_is_correct"])
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertFalse(answer.is_correct)
            self.assertTrue(answer.teacher_is_correct)
            self.assertEqual(answer.evidence_weight, 1.0)
            mastery = s.query(db.Mastery).one()
            self.assertIn(mastery.level, ("mid", "strong"))
            override = (
                s.query(db.TeacherDecision)
                .filter_by(decision="override")
                .one()
            )
            self.assertFalse(override.proposal["program_is_correct"])
            self.assertTrue(override.proposal["teacher_is_correct"])

    def test_teacher_can_confirm_subquestion_result(self):
        graph, config = self._assemble(2)
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        template, steps = self._wrong_process_steps(question["params"])
        with patch.object(
            grade_pipeline, "attribute_error", return_value=_fake_attribution()
        ):
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "session_id": "sess-1",
                    "current_question": question,
                    "template": template,
                    "student_steps": steps,
                    "phase": "grade_round",
                },
                config,
            )
        result = dict(graph.get_state(config).values["round_results"][0])
        result["subquestion_results"] = [{
            "id": "1",
            "prompt": "求增长率",
            "is_correct": False,
            "teacher_is_correct": None,
            "effective_is_correct": False,
            "parts": [],
        }, {
            "id": "2",
            "prompt": "求后续值",
            "is_correct": True,
            "teacher_is_correct": None,
            "effective_is_correct": True,
            "parts": [],
        }]
        graph.update_state(config, {"round_results": [result]})
        graph.invoke(
            {
                "student_id": str(self.student_id),
                "session_id": "sess-1",
                "phase": "summarize",
            },
            config,
        )
        graph.invoke(
            Command(resume={
                "decision": "accept",
                "subquestion_corrections": {"0:1": "correct"},
            }),
            config,
        )
        values = graph.get_state(config).values
        self.assertTrue(values["round_results"][0]["effective_is_correct"])
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertTrue(answer.teacher_is_correct)
            self.assertEqual(
                answer.subquestion_results[0]["effective_is_correct"],
                True,
            )

    def test_structured_growth_questions_run_through_h1_and_grading(self):
        with self.session() as s:
            kp = db.KnowledgePoint(
                subject="数学",
                chapter="一元二次方程",
                kp_name="一元二次方程增长率",
                concept="a(1+x)^n=b",
            )
            s.add(kp)
            s.flush()
            for record in load_growth_main_chain_questions(kp.id):
                if record["params"]["question_type"] != "growth_rate":
                    continue
                s.add(db.Question(
                    kp_id=kp.id,
                    stem=record["stem"],
                    answer=record["answer"],
                    analysis=record["analysis"],
                    difficulty=record["difficulty"],
                    source=record["source"],
                    params=record["params"],
                ))
            s.commit()
            growth_kp_id = kp.id

        graph = self._graph()
        config = {"configurable": {"thread_id": f"t-{next(_FAKE_ID)}"}}
        graph.invoke(
            {
                "student_id": str(self.student_id),
                "kp_id": str(growth_kp_id),
                "kp_name": "一元二次方程增长率",
                "session_id": "sess-growth",
                "question_count": 2,
                "phase": "assemble",
            },
            config,
        )
        snap = graph.get_state(config)
        payload = snap.tasks[0].interrupts[0].value
        self.assertEqual(len(payload["candidates"]), 4)
        self.assertTrue(all(
            item["params"]["question_type"] == "growth_rate"
            for item in payload["candidates"]
        ))

        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        self.assertTrue(check_structured_exam_answer(question, question["answer"]))
        self.assertFalse(check_structured_exam_answer(question, "x=1"))
        if supports_question_template(question["params"]):
            template, steps = self._correct_steps(question["params"])
        else:
            template = None
            steps = [
                {"basis": "最终作答", "result": question["answer"]}
            ]

        graph.invoke(
            {
                "student_id": str(self.student_id),
                "session_id": "sess-growth",
                "current_question": question,
                "template": template,
                "student_steps": steps,
                "attempt_no": 1,
                "assistance_level": "independent",
                "hint_count": 0,
                "scaffold_level": 0,
                "phase": "grade_round",
            },
            config,
        )
        result = graph.get_state(config).values["result"]
        self.assertTrue(result["is_correct"])
        self.assertTrue(result["final_answer_correct"])


if __name__ == "__main__":
    unittest.main()
