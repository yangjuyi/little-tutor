"""Quick test: verify with_structured_output works with our LLM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.adapters.llm import generate_question, get_llm

llm = get_llm("question")
print("Model:", llm.model_name)
print("Base URL:", llm.openai_api_base)
print()

print("Calling generate_question...")
result = generate_question(
    mastery_level="weak",
    kp_name="配方法解一元二次方程",
    llm=llm,
)

print()
print("=== 出题结果 ===")
print(f"difficulty: {result['difficulty']}")
print(f"stem: {result['stem']}")
print(f"answer: {result['answer']}")
print(f"params: {result['params']}")
print(f"source: {result['source']}")
