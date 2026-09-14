# little-tutor V2 完整验收用例

更新时间：2026-09-14

本文件是 V2 真实体验验收的执行版用例。自动化回归见
`VERIFICATION_PLAYBOOK.md`，完成状态见 `V2_ACCEPTANCE.md`。

## 验收目标

一次真实验收要同时证明五件事：

1. 老师能组卷、审题、修正和做最终决定。
2. 学生能连续作答、请求提示和脚手架，且不会提前看到最终答案。
3. 程序判分、AI 归因、老师结论三层不混淆。
4. 画像只接受真实、完成、老师确认的会话。
5. 桌面和手机都能走完整流程，数据不串、正式库不被污染。

## 环境准备

- 桌面端：Chrome 或 Edge，宽度 1440×900。
- 手机端：390×844 视口，优先真机。
- 老师令牌：`verify-teacher`。
- 每轮验收使用独立验证库；验收结束前不要混用正式库。
- 每轮开始前使用无痕窗口或清除站点 cookie，保证学生身份从空状态开始。

开始服务：

```powershell
$root = Join-Path $env:TEMP "little-tutor-v2-full"
New-Item -ItemType Directory -Path $root -Force | Out-Null
$env:TUTOR_DB_PATH = Join-Path $root "tutor.db"
$env:TUTOR_CHECKPOINT_PATH = Join-Path $root "checkpoints.db"
$env:TUTOR_TEACHER_TOKEN = "verify-teacher"
.\.venv\Scripts\python.exe -m app.adapters.persistence
.\.venv\Scripts\python.exe -m uvicorn app.web:app --host 0.0.0.0 --port 8010
```

访问：

```text
桌面学生端：http://127.0.0.1:8010/
桌面老师端：http://127.0.0.1:8010/teacher/login
手机学生端：http://<局域网IP>:8010/
手机老师端：http://<局域网IP>:8010/teacher/login
```

每轮只记录可观察事实：

- 哪一步卡住；
- 等了多久；
- 系统显示了什么；
- 你原本期待什么；
- 是否影响判分、画像可信度或继续使用意愿。

## P0 必过闭环

### P0-A 认证与角色隔离

| ID | 操作 | 预期 |
|---|---|---|
| A1 | 用错误令牌登录老师端 | 停留登录页，显示错误，不进入审核 |
| A2 | 用 `verify-teacher` 登录 | 进入 `/teacher/review` |
| A3 | 学生端直接访问 `/teacher/review` | 被拦截或跳转登录，不泄漏老师页面 |
| A4 | 学生端查看 HTML 和 URL | 不出现 `thread_id`、`session_id`、H1/H3、interrupt |

### P0-B 组卷与 H1 预审

| ID | 操作 | 预期 |
|---|---|---|
| B1 | 开始一场 `4:4:2`、10 题的练习 | H1 显示 20 道候选题，比例一致 |
| B2 | 检查候选题 | 无完全重复题干，题干校验通过 |
| B3 | 修改一道题的题干和参数 | 程序重算答案、解析、有效根，再回 H1 |
| B4 | 故意把题干和参数改冲突 | 明确拒绝，H1 会话仍可继续 |
| B5 | 点“换一题” | 秒级返回 H1，不出现重复题干 |
| B6 | 调整比例并重组 | 滑条不回退，候选题数量保持 2 倍，难题自动补余 |
| B7 | 全部通过并定稿 | 学生从第 1 题开始，不能先看到答案 |

### P0-C 学生作答闭环

| ID | 操作 | 预期 |
|---|---|---|
| C1 | 第 1 题全部答对并提交 | 程序判正确，学生端不显示 AI 归因 |
| C2 | 第 2 题故意答错 | 程序判错误，显示程序断点，不显示 AI 归因 |
| C3 | 某题只写一个根 | 程序判错，断点指向缺失的根 |
| C4 | 刷新当前题 | 进度、提示和脚手架等级不丢 |
| C5 | 连续快速双击提交 | 只产生一条作答记录，不重复批改 |
| C6 | 浏览器后退到已答题 | 不能重复提交该题 |
| C7 | 所有题完成 | 汇总页显示全部题级结果，不能重开同一会话 |

### P0-D 提示与脚手架

| ID | 操作 | 预期 |
|---|---|---|
| D1 | 请求第 1 级提示 | 只给方法方向，不出现最终答案 |
| D2 | 连续请求到第 3 级提示 | 提示升级，仍不泄露最终答案 |
| D3 | 提示后点“还是不会，给我分步帮助” | 出现分步帮助 1/2，只讲当前步骤 |
| D4 | 再请求一次分步帮助 | 出现 2/2，到上限后不再增加 |
| D5 | 在脚手架状态下答对并提交 | `scaffold_level>0`，`assistance_level=scaffolded`，`evidence_weight=0.25` |
| D6 | 进入下一题 | `hint_level` 和 `scaffold_level` 重置为 0 |

