# 助教小老师 · little-tutor

面向初中数学的自适应教学系统：根据学生画像自动**出题、批改、归因**，
画像更新经**老师确认（human-in-the-loop）**后才落库生效。

> 详细设计文档见 [PROJECT_SPEC.md](PROJECT_SPEC.md)（含 V1-V3 演进路线与架构分层），
> V2 验收状态见 [V2_ACCEPTANCE.md](V2_ACCEPTANCE.md)，
> 验证与真实体验流程见 [VERIFICATION_PLAYBOOK.md](VERIFICATION_PLAYBOOK.md)，
> 产品参考见 [PRODUCT_RESEARCH.md](PRODUCT_RESEARCH.md)，
> 版本变更见 [CHANGELOG.md](CHANGELOG.md)

## 当前状态：v0.1.1 MVP

LangGraph 核心闭环已端到端跑通：

- **双 Agent 分工**：QuestionGenerator 出题（LLM 只填参数，程序精确算解）、
  Grader 批改（程序判对错 + AI 三把尺归因）
- **HITL 画像更新**：批改后 AI 给出画像变更建议，`interrupt()` 暂停等老师审批，
  accept 才写库、reject 零写入（副作用后置 + 决定分流）
- **串图与会话**：`generate → grade → profile_update` 按 phase 路由，
  checkpointer + thread_id 支持多轮会话
- **持久化**：SQLAlchemy 2.x + SQLite（students / knowledge_points / questions /
  mastery / answer_records / practice_sessions / profiles / teacher_decisions
  八表；掌握度 3 级，做题记录带 session_id，老师每次仲裁都留痕）
- **判分**：数值集合比对（程序重算根 vs 学生答案提取数值，容差 0.01），
  修复了子串比对的假阳性/假阴性
- **即时反馈**：每题提交后先显示程序判分和程序断点；错因与画像更新仍由
  老师确认后生效
- **会话内自适应**：根据独立作答、提示/脚手架和答题正误更新目标难度，
  从老师已审核候选题中动态选择下一题
- **题干语义校验**：老师修改题干或参数后，程序按题型提取方程、面积、乘积
  或根与系数事实并双向核对；冲突题不能进入已审核题池，预审会话保持可继续
- **题目单一事实源**：旧题和种子题入池前按参数重算答案、有效根和解析，
  组卷路径统一按题干去重
- **角色入口分离**：学生端与 `/teacher/*` 老师端分离；配置
  `TUTOR_TEACHER_TOKEN` 后老师入口需要共享令牌
- **多 worker 会话租约**：同一会话的写操作通过数据库租约串行化，过期租约
  可自动恢复

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

# 5. 跑单元测试（168 项，全程离线）
python -m unittest discover -s tests -v

# 6. 启动会话制命令行（组卷预审→连续作答×N→批量画像确认，一次会话打断 ≤2 次）
python -m app.cli

