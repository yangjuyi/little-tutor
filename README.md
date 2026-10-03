# 助教小老师 · little-tutor

面向初中数学的自适应教学系统：根据学生画像自动**出题、批改、归因**，
画像更新经**老师确认（human-in-the-loop）**后才落库生效。

> 详细设计文档见 [PROJECT_SPEC.md](PROJECT_SPEC.md)（含 V1-V3 演进路线与架构分层），
> 对外能力口径与当前证据见 [CAPABILITY_STATUS.md](CAPABILITY_STATUS.md)，
> V2 验收状态见 [V2_ACCEPTANCE.md](V2_ACCEPTANCE.md)，
> 完整手工用例见 [V2_FULL_ACCEPTANCE_CASES.md](V2_FULL_ACCEPTANCE_CASES.md)，
> 验证与真实体验流程见 [VERIFICATION_PLAYBOOK.md](VERIFICATION_PLAYBOOK.md)，
> 离线评测集与指标见 [evals/README.md](evals/README.md)，
> 产品参考见 [PRODUCT_RESEARCH.md](PRODUCT_RESEARCH.md)，
> 版本变更见 [CHANGELOG.md](CHANGELOG.md)

## 当前状态：V2 验收通过 + V2.5-lite 综合题评估基础

LangGraph 核心闭环已端到端跑通：

- **判分与归因节点分离**：程序事实节点负责算解、最终对错、过程断点和逐空结果；
  LLM 归因节点只输出错因建议与证据，不拥有 `is_correct` 字段。答案和过程均
  正确时直接走程序 fallback，不浪费一次归因调用。
- **HITL 画像更新**：批改后 AI 给出画像变更建议，`interrupt()` 暂停等老师审批，
  accept 才写库、reject 零写入（副作用后置 + 决定分流）
- **会话级图**：`read_profile → generate_question_set → H1 预审 → 单题作答/程序判分
  → summarize_profile → H3 批量确认`；checkpointer + thread_id 支持跨请求和
  跨进程恢复，一次会话最多打断老师两次。H1/H3 非法审批会重新进入审批中断，
  不会把异常直接抛穿图；未知 phase/decision 统一进入 failed。
- **持久化**：SQLAlchemy 2.x + SQLite（students / knowledge_points / questions /
  mastery / answer_records / practice_sessions / profiles / teacher_decisions
  八表；掌握度 3 级，做题记录带 session_id，老师每次仲裁都留痕）
- **判分**：数值集合比对（程序重算根 vs 学生答案提取数值，容差 0.01），
  修复了子串比对的假阳性/假阴性
- **连续作答**：每题提交或跳过后直接进入下一题；程序判分、断点和归因在后台
  记录，全部完成后统一展示，错因与画像更新仍由老师确认后生效
- **主动跳过**：学生确实不会时可直接“这题不会，先跳过”；系统记录未作答
  事实和证据不足，不伪造错因，交给老师判断
- **过程判分分层**：最终答案正确但中间步骤错误时显示“过程错误”，保留可读
  断点，不允许最终答案覆盖过程错误
- **会话内自适应**：根据独立作答、提示/脚手架和答题正误更新目标难度，
  从老师已审核候选题中动态选择下一题
- **题干语义校验**：老师修改题干或参数后，程序按题型提取方程、面积、乘积
  或根与系数事实并双向核对；冲突题不能进入已审核题池，预审会话保持可继续
- **题目单一事实源**：旧题和种子题入池前按参数重算答案、有效根和解析，
  组卷路径统一按题干去重
- **角色入口分离**：学生端与 `/teacher/*` 老师端分离；配置
  `TUTOR_TEACHER_TOKEN` 后老师入口需要共享令牌
- **角色流程分离**：学生开始练习后进入等待审核页，老师预审完成后自动进入答题
- **老师会话选择**：老师登录后可从会话列表选择待预审/答题中/待确认的会话，
  不依赖学生浏览器 Cookie，支持在自己设备上处理
