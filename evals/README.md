# Eval Harness

本目录用于对 little-tutor 的程序判分和 LLM 归因做离线评测。评测用例从公开
种子题生成，私有题只在本机通过 `--include-private` 临时使用，不提交到仓库。

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

## 指标

- `program_accuracy`：程序判分是否符合用例预期
- `attribution_nonempty_rate`：错误或正确状态是否都有非空归因
- `fallback_rate`：LLM 不可用或结构失败后走程序兜底的比例
- `correct_guard_pass_rate`：正确作答是否被守住为 `无错`
- `wrong_guard_pass_rate`：错误作答是否被守住为非空错因
- `insufficient_evidence_rate`：无步骤用例是否正确标记证据不足
- `no_evidence_over_attribution_rate`：无步骤用例仍被强行归因的比例
- `error_type_distribution`：错因分布
- `latency_ms_*`：各条归因耗时
- `grader_prompt_sha256_12`：运行时的批改 prompt 版本指纹