### P0-E 证据与落库

| ID | 检查 | 预期 |
|---|---|---|
| E1 | `answer_records` 数量 | 与本次实际作答数一致 |
| E2 | `first_attempt_correct` | 首次提交结果与记录一致 |
| E3 | `hint_count` / `scaffold_level` | 与页面请求次数一致 |
| E4 | `assistance_level` | 独立/提示/脚手架分别正确 |
| E5 | AI 归因失败时 | `error_type=未归因`，`evidence_source=program`，不进入错因雷达 |
| E6 | 老师修正错因后 | `AnswerRecord.error_type` 更新，`TeacherDecision(edit)` 保留前后值 |

### P0-F H3 老师确认与画像

| ID | 操作 | 预期 |
|---|---|---|
| F1 | 打开 H3 确认页 | 显示正确率、掌握建议、题级证据，不出现内部术语 |
| F2 | 把建议等级改为 `strong` | accept 后 mastery 写入 `strong`，记录 `teacher_corrected` |
| F3 | 修正一道错因 | 作答记录更新，AI 原归因和修正值都留痕 |
| F4 | 勾选“测试会话”后 accept | 不写 mastery，会话 `data_source=test`，完成页提示测试会话 |
| F5 | 不勾测试会话，选择 accept | mastery 只写一次，`review_status=accepted` |
| F6 | 选择 reject | mastery 不写，老师决定和答题事实保留，`review_status=rejected` |
| F7 | 答错后 accept | `confirmed_wrong_count` 增加，掌握度不被单题直接覆盖 |
| F8 | 重复提交 H3 | 不产生重复 mastery 或重复老师决定 |

## P1 边界与证据

| ID | 操作 | 预期 |
|---|---|---|
| P1-1 | 全部答错后 accept | 掌握度下降，错因统计按实际归因聚合 |
| P1-2 | 全部答对后 accept | 掌握度按会话规则升级，不因单题直接到 strong |
| P1-3 | 提示后答对 | 证据权重 0.5，不作为独立答对升级 |
| P1-4 | 脚手架后答对 | 证据权重 0.25，不作为独立答对升级 |
| P1-5 | AI 服务异常 | 程序判分仍正确，归因降级为未归因，老师可正常确认 |
| P1-6 | 错因修正为“漏根” | 完成页错因雷达能体现，不因不在旧五类中丢失 |
| P1-7 | 应用题只取有效正根 | 不显示不合题意的负根 |
| P1-8 | 分数、小数、`x1/x2` 顺序 | 判分和断点均正确 |

## P2 并发、隔离与低概率场景

| ID | 操作 | 预期 |
|---|---|---|
| P2-1 | 两个窗口同时提交同一会话 | 一个成功，另一个收到忙提示，不产生分叉 |
| P2-2 | 两个 worker 连同一验证库 | 会话租约阻止并发写，过期后可恢复 |
| P2-3 | 标记测试会话后再检查画像 | 该会话不进入掌握度、错因统计和轨迹证据 |
| P2-4 | 中断未完成会话 | 只保留事实，不进入画像 |
| P2-5 | 老师中途重启进程 | checkpoint 可续跑，审批不重复落库 |
| P2-6 | 正式库哈希前后对比 | 全量测试和真实验收前后哈希不变 |
| P2-7 | 手机端 390px | 无横向滚动、无遮挡、按钮可点、图表可读 |
| P2-8 | 桌面端 1440px | 三栏/两栏不重叠，长题干不溢出 |

## 自动化覆盖映射

以下内容优先由自动化保证，手工只抽查：

| 范围 | 自动化入口 |
|---|---|
| 判分、参数、题干语义 | `tests.test_agents` / `tests.test_question_edit` |
| H1/H3 生命周期 | `tests.test_session_graph` |
| 模板、提示、脚手架 | `tests.test_template` / `tests.test_hints` |
| 证据权重、掌握度 | `tests.test_domain_adaptation` / `tests.test_mastery` |
| 会话隔离、租约 | `tests.test_session_store` |
| Web 全流程 | `tests.test_web` |
| 真实 LLM accept/reject | `scripts/e2e_smoke.py` |
| 错误答案真实链路 | `scripts/e2e_smoke.py 2 accept wrong` |

## 记录模板

```text
用例 ID：
环境：桌面 / 手机
前置：
操作：
实际结果：
是否通过：
问题照片/录屏：
是否影响判分：
是否影响画像：
备注：
```

## 验收结论

V2 可以判定为收口，必须同时满足：

1. P0 用例全部通过。
2. P1 中与判分、画像、证据、权限相关的用例通过。
3. P2 中正式库隔离和手机完整流程通过。
4. 自动化回归和真实 accept/reject 冒烟通过。