- **老师完成页独立**：老师确认后进入老师完成页，学生端独立进入学习小结，
  不再互相依赖 Cookie
- **结果等待自动刷新**：老师打开结果确认页时，学生未完成则显示等待页面并自动检查；
  学生完成后无需手动刷新即可进入画像确认
- **学生/老师结果边界**：学生查看程序作答总结后点击“提交给老师确认”，进入
  学生等待页；老师在自己的确认页处理，学生不会进入老师工作流
- **老师登录保护**：同一来源连续失败 5 次后短锁定 30 秒
- **多 worker 会话租约**：同一会话的写操作通过数据库租约串行化，过期租约
  可自动恢复
- **过程诊断切片**：领域层已新增步骤转换诊断契约和一元一次/二次方程诊断器，
  当前未接入主链路，排 V2.5
- **真实题主链路垂直切片**：增长率 / 降价率 15 道真实/专题题完成结构化解题、
  原题型作答、答案等价、程序判分、H1 预审和会话主链路验收；多选真题保留
  A/B/C/D，数值与列方程题使用最终作答输入。学生首页可选择
  “真实中考增长率与降价率”
- **真实题样本扩展**：私有中考题扩展到 49 道；增长率 17、利润/销售 15、
  面积/几何 15 已达到样本积累门槛；后两类仍需补 solver、作答结构和主链路。
- **程序初评与老师终审分层**：程序判分作为不可变事实保留，老师在 H3 可以
  推翻任意题目的程序对错；只有老师确认后的有效结论进入会话正确率和学生画像。
- **题型 handler 注册表**：新增 `domain/assessment` 契约与注册表；增长率作为
  第一个独立题型插件，核心层通过统一接口完成物化、模板构建、答案判定和
  LLM 适配，避免继续向主链路堆题型 `if`。
- **通用作答元素**：选择、数值/表达式、符号方程由独立响应元素判定；后续
  数学、物理和化学题型可以复用同一套作答和评分基础。
- **真实多问解答题**：2024 西藏、2025 岳麓模拟已拆成 `(1)(2)` 子问题，
  子问题独立作答/判分，老师可逐问确认；两道题覆盖增长率、后续金额和最大数量。
- **题库优先**：启动练习时自动加载公开种子题和本地私有训练题，优先挑库，
  缺题槽位再使用程序化题目设计器
- **老师错因修正与测试会话**：H3 可修正题级错因并保留 AI 原归因记录；
  测试会话只保留事实和老师决定，不进入学生画像
- **业务写入逻辑幂等**：作答记录按
  `(session_id, question_id, attempt_no)` 去重；老师决定与 accept 后画像更新
  在同一业务库事务内执行，重复提交相同决定不会重复累加 mastery
- **状态契约防护**：GradeState 入口校验 `current_question/student_steps`；
  plan/generated 缺失或重复 index 会进入 failed，而不是在字典取值时抛 KeyError
- **归因失败隔离**：LLM 请求显式配置超时和有限重试；超时或异常时保留
  程序判分事实并降级为 `evidence_source=program`，主流程继续进入老师确认
- **分层脚手架**：提示后仍卡住可请求分步帮助；脚手架只给当前步骤方法，
  不泄露最终答案，提交后按 `scaffolded` 证据权重进入画像链

## 快速开始

```bash
# 1. 创建虚拟环境（CI 基线 Python 3.12；本机 Windows 已在 3.14.6 验证）
python -m venv .venv
.venv\Scripts\activate          # Windows；macOS/Linux 用 source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置模型（默认 DeepSeek）
copy .env.example .env          # 编辑 .env 填入 API Key
# 可选：OPENAI_TIMEOUT_SECONDS=30、OPENAI_MAX_RETRIES=2

# 4. 初始化数据库
python -m app.adapters.persistence

# 5. 跑单元测试（308 项，全程离线）
python -m unittest discover -s tests -v

# 6. 启动会话制命令行（组卷预审→连续作答×N→批量画像确认，一次会话打断 ≤2 次）
python -m app.cli

# 7. 启动简易 Web 演示版（Windows 推荐双击 start-tutor.bat）
python -m uvicorn app.web:app --port 8000
```

