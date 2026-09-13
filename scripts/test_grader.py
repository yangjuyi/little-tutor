"""Test grade_question with real LLM call."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.adapters.llm import generate_question, get_llm, grade_question

question_llm = get_llm("question")
grade_llm = get_llm("grade")
print("=== Step 1: generate question ===")
question = generate_question(
    mastery_level="weak",
    kp_name="配方法解一元二次方程",
    llm=question_llm,
)
print(f"stem: {question['stem']}")
print(f"answer: {question['answer']}")
print(f"params: {question['params']}")

print("\n=== Step 2: student answers (simulate) ===")
# Simulate a student who made a calculation error
student_steps = [
    {"basis": "将方程两边除以a", "result": "x² + bx/a + c/a = 0"},
    {"basis": "配方，加上(b/2a)²", "result": "(x + b/2a)² = b²/4a² - c/a"},
    {"basis": "开方求解", "result": "x=5"},  # 故意写错答案
]
print(f"student_steps: {student_steps}")

print("\n=== Step 3: grade ===")
result = grade_question(question, student_steps, grade_llm)

print(f"is_correct: {result['is_correct']}")
print(f"error_type: {result['error']['error_type']}")
print(f"confidence: {result['error']['confidence']}")
print(f"evidence: {result['error']['evidence']}")
print(f"ai_certain: {result['error']['ai_certain']}")
print(f"teacher_reviewed: {result['error']['teacher_reviewed']}")
print(f"steps_analyzed: {result['error']['steps_analyzed']}")
print(f"insufficient_evidence: {result['error']['insufficient_evidence']}")
