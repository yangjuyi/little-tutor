# 助教小老师 · little-tutor

面向初中数学的自适应教学系统：根据学生画像自动**出题、批改、归因**，
画像更新经**老师确认（human-in-the-loop）**后才落库生效。

> 详细设计文档见 [PROJECT_SPEC.md](PROJECT_SPEC.md)（含 V1-V3 演进路线与架构分层），
> 版本变更见 [CHANGELOG.md](CHANGELOG.md)

## 当前状态：v0.1 MVP

LangGraph 核心闭环已端到端跑通：

- **双 Agent 分工**：QuestionGenerator 出题（LLM 只填参数，程序精确算解）、
  Grader 批改（程序判对错 + AI 三把尺归因）
- **HITL 画像更新**：批改后 AI 给出画像变更建议，`interrupt()` 暂停等老师审批，
  accept 才写库、reject 零写入（副作用后置 + 决定分流）
- **串图与会话**：`generate → grade → profile_update` 按 phase 路由，
  checkpointer + thread_id 支持多轮会话
- **持久化**：SQLAlchemy 2.x + SQLite（students / knowledge_points / questions /
  mastery / answer_records / profiles / teacher_decisions 七表；掌握度 3 级，
  做题记录带 session_id，老师每次仲裁都留痕）
- **判分**：数值集合比对（程序重算根 vs 学生答案提取数值，容差 0.01），
  修复了子串比对的假阳性/假阴性

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
python -m app.db

# 5. 跑单元测试（41 项，全程离线）
python -m unittest discover -s tests -v

# 6. 启动 MVP 命令行（出题→作答→批改→老师审批→下一题）
python -m app.run_mvp
```

## 目录结构

```
little-tutor/
├── PROJECT_SPEC.md          # 总设计文档（V1-V3 路线）
├── app/
│   ├── state.py             # LangGraph State / 数据模型（TypedDict）
│   ├── db.py                # SQLAlchemy 建表与会话
│   ├── agents.py            # 出题 / 批改 Agent（结构化输出 + 程序兜底）
│   ├── profile_update.py    # HITL 画像更新节点（interrupt）
│   ├── graph.py             # 串图：phase 路由 + checkpointer
│   ├── run_mvp.py           # 多轮命令行入口
│   └── prompts/             # Prompt 独立文件（版本可回退）
├── data/
│   ├── build_knowledge_base.py
│   └── generated/           # 生成的知识卡片 JSON
├── scripts/                 # 手动冒烟脚本（调真实 LLM，不进自动化测试）
└── tests/                   # 41 项单元测试（含 HITL 分流守护 + 落库行为测试）
```

## 开发路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| V1/P1 | 双 Agent + HITL 闭环 MVP（本仓库当前形态） | ✅ v0.1 |
| V2/P2 | 持久化（SqliteSaver）/ Send 并发 / 子图 / 掌握度升级规则 / 难度参数化 / 模板填空作答 / 学生即时反馈 / 会话级图重构（组卷预审 + 批量确认）/ 脚手架证据分级 / 置信度规则化 / 判分表示升级（SymPy 符号等价） / 初中数学题型扩展 / 家长会话简报 | ⏳ |
| V3/P3 | FastAPI 服务化 + Web；物理/化学学科扩展 | ⏳ |
| 后续 | RAG 判定（开放表述）、评测体系 | ⏳ |

> V2/P2 行拆注（2026-09-05）：**掌握度升级规则 / 难度参数化 / 模板填空作答 /
> 学生即时反馈 / 会话级图重构** = V1 定稿未实现的还债项（排 P2 队首）；
> **置信度规则化 / 判分表示升级（SymPy）/ 初中数学题型扩展 / 脚手架证据分级**
> = 真 V2 产品项；**家长会话简报** = V2 定结构与数据字段，P3 随 Web 实现。
> 难度词汇表统一（DifficultyLevel 独立类型）为还债项 B0，先于其余 B 项。

> 学科范围：V1/V2 的教学与判分闭环只做数学；物理/化学的作答结构、
> 单位建模和判分管线从 V3 起扩展。仓库中的物理/化学知识卡与字段
> 只是预留数据，不代表当前管线已支持。

## 已知限制

- 对错判定已改为数值集合比对：每个根都需在学生答案中出现（容差 0.01），
  分数/小数/下标格式均可；推导文本中的多余数字不影响判定。
  逐空判定仍由后续"模板填空"体系根治
  - 已知残留边界：若根恰为 0，学生推导文本中的 "=0" 可能被提取为该根
    （CLI 只收最终答案，实际影响有限；逐空判定根治）
- 会话存档为内存态（InMemorySaver），进程重启即失，
  P2 切换 SqliteSaver 后支持跨天审批

## License

MIT，见 [LICENSE](LICENSE)
