# little-tutor 路线图

更新时间：2026-10-06

本文件是执行优先级的唯一来源。当前能力与对外口径以
`CAPABILITY_STATUS.md` 为准；`PROJECT_SPEC.md` 保留产品细节，
`ARCHITECTURE.md` 保留分层规则和过程诊断契约。

## 双目标

1. **真实可用**：一对一补习闭环能跑通，老师可用，学生输入低摩擦。
2. **面试深度**：HITL、证据分级、多 Agent 可追溯、评测与工程化能讲清楚。

两个目标共用同一套核心闭环，不做两个并行产品。

## 当前状态

本文件不维护当前能力、测试数字、Eval 结果或验收结论。当前状态以
[CAPABILITY_STATUS.md](CAPABILITY_STATUS.md) 为准，Eval 结果以
[evals/RESULTS.md](evals/RESULTS.md) 为准，V2 历史验收见
[V2_ACCEPTANCE.md](V2_ACCEPTANCE.md)。

## V2.5-lite 综合题评估基础（当前优先级）

目标是在不破坏现有数学闭环的前提下，形成可持续新增题型家族的平台能力。

1. `SubquestionSpec / Submission / Evaluation`、逐子问题判分和老师逐问确认
   已接入主链路；继续扩真实多步题和部分分策略。
2. 用通用 response element 支持 choice / numeric / symbolic / multi_step。
3. 旧配方法题型迁入 `QuestionHandler`，移除核心题型兼容分支。
4. 当前已接增长率和判别式两个代表家族；继续补真实题样本，每类达到 15 道后验收。
5. 综合题模块只承诺“新增家族不改核心”，不承诺首期覆盖全学科。

## V2.5 诊断增强

1. 将 `TransitionCheck` 旁路接入 `session_graph`，旧 `judge_blanks` 保留回退。
2. 分步输入只做诊断模式：步骤卡片 + 完整表达式，不替代默认作答。
3. 完整 V2.5 多 Agent 教学子图（不属于当前 V2.5-lite）：
   - Diagnosis Agent
   - Teaching Supervisor（第一版规则状态机）
   - Scaffold / Hint Agent
   - Critic Agent
   - Profile Proposal Agent
4. 取消 `Explainer`；Reference Solution 只进老师证据链，不直接给学生。
5. 增加 loop limit、budget、handoff 和 Agent Trace。
6. 置信度规则化：拆分 AI 归因可信度和掌握度置信度。
7. 数学题型与方法扩展：接入因式分解、直接开平方和公式法，由题型声明
   应使用的解题方法；答案表示支持分数、根式和简单无理数，程序做符号等价
   或高精度数值回代，LLM 仍不参与对错判定。
8. 拍照/手写输入继续留 V3.3，通过可插拔输入适配器接入，不替换当前模板填空
   主链路。

> V2.5 多 Agent 教学子图和 V3.1 RAG 的启动条件以
> [ADR-005](docs/adr/0005-defer-rag-and-multi-agent-teaching-graph.md) 为准；
> 列入路线不等于当前承诺实施。

## V3.0 体验层

1. Vue 3 + TypeScript + Vite + Vue Router + Pinia + TanStack Query。
2. 三个前端壳：
   - `StudentShell`：练习、提示、即时程序反馈、掌握度进展。
   - `TeacherWorkspace`：组卷、批量确认、错因修正、题级证据。
   - `ParentReport`：只读报告，不做家长登录。
3. Element Plus 用于老师工作台；学生端使用自定义组件。
4. ECharts、KaTeX、MathLive、PWA。
5. 认证：httpOnly + Secure + SameSite Cookie + CSRF + 服务端 RBAC。
   不使用 JWT localStorage。
6. 先解决“像管理系统”的体验问题，再继续加学科和基础设施。

## V3.1 知识与评测

1. RAG 只服务开放表述判定；结构化查表继续走程序精确查询。
2. 模型路由按任务拆分，不把强模型用于所有环节。
3. 评测：题目质量、归因准确性、掌握度置信度、画像趋势。

## V3.2 基础设施

按真实问题触发，不先堆组件：PostgreSQL、Redis、任务队列、向量库、
日志 / Metrics / Trace、Docker Compose 和反向代理。Kubernetes 暂缓。

## V3.3 学科扩展

1. `SubjectPlugin` / `TrainingPlugin` / `IntegratedPlugin` 三类插件。
2. 物理、化学结构化答案 schema、单位、公式模板和图数据。
3. OCR 作为可插拔输入适配器：先最终答案，再关键步骤确认。
4. 手写画布不作为前置条件；有真实触控笔需求再评估。

## 排序原则

1. 闭环优先于智能程度。
2. 事实层优先于模型层。
3. 体验层不能长期缺席。
4. 过程诊断是增强层，不抢主闭环。
5. 学科扩展后置，先证明数学闭环和角色化体验成立。
6. 真实题负责验收，AI 生成题只负责训练、变式和压力测试。
