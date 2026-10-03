"""Acceptance for the first real-exam vertical slice in the product main chain."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    runtime = tempfile.TemporaryDirectory(prefix="little-tutor-real-exam-")
    os.environ["TUTOR_DB_PATH"] = str(Path(runtime.name) / "tutor.db")
    os.environ["TUTOR_CHECKPOINT_PATH"] = str(Path(runtime.name) / "checkpoints.db")
    os.environ["TUTOR_LOAD_SEED_CATALOG"] = "0"

    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command

    import app.adapters.persistence as db
    import app.harness.session_graph as session_graph
    from app.adapters.real_exam_bank import load_growth_main_chain_questions
    from app.application.student_practice import _build_student_steps
    from app.domain.answer_template import (
        build_template,
        supports_question_template,
    )
    from app.domain.assessment import get_question_handler

    db.init_db()
    with db.SessionLocal() as session:
        kp = db.KnowledgePoint(
            subject="数学",
            chapter="一元二次方程",
            kp_name="一元二次方程增长率",
            concept="a(1+x)^n=b",
        )
        student = db.Student(name="真实验收学生")
        session.add_all([kp, student])
        session.flush()
        records = load_growth_main_chain_questions(kp.id)
        deduped_records = {
            record["stem"]: record for record in records
        }
        for record in deduped_records.values():
            session.add(db.Question(
                kp_id=kp.id,
                stem=record["stem"],
                answer=record["answer"],
                analysis=record["analysis"],
                difficulty=record["difficulty"],
                source=record["source"],
                params=record["params"],
            ))
        session.commit()
        kp_id = kp.id
        student_id = student.id

    results = []
    with db.SessionLocal() as session:
        rows = session.query(db.Question).all()
    for row in rows:
        question = {
            "id": row.id,
            "kp_id": row.kp_id,
            "stem": row.stem,
            "answer": row.answer,
            "analysis": row.analysis,
            "difficulty": row.difficulty,
            "source": row.source,
            "params": dict(row.params or {}),
        }
        handler = get_question_handler(question["params"])

        def judge(mutate: bool) -> bool:
            if supports_question_template(question["params"]):
                template = build_template(question["params"])
                form = {}
                for blank in template["blanks"]:
                    value = (
                        str(blank["answer_index"] + 1)
                        if blank["kind"] == "choice"
                        else f"{blank['expected']:g}"
                    )
                    form[blank["id"]] = value
                if mutate:
                    final_ids = template.get("answer_blank_ids") or []
                    target_id = (
                        final_ids[0]
                        if final_ids
                        else template["blanks"][0]["id"]
                    )
                    first = next(
                        blank for blank in template["blanks"]
                        if blank["id"] == target_id
                    )
                    if first["kind"] == "choice":
                        wrong_index = (
                            int(first["answer_index"]) + 1
                        ) % len(first["options"])
                        form[first["id"]] = str(wrong_index + 1)
                    else:
                        form[first["id"]] = "999999"
                _, steps = _build_student_steps(question, form)
                return handler.check_answer(question, steps[-1]["result"])
            answer = (
                "x=1"
                if row.params.get("target") == "equation"
                else "999%"
            )
            return handler.check_answer(
                question,
                row.answer if not mutate else answer,
            )

        correct_limit = judge(False)
        wrong_rejected = not judge(True)
        results.append({
            "question_id": row.params.get("source_question_id"),
            "year": row.params.get("year"),
            "province": row.params.get("province"),
            "difficulty": row.difficulty,
            "target": row.params.get("target"),
            "program_correct_answer": correct_limit,
            "program_wrong_answer_rejected": wrong_rejected,
            "status": (
                "main_chain_verified"
                if correct_limit and wrong_rejected
                else "failed"
            ),
        })

    connection = sqlite3.connect(
        os.environ["TUTOR_CHECKPOINT_PATH"],
        check_same_thread=False,
    )
    graph = session_graph.build_session_graph(SqliteSaver(connection))

    def fake_attribution(question, steps, program_result, llm):
        return {
            "error_type": "未归因",
            "error_kp_id": str(kp_id),
            "confidence": 0.0,
            "evidence": "程序结构化真题判定",
            "evidence_source": "program",
            "ai_certain": False,
            "teacher_reviewed": False,
            "steps_analyzed": len(steps),
            "insufficient_evidence": True,
        }

    def graph_smoke(answer_mode: str, suffix: str) -> dict:
        thread_id = f"real-exam-{suffix}"
        config = {"configurable": {"thread_id": thread_id}}
        graph.invoke(
            {
                "student_id": str(student_id),
                "kp_id": str(kp_id),
                "kp_name": "一元二次方程增长率",
                "session_id": thread_id,
                "question_count": 2,
                "phase": "assemble",
            },
            config,
        )
        snapshot = graph.get_state(config)
        candidates = snapshot.tasks[0].interrupts[0].value["candidates"]
        graph.invoke(Command(resume="approve"), config)
        question = graph.get_state(config).values["approved_questions"][0]
        uses_template = supports_question_template(question["params"])
        if uses_template:
            template = build_template(question["params"])
            form = {}
            for blank in template["blanks"]:
                if blank["kind"] == "choice":
                    value = str(blank["answer_index"] + 1)
                else:
                    value = f"{blank['expected']:g}"
                form[blank["id"]] = value
            if answer_mode == "wrong":
                final_ids = template.get("answer_blank_ids") or []
                target_id = (
                    final_ids[0]
                    if final_ids
                    else template["blanks"][0]["id"]
                )
                target = next(
                    blank for blank in template["blanks"]
                    if blank["id"] == target_id
                )
                if target["kind"] == "choice":
                    choice = target
                    wrong_index = (int(choice["answer_index"]) + 1) % len(
                        choice["options"]
                    )
                    form[choice["id"]] = str(wrong_index + 1)
                else:
                    form[target["id"]] = (
                        f"{float(target['expected']) + 1:g}"
                    )
            template, steps = _build_student_steps(question, form)
        else:
            final_answer = (
                question["answer"]
                if answer_mode == "correct"
                else "x=1"
                if question["params"].get("target") == "equation"
                else "999%"
            )
            template, steps = _build_student_steps(
                question,
                {"final_answer": final_answer},
            )
        with patch.object(
            session_graph,
            "attribute_error",
            side_effect=fake_attribution,
        ):
            graph.invoke(
                {
                    "student_id": str(student_id),
                    "session_id": thread_id,
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
        return {
            "thread_id": thread_id,
            "candidate_count": len(candidates),
            "all_candidates_structured": all(
                item["params"].get("question_type")
                in ("growth_rate", "growth_application")
                for item in candidates
            ),
            "question_id": question["id"],
            "is_correct": result["is_correct"],
            "uses_template": uses_template,
            "program_breakpoint": (
                (result.get("error") or {}).get("program_breakpoint")
            ),
        }

    correct_smoke = graph_smoke("correct", "correct")
    wrong_smoke = graph_smoke("wrong", "wrong")
    connection.close()

    passed = sum(item["status"] == "main_chain_verified" for item in results)
    graph_ok = bool(
        correct_smoke["all_candidates_structured"]
        and correct_smoke["is_correct"] is True
        and wrong_smoke["all_candidates_structured"]
        and wrong_smoke["is_correct"] is False
        and (
            not wrong_smoke["uses_template"]
            or bool(wrong_smoke["program_breakpoint"])
        )
    )
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "suite": "real_exam_main_chain_acceptance",
        "capability": "growth_rate",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "sample_ready": len(results) >= 15,
        "status": (
            "verified"
            if len(results) >= 15 and passed == len(results) and graph_ok
            else "failed"
        ),
        "graph_smoke": {
            "correct": correct_smoke,
            "wrong": wrong_smoke,
            "passed": graph_ok,
        },
        "results": results,
    }
    output = (
        ROOT
        / "outputs"
        / "evals"
        / "middle_exam_main_chain_acceptance.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={output}")
    db.engine.dispose()
    runtime.cleanup()


if __name__ == "__main__":
    main()
