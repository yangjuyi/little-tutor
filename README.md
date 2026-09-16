# 助教小老师 · little-tutor

面向初中数学的自适应教学系统：根据学生画像自动**出题、批改、归因**，
画像更新经**老师确认（human-in-the-loop）**后才落库生效。

> 详细设计文档见 [PROJECT_SPEC.md](PROJECT_SPEC.md)（含 V1-V3 演进路线与架构分层），
> V2 验收状态见 [V2_ACCEPTANCE.md](V2_ACCEPTANCE.md)，
> 完整手工用例见 [V2_FULL_ACCEPTANCE_CASES.md](V2_FULL_ACCEPTANCE_CASES.md)，
> 验证与真实体验流程见 [VERIFICATION_PLAYBOOK.md](VERIFICATION_PLAYBOOK.md)，
> 离线评测集与指标见 [evals/README.md](evals/README.md)，
> 产品参考见 [PRODUCT_RESEARCH.md](PRODUCT_RESEARCH.md)，
> 版本变更见 [CHANGELOG.md](CHANGELOG.md)

## 当前状态：v0.2.0 baseline（V2 验收通过，待提交）

LangGraph 核心闭环已端到端跑通：

- **双职责 LLM 流程**：出题生成和批改归因职责分离（LLM 只填参数/报归因，
  程序精确算解并判定对错）
- **HITL 画像更新**：批改后 AI 给出画像变更建议，`interrupt()` 暂停等老师审批，
  accept 才写库、reject 零写入（副作用后置 + 决定分流）
- **会话级图**：`read_profile → generate_question_set → H1 预审 → 单题作答/程序判分
  → summarize_profile → H3 批量确认`；checkpointer + thread_id 支持跨请求和
  跨进程恢复，一次会话最多打断老师两次
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
- **题库优先**：启动练习时自动加载公开种子题和本地私有训练题，优先挑库，
  缺题槽位再使用程序化题目设计器
- **老师错因修正与测试会话**：H3 可修正题级错因并保留 AI 原归因记录；
  测试会话只保留事实和老师决定，不进入学生画像
- **分层脚手架**：提示后仍卡住可请求分步帮助；脚手架只给当前步骤方法，
  不泄露最终答案，提交后按 `scaffolded` 证据权重进入画像链

## 快速开始

```bash
# 1. 创建虚拟环境（Python 3.12）
python -m venv .venv
.venv\Scripts\activate          # Windows；macOS/Linux 用 source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置模型（默认 DeepSeek）
copy .env.example .env          # 编辑 .env 填入 API Key

# 4. 初始化数据库
python -m app.adapters.persistence

# 5. 跑单元测试（224 项，全程离线）
python -m unittest discover -s tests -v

# 6. 启动会话制命令行（组卷预审→连续作答×N→批量画像确认，一次会话打断 ≤2 次）
python -m app.cli

# 7. 启动简易 Web 演示版（三段式页面：组卷预审 / 连续作答+汇总 / 批量确认）
python -m uvicorn app.web:app --port 8000
```

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
├── evals/                    # 公开 45 条 + 可选私有题的离线评测集
├── scripts/                 # 手动冒烟脚本（调真实 LLM，不进自动化测试）
└── tests/                   # 224 项单元测试（含 HITL 分流守护 + 落库行为测试）
```

## 开发路线

> 执行优先级以 [ROADMAP.md](ROADMAP.md) 为准；下表只做摘要。

| 阶段 | 内容 | 状态 |
|---|---|---|
| V1/P1 | 出题/批改职责分离 + HITL 闭环 MVP | ✅ |
| V2/P2 | 模板填空、即时反馈、会话级图、难度参数化、掌握度规则、错因修正/测试标记、分层脚手架 | ✅ 验收通过 |
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
- 当前模板和判分范围仍以一元二次方程为主线，复杂题型与单位建模留后续阶段。
- 过程诊断只覆盖一元一次/二次方程的相邻步骤转换，尚未接入主流程；
  分步输入不是默认作答方式。

## License

MIT，见 [LICENSE](LICENSE)
