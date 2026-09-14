# little-tutor 验证手册

本文件定义工程回归和真实用户体验测试的执行方法。所有可能写入业务数据的验证
必须先设置隔离数据库路径，禁止直接使用正式库。

## 1. 自动化基线

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

当前基线：`180` 项通过。

真实 LLM 端到端使用临时数据库和临时 checkpoint，退出后自动清理：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\e2e_smoke.py 2 accept
.\.venv\Scripts\python.exe -X utf8 scripts\e2e_smoke.py 2 reject
.\.venv\Scripts\python.exe -X utf8 scripts\e2e_smoke.py 2 accept wrong
.\.venv\Scripts\python.exe -X utf8 scripts\e2e_smoke.py 2 reject wrong
```

`wrong` 模式会让首题最终答案错误，用于验证程序判分、错误证据落库、
AI 归因或程序兜底，以及 H3 在错误作答下的 accept/reject 分流。

LLM 网络不可用时，冒烟允许走“程序判分 + 归因不可用”兜底，但必须满足：

- 正确答案仍判正确；
- 错误答案仍判错误；
- `error_type=未归因`；
- `evidence_source=program`；
- 不进入错因雷达；
- accept/reject 仍能完成生命周期落库。

## 2. 改动与测试对照

| 改动 | 必跑测试 | 通过标准 |
|---|---|---|
| 答案与参数单一事实源 | `tests.test_question_edit`、`tests.test_question_design`、`tests.test_seeds` | 答案、有效根、解析均由参数重算 |
| 旧题自动修复 | `tests.test_session_graph.TestSessionGraph.test_stale_seed_answer_is_recomputed_and_persisted` | 数据库中的旧答案被修复并持久化 |
| 组卷题干去重 | `tests.test_session_graph.TestSessionGraph.test_no_send_path_still_deduplicates_seed_stems` | 无扇出路径也不出现重复题干 |
| 题干语义冲突 | `tests.test_question_edit`、`tests.test_session_graph` | 冲突被拒绝，H1 会话仍可继续 |
| AI 归因失败隔离 | `tests.test_agents.TestGradeFallback`、`tests.test_web.TestWebFlow.test_done_context_aggregates_error_causes` | 不伪造错因，不计入错因雷达 |
| 历史证据权重 | `tests.test_mastery`、`tests.test_persistence_migration` | `evidence_weight` 正确迁移和聚合 |
| 老师角色入口 | `tests.test_web.TestWebFlow.test_teacher_token_guards_teacher_routes` | 未登录跳转登录页，令牌错误被拒绝 |
| 多 worker 会话租约 | `tests.test_session_store` | 两个 worker 并发时只能有一个获得租约 |
| 组卷模块拆分 | 全量测试 | 图、组卷和 Web 行为不变 |

## 3. 隔离环境启动

以下命令创建独立验证库，不会碰正式 `tutor.db`：

```powershell
$verifyRoot = Join-Path $env:TEMP "little-tutor-verify"
New-Item -ItemType Directory -Path $verifyRoot -Force | Out-Null

$env:TUTOR_DB_PATH = Join-Path $verifyRoot "tutor.db"
$env:TUTOR_CHECKPOINT_PATH = Join-Path $verifyRoot "checkpoints.db"
$env:TUTOR_TEACHER_TOKEN = "verify-teacher"

