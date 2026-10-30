# Eval Harness

本目录用于对 little-tutor 的程序判分和 LLM 归因做离线评测。评测用例从公开
种子题生成，私有题只在本机通过 `--include-private` 临时使用，不提交到仓库。

本文件只定义“怎么运行 Eval 和指标含义”，不维护当前能力状态。当前 Eval 结果
见 `RESULTS.md`；当前对外能力边界见 `../CAPABILITY_STATUS.md`。

## 生成公开评测集

```powershell
.\.venv\Scripts\python.exe evals\build_cases.py
```

当前公开集：`9` 道题 × `5` 种作答状态 = `45` 个用例。

五种状态：

- 有过程且最终答案正确
- 只给最终答案且正确
- 只回答部分根
- 最终答案错误
- 完全无步骤

## 本地私有增强集

```powershell
.\.venv\Scripts\python.exe evals\build_cases.py --source private --output outputs\evals\private_v1.jsonl
```

该输出路径已被 `.gitignore` 排除。

如需一次生成公开题和私有题合并集：

```powershell
.\.venv\Scripts\python.exe evals\build_cases.py --source all --output outputs\evals\all_v1.jsonl
```

如已下载中考专题原文，可导入私有中考题并生成审查稿：

```powershell
.\.venv\Scripts\python.exe evals\import_middle_exam_source.py
.\.venv\Scripts\python.exe evals\review_private_bank.py
```

真实题求解验收：

```powershell
.\.venv\Scripts\python.exe -X utf8 evals\run_real_exam_acceptance.py
```

该命令只统计 `real_exam_acceptance`，不会把生成题结果混入中考能力结论。

老师决定与归因证据汇总（只读）：

```powershell
.\.venv\Scripts\python.exe -X utf8 evals\report_teacher_decisions.py
```

该脚本输出老师决定计数、错因修正次数、结果推翻次数和“作答到决定延迟”。
当前 schema 没有逐题审核分母，因此不计算虚假的采纳率或修正率；延迟也不
等于人工审核耗时。badcase 记录模板见 `evals/BADCASE_RECORDING.md`。

增长率真实题主链路验收：

```powershell
.\.venv\Scripts\python.exe -X utf8 evals\run_real_exam_main_chain_acceptance.py
```

该命令使用隔离临时库，验证 15 道增长题的正确答案接受、错误答案拒绝，
并额外跑 H1 预审 + 正确作答 / 错误作答图流程。

## 离线运行

```powershell
.\.venv\Scripts\python.exe evals\run_eval.py --mode program
```

离线模式只验证评测框架和程序判分契约，不调用模型。

## 真实 LLM 运行

```powershell
.\.venv\Scripts\python.exe -X utf8 evals\run_eval.py --mode real
```

真实模式逐条调用当前 `grader_v1.md`，报告写入 `outputs/evals/`。

只跑某类用例：

```powershell
.\.venv\Scripts\python.exe -X utf8 evals\run_eval.py --mode real --tag no_steps
```

## 当前结果

本文件不重复维护当前测试数、Prompt 指纹和 Eval 指标。结果见 `RESULTS.md`，
对外边界见 `../CAPABILITY_STATUS.md`。
- 正确题和无步骤题会按设计跳过 LLM，直接使用程序证据；这类正常路径计入
  `program_evidence_rate`，不再沿用旧指标名 `fallback_rate`。
- 私有中考题：`49` 道；离线结构化求解 `20` 道。
- 增长率 / 降价率：`15/15` 完成主链路验收。
- 双会话自适应：画像升级与降级会改变下一轮难度配比，端到端测试通过。
- 判别式第二 handler：已注册，当前 1 道真实题通过 handler 路径。
- 真实多问解答题：2 道 `(1)(2)` 题目已接入主链路子问题机制。
- 程序初评与老师终审分层：`is_correct` 保留程序事实，
  `teacher_is_correct` 保存老师确认结论。
- 通用 response element：`choice`、`numeric/expression`、
  `symbolic/equation`。
- 过程诊断：离线切片已实现，尚未接入主练习链路。
- RAG、OCR、多 Agent、物理和化学：尚未实现。

## 指标

- `program_accuracy`：程序判分是否符合用例预期
- `attribution_nonempty_rate`：错误或正确状态是否都有非空归因
- `program_evidence_rate`：最终归因证据来自程序路径的比例，包含正常跳过和
  确定性归一化，不等同于 LLM 故障兜底
- `llm_evidence_rate`：最终归因证据来自 LLM 的比例
- `correct_guard_pass_rate`：正确作答是否被守住为 `无错`
- `wrong_guard_pass_rate`：错误作答是否被守住为非空错因
- `insufficient_evidence_rate`：无步骤用例是否正确标记证据不足
- `no_evidence_over_attribution_rate`：无步骤用例仍被强行归因的比例
- `error_type_distribution`：错因分布
- `latency_ms_*`：各条归因耗时
- `grader_prompt_sha256_12`：运行时的批改 prompt 版本指纹
