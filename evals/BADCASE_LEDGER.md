# little-tutor Badcase Ledger

Updated: 2026-10-03

Only confirmed defects and reproducible quality gaps are recorded here.

## BC-0001

```text
badcase_id: BC-0001
first_seen: 2026-10-03
source: evidence collection web flow
question_id: null
student_id: null
session_id: synthetic-session-a
input: 新会话仍停在 H1 预审时触发 /summarize
expected: 拒绝汇总并跳回当前阶段页面
actual: /waiting-confirmation 返回 500，KeyError: 'proposals'
program_fact: 会话仍在 h1_review，checkpoint 没有丢失
llm_attribution: 与 LLM 无关
teacher_judgement: 不涉及
severity: P1
root_cause_category: graph_routing
fix: trigger_summary 增加阶段、剩余题量和 interrupt 类型校验；
     load_summary 对非 H3 payload 返回受控跳转
regression_test: tests/test_web.py::TestWebFlow::
                 test_summarize_before_h1_redirects_without_server_error
status: fixed
maintainer: solo-project-maintainer
```

### Verification

- Focused regression tests passed.
- Full suite: `287/287` passed in `152.743s`.
- Live verification: `/waiting-confirmation` with the affected session cookie
  returned `303 Location: /waiting`.
- The existing checkpoint was preserved and can continue after H1 approval.

## BC-0002

```text
badcase_id: BC-0002
first_seen: 2026-10-03
source: evidence collection web flow
question_id: null
student_id: local-test-student
session_id: synthetic-session-a
input: 老师已定稿，但学生关闭原标签页后无法重新进入该会话
expected: 学生可按 session_id 恢复原会话并回到当前答题位置
actual: 学生首页只能新开练习，没有恢复已有会话入口
program_fact: 会话仍在 answer 阶段，0/1 题，checkpoint 完整
llm_attribution: 与 LLM 无关
teacher_judgement: 不涉及
severity: P1
root_cause_category: ui
fix: 新增 /resume?session_id=...；同步 thread_id/student_id cookie；
     老师工作台增加“学生端继续”入口；学生首页按 student_id 自动识别
     未完成会话，不向普通用户暴露 session_id
regression_test: tests/test_web.py::TestWebFlow::
                 test_resume_session_restores_student_answer_page
status: fixed
maintainer: solo-project-maintainer
```

### Verification

- `/resume?session_id=synthetic-session-a` returns `303 Location: /answer/0`.
- Full suite: `289/289` passed in `153.977s`.

## BC-0003

```text
badcase_id: BC-0003
first_seen: 2026-10-03
source: evidence collection answer flow
question_id: 57
student_id: local-test-student
session_id: synthetic-session-a
input: 学生完成第 1 题并提交
expected: 批改结果落库后继续进入下一题
actual: collect_round 选择下一题时抛出 500
program_fact: AnswerRecord 已保存，程序判分事实完整
llm_attribution: 当前题型走了程序兜底，与 LLM 无关
teacher_judgement: 尚未审核
severity: P1
root_cause_category: graph_routing
root_cause: rank_questions_for_focus 中 source_design_id 为空时
            `source_design and ...` 返回空字符串，随后 int("") 抛错
fix: 先转 bool，再与题型比较；恢复入口自动继续中断的 collect_round
regression_test: tests/test_teaching_plan.py::TestTeachingPlan::
                 test_empty_source_design_does_not_break_ranking
status: fixed
maintainer: solo-project-maintainer
```

### Verification

- Focused teaching-plan tests passed.
- Full suite: `291/291` passed in `154.969s`.
- Live recovery: `synthetic-session-a` resumed to `/answer/1`;
  first answer remained saved and was not duplicated.

## BC-0004

```text
badcase_id: BC-0004
first_seen: 2026-10-03
source: evidence collection answer grading
question_id: 57
student_id: local-test-student
session_id: synthetic-session-a
input: 1000（1+x）^2=1440
expected: 与 1000(1+x)^2=1440 等价，判正确
actual: 程序判错误，error_type=计算
program_fact: 原文使用了全角括号，解析器未归一化
llm_attribution: 当前走程序归因兜底
teacher_judgement: 尚未审核
severity: P1
root_cause_category: program_grading
fix: answer_equiv 先归一化全角括号、正负号、等号和乘号，再做符号等价
regression_test: tests/test_exam_growth_rate.py::TestGrowthRateSolver::
                 test_equation_equivalence_accepts_full_width_parentheses
status: fixed
maintainer: solo-project-maintainer
```

### Verification

- Focused equation-equivalence tests passed.
- Full suite: `292/292` passed in `143.712s`.
- Corrected `AnswerRecord` and checkpoint fact for `synthetic-session-a/q57`
  to `is_correct=true`, `error_type=无错`, `evidence_weight=0.5`.

## BC-0005

```text
badcase_id: BC-0005
first_seen: 2026-10-03
source: historical acceptance / log-derived comparison
question_id: 2
student_id: local-test-student
session_id: synthetic-session-b
input: 选择题步骤只向 LLM 传入作答序号 1/2
expected: LLM 应按选项文本理解学生选择
actual: LLM 把序号当成数学值并产生错误过程归因
program_fact: 程序逐空判分和最终答案均正确
llm_attribution: 归因结论为“无错”，但证据文本描述错误
teacher_judgement: 会话 accept，未发现该输入契约问题
severity: P1
root_cause_category: data_contract
fix: student_steps 对选择题附加 options 和 selected_option_text；
     grader prompt 明确不得把选项序号当数学值
regression_test: tests/test_agents.py::TestGradeQuestionIntegration::
                 test_choice_steps_include_option_context_for_llm
status: fixed
maintainer: solo-project-maintainer
```

### Verification

- Focused attribution tests passed.
- Full suite: `293/293` passed in `150.136s`.
- Current grader prompt fingerprint changed to `a7650164fb16`;
  complete Eval must be rerun before reusing old Eval conclusions.
- 2026-10-05: full suite `316` tests, `0 failed`, `5 skipped` in `179.318s`;
  grader prompt changed to `7c3c2aea3e04` with partial-submission and
  `unfilled` rules. The current Prompt Eval was rerun; see `evals/RESULTS.md`.
