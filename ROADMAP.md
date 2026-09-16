# little-tutor 路线图

更新时间：2026-09-15

本文件是执行优先级的唯一来源。`PROJECT_SPEC.md` 保留产品细节和能力清单，
`ARCHITECTURE.md` 保留分层规则和过程诊断契约。阶段冲突时以本文件为准。

## 双目标

1. **真实可用**：一对一补习闭环能跑通，老师可用，学生输入低摩擦。
2. **面试深度**：HITL、证据分级、多 Agent 可追溯、评测与工程化能讲清楚。

两个目标共用同一套核心闭环，不做两个并行产品。

## 当前状态

- 阶段：`v0.2.0 baseline` + V2 验收通过，待整理提交。
- 自动化：224 项测试通过（2026-09-16 本地复跑）。
- 真实闭环：accept / reject / accept wrong / reject wrong 通过。
- 过程诊断：领域契约和一元一次/二次方程转换器已落地，尚未接入主链路。
- 默认学生输入仍为模板填空；分步输入只作为后续诊断模式。

## V2 收口

V2 已于 2026-09-16 完成功能、浏览器自动化、真实 LLM 和真机人工验收。
过程诊断不属于 V2 完成门槛，提交后进入 V2.5。

## V2.5 诊断增强

1. 将 `TransitionCheck` 旁路接入 `session_graph`，旧 `judge_blanks` 保留回退。
2. 分步输入只做诊断模式：步骤卡片 + 完整表达式，不替代默认作答。
3. 多 Agent 教学子图：
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
