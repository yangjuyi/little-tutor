# 助教小老师 · little-tutor 🎓

一个给初中/高中数学、物理、化学学生用的**自适应出题与辅导** AI 助教：
根据每个学生的画像，自动 **出题、批改、讲解、规划复习**，让"因材施教"真正落地。

> 📐 详细设计文档见 [PROJECT_SPEC.md](PROJECT_SPEC.md)

## 功能特性

- 🧠 **学生画像（Student Model）**：6 级掌握度 × 8 类易错 × 7 项能力 × 学习偏好/行为
- 📝 **自适应出题**：针对学生薄弱点生成个性化题目（附解析）
- ✅ **自动批改**：判对错 + 错因归因
- 💡 **讲解 + 变式题**：引用知识库，按学生偏好讲解
- 📋 **复习规划**：优先安排薄弱知识点
- 👤 **人机协同**：AI 给出画像更新建议，老师确认后生效（human-in-the-loop）

## 技术栈

Python 3.12 · LangChain · LangGraph · FastAPI · SQLAlchemy · SQLite · Chroma

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
# Windows：.venv\Scripts\activate ；macOS/Linux：source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env    # 然后编辑 .env 填入你的 Key

# 4. 初始化数据库
python -m app.db
```

## 目录结构

```
little-tutor/
├── PROJECT_SPEC.md          # 项目规格说明书
├── README.md                # 本文件
├── requirements.txt
├── .env.example
├── app/                     # 主代码
│   ├── db.py                # SQLAlchemy 建表
│   ├── knowledge_base.py    # 知识卡片 + Chroma 检索（V2）
│   ├── profiles.py          # 学生画像读写（V2）
│   ├── agents.py            # LangGraph 多 Agent 编排（V3）
│   └── main.py              # FastAPI 入口（V3）
├── data/
│   └── generated/           # 生成的知识卡片 JSON
└── tests/                   # 评测与单元测试
```

## 开发路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| 骨架 | 项目结构 + 数据库 | 🚧 进行中 |
| V1 | Dify 原型验证想法 | ⏳ |
| V2 | LangChain 重写：出题/批改/讲解 + RAG | ⏳ |
| V3 | 多 Agent 闭环 + FastAPI + 评测 | ⏳ |

## License

MIT（待定）
