# 助教小老师 · little-tutor

面向初中数学的自适应教学系统：根据学生画像自动**出题、批改、归因**，
画像更新经**老师确认（human-in-the-loop）**后才落库生效。

> 详细设计文档见 [PROJECT_SPEC.md](PROJECT_SPEC.md)（含 V1-V3 演进路线与架构分层）

## 当前状态：v0.1 MVP

LangGraph 核心闭环已端到端跑通：

- **双 Agent 分工**：QuestionGenerator 出题（LLM 只填参数，程序精确算解）、
  Grader 批改（程序判对错 + AI 三把尺归因）
- **HITL 画像更新**：批改后 AI 给出画像变更建议，`interrupt()` 暂停等老师审批，
  accept 才写库、reject 零写入（副作用后置 + 决定分流）
- **串图与会话**：`generate → grade → profile_update` 按 phase 路由，
  checkpointer + thread_id 支持多轮会话
- **持久化**：SQLAlchemy 2.x + SQLite（students / knowledge_points / questions /
  mastery / answer_records / profiles 六表）

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

# 5. 跑单元测试（20 项，全程离线）
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
└── tests/                   # 20 项单元测试（含 HITL 分流守护测试）
```

## 开发路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | 双 Agent + HITL 闭环 MVP（本仓库当前形态） | ✅ v0.1 |
| P2 | 持久化（SqliteSaver）/ Send 并发 / 子图 | ⏳ |
| P3 | FastAPI 服务化 + Web（学生答题页 + 老师看板） | ⏳ |
| 后续 | RAG 讲解、模板填空逐空判定、评测体系 | ⏳ |

## 已知限制

- 对错判定基于答案子串比对，未做格式归一化（`x1` vs `x₁`），
  将由"模板填空逐空判定"体系根治
- 会话存档为内存态（InMemorySaver），进程重启即失，
  P2 切换 SqliteSaver 后支持跨天审批

## License

MIT（待定）
