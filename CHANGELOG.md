# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

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
- 手动冒烟脚本移入 `scripts/`；README / AGENTS / SPEC §15 状态刷新，
  实现与设计的差异在 SPEC §15 如实记账

## [0.1.0] - 2026-09-01

### Added

- V1 MVP：双 Agent 闭环（QuestionGenerator 出题：LLM 填参数 + 程序算解；
  Grader 批改：程序判对错 + AI 三把尺归因）
- HITL 画像更新：`interrupt()` 暂停等老师审批，accept 写库 / reject 零写入
- LangGraph 串图（phase 路由 + checkpointer + thread_id 多轮会话）
- SQLAlchemy 2.x + SQLite 数据层；38 张知识卡生成脚本