.\.venv\Scripts\python.exe -m app.adapters.persistence
.\.venv\Scripts\python.exe -m uvicorn app.web:app --host 127.0.0.1 --port 8010
```

打开：

```text
学生端：http://127.0.0.1:8010/
老师端：http://127.0.0.1:8010/teacher/login
```

测试结束后关闭服务，并删除 `$verifyRoot`。验证前后可对正式库做哈希确认：

```powershell
Get-FileHash .\tutor.db
Get-FileHash .\checkpoints.db
```

## 4. 老师端真实体验

1. 用错误令牌登录，确认仍停留在老师登录页并显示错误。
2. 用 `verify-teacher` 登录，确认进入 `/teacher/review`。
3. 开始一场 `4:4:2`、共 10 题的练习，确认 H1 出现 20 道候选题。
4. 逐项检查候选题：
   - 每道题显示“题干校验：已通过”；
   - 不存在完全相同的题干；
   - 程序答案与题干一致；
   - 应用题只显示符合题意的有效根。
5. 修改一道根与系数题，把“两根之和”改成错误值，保持参数不变：
   - 应显示“根与系数题题干与参数冲突”；
   - 不出现 `root_relation` 等内部标识；
   - H1 题池仍保留，可继续修改或定稿。
6. 点击“换一题”：
   - 题库有可用题时应在秒级完成；
   - 换题后回到 H1；
   - 不出现重复题干。
7. 调整比例并重组：
   - 提交后滑条值不回退；
   - 候选题数量保持实际题量的 2 倍；
   - 难度比例与提交值一致。
8. 定稿后完成学生流程，在 `/teacher/summary`：
   - accept 后画像更新；
   - reject 后画像不变；
   - 两种决定都保留老师决定记录。

## 5. 学生端真实体验

至少跑三场隔离练习：

### 场景 A：全部正确

- 每题按程序答案作答；
- 作答过程中不提前显示对错；
- 每题提交后程序反馈正确；
- 完成页正确率、画像和错因图正常。

### 场景 B：典型错误

分别覆盖：

- 第一个选择题错误；
- 中间填空题符号错误；
- 最后根只写一个或写错。

检查：

- 程序能定位第一个错误空位；
- 学生即时反馈不展示 AI 归因；
- 老师确认页能看到题级证据；
- 错因不存在时显示“待老师确认”，不伪造“计算错误”。

### 场景 C：提示与浏览器行为

- 连续点击三次“需要提示”；
- 确认提示不泄露最终答案；
- 至少请求一次“还是不会，给我分步帮助”，确认分步帮助只给当前步骤方法，
  不显示最终答案；
- 提交后确认 `scaffold_level > 0`、`assistance_level=scaffolded`、
  `evidence_weight=0.25`；
- 刷新页面后当前题和提示等级不丢失；
- 后退到已答题不能重复提交；
- 快速双击提交按钮只产生一条作答记录；
- 完成后不能重新开始同一会话。

## 6. 多 worker 验证

自动化测试已经覆盖数据库租约互斥。若需要 HTTP 层验证：

1. 两个服务进程连接同一个隔离 `TUTOR_DB_PATH`，监听不同端口。
2. 在两个浏览器窗口打开同一会话，同时提交修改或定稿。
3. 期望结果：
   - 一个请求成功；
   - 另一个收到“处理中”或 `PracticeBusy` 跳转；
   - 不产生重复作答、重复老师决定或状态分叉；
   - 第一个请求完成后，第二个请求可以重试成功。

## 7. UX 验收指标

每场真实体验记录：

| 指标 | 建议门槛 |
|---|---|
| 开始练习到 H1 首屏 | 有题库时 < 2 秒 |
| 换一题 | 题库命中时 < 2 秒 |
| 学生每题操作时间 | 中档题 30 秒到 3 分钟 |
| 老师打断次数 | 每场不超过 2 次 |
| 老师预审时间 | 20 题不超过 10 分钟 |
| 错因说明可理解性 | 老师无需解释内部术语即可判断 |
| 移动端完整流程 | 390px 宽度下无横向滚动、无遮挡 |

每次体验只记录可观察事实：

- 哪一步卡住；
- 等了多久；
- 系统显示了什么；
- 老师或学生原本期待什么；
- 是否影响题目正确性、画像可信度或继续使用意愿。

## 8. 发布前签字清单

- [ ] 全量测试通过。
- [ ] accept/reject 端到端通过。
- [ ] 正式库哈希在测试前后不变。
- [ ] 老师令牌启用时无法绕过登录。
- [ ] 学生无法进入 `/teacher/*`。
- [ ] 无重复题干和答案与参数冲突。
- [ ] 无重复作答、重复老师决定。
- [ ] 多 worker 并发写被租约拦截。
- [ ] AI 失败不伪造错因。
- [ ] 桌面与手机均完成一轮真实流程。