# 7. 启动简易 Web 演示版（三段式页面：组卷预审 / 连续作答+汇总 / 批量确认）
python -m uvicorn app.web:app --port 8000
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
├── scripts/                 # 手动冒烟脚本（调真实 LLM，不进自动化测试）
└── tests/                   # 168 项单元测试（含 HITL 分流守护 + 落库行为测试）
```

## 开发路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| V1/P1 | 双 Agent + HITL 闭环 MVP（本仓库当前形态） | ✅ v0.1 |
| V2/P2 | Prompt 文件接线 / 按任务拆温度 / 持久化（SqliteSaver）/ Send 并发 / 子图 / 掌握度升级规则 / 难度参数化 / 模板填空作答 / 学生即时反馈 / 会话级图重构（组卷预审 + 批量确认）/ 简易 Web 演示版（FastAPI 三页面）/ 脚手架证据分级 / 置信度规则化 / 判分表示升级（SymPy 符号等价） / 初中数学题型扩展 / 家长会话简报 | ⏳ |
| V3/P3 | FastAPI 服务化 + Web；物理/化学学科扩展 | ⏳ |
| 后续 | RAG 判定（开放表述）、评测体系 | ⏳ |

> V2/P2 行拆注（2026-09-05）：**掌握度升级规则 / 难度参数化 / 模板填空作答 /
> 学生即时反馈 / 会话级图重构** = V1 定稿未实现的还债项（排 P2 队首）；
> **置信度规则化 / 判分表示升级（SymPy）/ 初中数学题型扩展 / 脚手架证据分级**
> = 真 V2 产品项；**家长会话简报** = V2 定结构与数据字段，P3 随 Web 实现。
> 难度词汇表统一（DifficultyLevel 独立类型）为还债项 B0，已于 2026-09-07 完成；
> B2 难度参数化（难度带约束表 + hard 结构标记 + 违约重试/降级）、
> B3 正确率归因（各难度正确率聚合）、B1 掌握度规则（§16.5 会话聚合，
> strong 需连续两个会话 ≥0.8）、B4 学生即时反馈（程序初评当场可见）、
> 种子题库（9 题 JSON 入册 + 幂等加载）均已于 2026-09-09 完成。
> 2026-09-11 补：组卷缺库槽位改为程序化题目设计器生成，参数通过配方整洁性
> 闸门；Web 答题过程不显示单题结果，全部完成后统一展示题级汇总。
> P2 持久化第一步（SqliteSaver 文件级 checkpoint + 跨实例 resume 测试）
> 已于 2026-09-09 完成；Send 并发 / 子图 / LLM 全局异常兜底仍待做。
> A 模板填空（程序生成模板 + choice/expression 逐空判定 + 断点定位，
> V2 单题型起步、schema 稳定层留扩展位）已于 2026-09-09 完成。
> C 会话级图（H1 组卷预审 interrupt① + 单题循环零打断 + H3 批量确认 interrupt②，
> 挑库优先 + 混难度，一次会话打断 ≤2 次）已于 2026-09-09 完成；
> CLI 已切换会话制（run_mvp）；简易 Web 演示版（FastAPI 三段式，graph/checkpointer
> 全复用，会话凭 cookie 续跑）已于 2026-09-09 完成；P2 收尾（Send 扇出并发生成
> 程序化设计题 / 批改 compiled 子图 / LLM 全局异常兜底——归因挂掉保程序事实，
> 组卷失败 llm_error 收束不炸图）同日完成。**V2 全部落地。**

> V2 执行顺序：Prompt 前置（已完成：接线 question prompt + 补 grader prompt + 按任务拆温度）
> → B0 词汇表统一（已完成）→ B2 难度参数化（已完成）→ B3 正确率归因（已完成）→
> B1 掌握度规则（已完成）→ B4 学生即时反馈（已完成）→
> 种子题库（已完成，C 前置已就绪）→ A 模板填空（已完成）→ C 会话级图 →
> 简易 Web 演示版（V2 收尾）→ P2 Send 并发/子图/异常兜底 → P3 Web 产品化。

> 学科范围：V1/V2 的教学与判分闭环只做数学；物理/化学的作答结构、
> 单位建模和判分管线从 V3 起扩展。仓库中的物理/化学知识卡与字段
> 只是预留数据，不代表当前管线已支持。

## 已知限制

- 对错判定已改为数值集合比对：每个根都需在学生答案中出现（容差 0.01），
  分数/小数/下标格式均可；推导文本中的多余数字不影响判定。
  逐空判定仍由后续"模板填空"体系根治
  - 已知残留边界：若根恰为 0，学生推导文本中的 "=0" 可能被提取为该根
    （CLI 只收最终答案，实际影响有限；逐空判定根治）
- 当前模板和判分范围仍以一元二次方程为主线，复杂题型与单位建模留后续阶段。

## License

MIT，见 [LICENSE](LICENSE)
