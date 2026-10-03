# Badcase Recording Template

Updated: 2026-10-01

Use one record per confirmed defect or quality gap. Do not create a record for
an unverified suspicion.

## Required Fields

```text
badcase_id:
first_seen:
source:
question_id:
student_id:
session_id:
input:
expected:
actual:
program_fact:
llm_attribution:
teacher_judgement:
severity:
root_cause_category:
fix:
regression_test:
status:
owner:
```

## Classification

`root_cause_category` uses one of:

```text
data_contract
program_grading
attribution_prompt
llm_runtime
graph_routing
hitl_review
persistence
ui
unknown
```

`severity` uses:

```text
P0: correctness or data integrity failure
P1: blocks a main workflow or human decision
P2: degrades quality, usability, or evidence quality
P3: cosmetic or future improvement
```

## Example

```text
badcase_id: BC-0001
first_seen: 2026-09-20
source: real LLM Eval, no_steps
question_id: q-public-01
student_id: null
session_id: null
input: 学生未提交任何步骤
expected: error_type=未归因, confidence=0, insufficient_evidence=true
actual: LLM 输出 error_type=计算，同时标记证据不足
program_fact: 最终答案错误，无法定位过程断点
llm_attribution: 计算
teacher_judgement: 教师尚未评审
severity: P2
root_cause_category: attribution_prompt
fix: 无步骤时在程序归一化层强制未归因
regression_test: tests/test_agents.py::test_no_steps_cannot_force_specific_error_type
status: fixed
owner: Codex
```