Windows 一键启动 / 停止：

- 双击 `start-tutor.bat`：后台启动服务、等待健康检查通过，然后打开浏览器。
- 双击 `stop-all.bat`：只停止本项目 PID 文件记录的 uvicorn 进程。
- 运行日志写入 `outputs/runtime/`。

真实浏览器自动化验收（服务启动后执行）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_browser_acceptance.ps1
```

## 目录结构

```
little-tutor/
├── PROJECT_SPEC.md          # 总设计文档（V1-V3 路线）
├── app/
│   ├── domain/              # 判分、题型、模板、会话、证据、领域模型
│   ├── harness/             # LangGraph State、会话级图、旧版兼容图
│   ├── application/         # 学生练习、老师审核、画像证据
│   ├── adapters/            # LLM、SQLAlchemy、checkpoint、题库、会话存储
│   ├── web/                 # 学生路由、老师路由、视图模型
│   ├── templates/           # Web 页面模板
│   ├── cli.py               # 会话制命令行入口
│   └── runtime.py           # 运行路径与测试隔离
├── data/
│   ├── build_knowledge_base.py
│   └── generated/           # 生成的知识卡片 JSON
├── evals/                    # 公开 45 条 + 本地私有题离线评测（当前私有 180 条）
├── scripts/                 # 手动冒烟脚本（调真实 LLM，不进自动化测试）
└── tests/                   # 308 项单元测试（含节点隔离、HITL 分流和落库行为测试）
```

## 开发路线

> 执行优先级以 [ROADMAP.md](ROADMAP.md) 为准；下表只做摘要。

| 阶段 | 内容 | 状态 |
|---|---|---|
| V1/P1 | 出题/批改职责分离 + HITL 闭环 MVP | ✅ |
| V2/P2 | 模板填空、程序判分后台记录+会话后汇总、会话级图、难度参数化、掌握度规则、错因修正/测试标记、分层脚手架 | ✅ 验收通过 |
| V2.5-lite | 综合题 handler / response element / Subquestion 基础已接入；继续扩真实多步题和部分分 | 🚧 进行中 |
| V2.5 | 过程诊断旁路接入 + 多 Agent 教学子图 + Trace/证据分级 | ⏳ |
| V3.0 | Vue 角色化前端 + FastAPI API + 移动端体验 | ⏳ |
| V3.1 | RAG（仅开放表述）+ 评测 + 模型路由 | ⏳ |
| V3.2 | 基础设施、部署、可观测性 | ⏳ |
| V3.3 | 物理/化学插件 + OCR 输入适配器 | ⏳ |

> 关键边界：V1/V2 只做数学；模板填空是默认输入；分步过程诊断排 V2.5；
> RAG 和 OCR 不阻塞 V2 收口；家长端只做老师可分享的只读报告，不做登录端。

## 已知限制

- 对错判定已改为数值集合比对：每个根都需在学生答案中出现（容差 0.01），
  分数/小数/下标格式均可；推导文本中的多余数字不影响判定。
  逐空判定仍由后续"模板填空"体系根治
  - 已知残留边界：若根恰为 0，学生推导文本中的 "=0" 可能被提取为该根
    （CLI 只收最终答案，实际影响有限；逐空判定根治）
- 当前模板和判分范围以一元二次方程为主线；增长率/降价率为首个真实题主链路
  切片，其他题型仍处于离线求解或样本积累阶段。
- 过程诊断只覆盖一元一次/二次方程的相邻步骤转换，尚未接入主流程；
  分步输入不是默认作答方式。

## License

MIT，见 [LICENSE](LICENSE)
