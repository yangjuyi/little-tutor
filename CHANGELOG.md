# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

## [Unreleased]

### Removed

- 将本仓库的维护说明改为本地文件，不再随仓库发布

### Fixed

- 连续下标变量标签（如 `x₁₂`）在数值提取时整体剥除，避免残留数字污染
  数值根集合

### Documented

- 将本地维护说明命名为 `MAINTAINERS.md`，并更新忽略规则
- 明确学科范围：V1/V2 教学与判分闭环只做数学；物理/化学作答结构、
  单位建模与判分管线从 V3 起扩展，现有物理/化学知识卡仅作为数据预留
- 记录 V2 规划：脚手架证据分级与置信度规则化；脚手架不进入判分链路，
  掌握度置信度由可审计证据与老师仲裁驱动
- 记录 V2 规划：判分表示从 `float` 升级为 SymPy 符号等价（含数值采样
  验证兜底）；新增可逆验证原则（逆运算回代 + 形态校验，如因式分解
  `expand(答案) == 原式`）；初中数学题型扩展顺序（分式方程 → 绝对值
  方程 → 圆的计算 → 二次函数综合）
- 记录 V3 规划（基于初高中物理/化学实验与计算真题验证）：七项架构
  缺口（图双 role / 知识型判定 / 化学方程式库 / 物理公式模板库 /
  误差范围判分 / 过程分 / 电路拓扑 schema）；知识库拆分为结构化查表
  与 RAG（RAG 仅服务开放表述判定，全部放 V3）；扩展合格标准 =
  整卷级真题回灌，程序能解的题必须端到端跑通
- README 路线表同步 V2 规划条目

### Changed

- `mastery.wrong_count` 更名为 `confirmed_wrong_count`：原字段名暗示"答错次数"，
  实际语义是"被老师确认的答错次数"（reject 的画像建议不计入）
- `questions.source` 词汇统一为 `public/private/ai_generated`（原 `"AI"` 与 SPEC §6.1 不一致）

## [0.1.1] - 2026-09-02

### Fixed

- **判分重写**：答案比对从子串改为数值集合比对（程序按参数重算根，
  从学生答案提取数值比对，容差 0.01）——修复只答部分根也判对的假阳性，
  以及 `x1` vs `x₁`、`3` vs `3.0`、`1/2` vs `0.5` 格式差异导致的假阴性
- **自适应闭环读回**：每轮出题前从数据库读取当前掌握度（原实现硬编码 weak，
  画像写了不读，"下次出题更准"不生效）
- 审批输入强校验（accept/reject），移除"回车默认 accept"的危险默认
- `profile_update` 节点入口校验：缺 `question` 时在 interrupt 前报错，
  不再等老师拍板后才崩

### Added

- `teacher_decision` 表：老师每次仲裁留痕（reject 也记录，可追溯）
- `answer_records.session_id`：做题记录挂会话（spec §16）
- 生成题落库换真实主键，`answer_records` 外键闭环
- 落库行为自动化测试（临时库）+ 判分单元/集成测试，共 41 项离线测试

### Changed

- 掌握度枚举 6 级对齐为 3 级（weak/mid/strong，与难度混合矩阵同词汇）
- 手动冒烟脚本移入 `scripts/`；README / 维护说明 / SPEC §15 状态刷新，
  实现与设计的差异在 SPEC §15 如实记账

## [0.1.0] - 2026-09-01

### Added

- V1 MVP：双 Agent 闭环（QuestionGenerator 出题：LLM 填参数 + 程序算解；
  Grader 批改：程序判对错 + AI 三把尺归因）
- HITL 画像更新：`interrupt()` 暂停等老师审批，accept 写库 / reject 零写入
- LangGraph 串图（phase 路由 + checkpointer + thread_id 多轮会话）
- SQLAlchemy 2.x + SQLite 数据层；38 张知识卡生成脚本
