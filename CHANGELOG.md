# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

## [Unreleased]

### Fixed

- 题库派生字段以 `params + design_id` 为唯一事实源：旧题入池前重算
  `valid_roots`、答案和解析并回写数据库；无扇出组卷路径也强制执行题干去重，
  修复同一题重复入池和旧答案与参数矛盾的问题。
- AI 归因失败不再伪造“计算错误”：程序只记录 `未归因` 和证据不足，
  不进入错因雷达，老师端明确显示归因状态。
- 历史会话掌握度证据统一使用 `evidence_weight`，提示后和脚手架后答对
  不再按独立答对计入历史正确率。
- 老师端迁移到 `/teacher/*` 并提供共享令牌访问控制；学生端不再暴露或直接
  跳转老师审核流程。
- 会话写并发改为 `practice_sessions` 数据库租约，移除进程内
  `threading.Lock`；多 worker 下同一会话不会并发写入，租约过期可自动恢复。
- 老师按比例重组后，预审页会回显本次提交的难度比例，不再重置为
  40/40/20 默认值；难题档百分比变化时，禁用滑块位置同步实时更新。
- 测试数据隔离：`TUTOR_DB_PATH` / `TUTOR_CHECKPOINT_PATH` 支持覆盖运行库路径；
  端到端冒烟脚本强制使用临时目录，退出即删除。已清理正式库中的历史测试会话，
  `answer_records 39→3`、`teacher_decisions 3→1`、checkpoint 测试线程全部移除，
  仅保留最后一条真实会话 `web-51a030c4`。
- Web 入口移除手工会话 ID：`student_id` 作为长期身份由 cookie 保留，每次新开
  练习自动生成新的 `thread_id/session_id`；同一浏览器复用同一学生，但不会
  复用上一次练习会话。
- 完成页改为结果看板：新增学生画像雷达图（掌握程度/正确率/步骤正确率/证据
  充分度）与错因雷达图（审题/概念/计算/跳步/粗心），保留答题明细入口；
  桌面与手机尺寸完成截图验证。
- 画像确认页改为老师可用文案：去掉 H3、kp ID、confidence 等内部术语，直接显示
  知识点、答题数、答对数、系统建议和判断依据；按钮改为“确认并更新学生画像”
  与“暂不更新，仅保留记录”。CLI 同步该口径。
- Web 作答改为连续流：答题过程中不显示单题对错，全部完成后统一展示题级汇总；
  `/result/{idx}` 保留为单题详情，不再每题强制跳转。
- 模板提示去除前序中间式子回显，逐步只保留当前操作指令，避免后置空位反向
  提示前序答案。

### Added

- 过程诊断垂直切片：新增 `StudentStepV2`、`Submission`、`TransitionCheck`
  领域契约和一元一次/二次方程转换诊断器；可定位首个不成立转换、识别
  漏根并标记过程证据不足，当前只新增领域能力与单测，尚未接入主业务链路。
- 新增题目派生字段物化模块：答案、有效根、解析和语义验证元数据统一由
  题干契约与结构化参数生成。
- 组卷职责拆入 `app/harness/question_assembly.py`，`session_graph.py`
  只保留图节点编排、H1、批改与汇总路由。
- 题干语义契约：按 `design_id` 从题干提取结构化事实，并与 `a/b/c`
  双向校验；题干、方程、面积、乘积或根与系数关系冲突时拒绝进入 H1 题池，
  校验失败会返回预审页并保留当前会话。覆盖直接求解、多步化简、长方形面积、
  连续偶数、根与系数五种现有题型。
- 会话内自适应：根据最近一题或两题的程序证据更新目标难度，并从老师已审核的
  候选题中重排剩余题目；独立连续答对升级，答错降级，提示/脚手架后答对不升级。
- 证据加权掌握度：独立答对权重 1.0、提示后答对 0.5、脚手架后答对 0.25，
  加权结果同时进入会话汇总和画像建议，原始正确率继续保留用于展示。
- 老师等级修正：H3 确认页允许老师在 accept 前修正 weak/mid/strong，
  修正后的等级写入 mastery，并在老师决定记录中标记 `teacher_corrected`。
- 三级提示：学生可以在当前题逐级请求提示；提示只给方法、步骤和符号检查，
  不泄露最终答案；提交时记录 `hint_count`，并将掌握证据标记为 `hinted`。
- 双倍预审题池：实际题量固定时生成 2 倍候选题，难度比例保持一致，老师审核
  后系统从已审核池中按证据自适应选题；学生实际完成题量仍为原配置。
- 老师题干修改：H1 预审页支持编辑题干，修改后回到预审池继续确认，定稿使用
  修改后的题干。
- 老师改题重算：题干和 `a/b/c` 结构化参数一起提交，程序校验难度与可解性，
  重新计算答案、解析、有效根和作答模板；非法修改拒绝进入题池。
- 产品参考研究：新增 `PRODUCT_RESEARCH.md`，记录组卷产品、智适应产品和
  mastery learning 产品的公开机制，以及对 little-tutor 的采用原则。
- 学生即时程序反馈：提交单题后进入独立反馈页，只显示程序判分和程序断点；
  AI 归因仍留到会话结束后由老师确认。
- 老师确认页增加题级归因证据：显示题目、程序结果、程序断点和 AI 归因，
  学生端不展示该证据。
- 首次作答证据：`answer_records` 新增 `attempt_no`、`first_attempt_correct`、
  `hint_count`、`scaffold_level`、`assistance_level`，并提供旧 SQLite 文件
  自动补列与首次作答结果回填。
- V2 验收矩阵：记录真实 LLM accept/reject 闭环、会话隔离、恢复、正式库
  保护和尚未实现的即时反馈、证据、老师修正与角色入口。
- 学科扩展插件方针：区分 `SubjectPlugin`（单学科解析/求解/判分）、
  `TrainingPlugin`（单场训练的组题与报告策略）和 `IntegratedPlugin`
  （真正跨学科的求解链）。会话、证据、HITL、画像与持久化保持共享核心，
  不随学科复制。
- 全项目分层重构：代码按 `domain / harness / application / adapters / web`
  重新落位；领域模型与领域规则不再依赖 Web、数据库或 LangGraph。
  学生练习、老师审核、画像证据进入应用层；LLM、SQLite、checkpoint、
  题库和会话生命周期进入适配器层；Web 路由按学生/老师拆分。
  原根目录模块和 `run_mvp.py` 已移除，CLI 入口迁移为 `app.cli`。
- 练习会话生命周期：新增 `practice_sessions` 表与领域契约，区分真实、测试、
  完成、中断和老师审核状态；掌握度只读取真实、完成且已接受的会话，未完成、
  拒绝、测试、中断会话不再进入画像证据。已有真实会话已显式回填。
- 掌握度规则拆分为纯领域实现：`app/domain/mastery.py` 只处理会话率到等级、
  置信度和证据文案，`app/mastery.py` 保留持久化读取与兼容入口。
- 学生练习用例迁入应用层：`app/application/student_practice.py` 负责开始练习、
  组卷预审、作答、汇总和老师确认；`app/web.py` 只保留 HTTP、cookie、模板和
  跳转逻辑，不再直接访问数据库、会话图、checkpoint 或作答模板。
- 程序化题目设计器（`app/question_design.py`）：按题型结构生成直接求解、连续
  偶数、长方形面积、根与系数、多步化简题；参数必须通过“配方中间值整洁”
  质量闸门（`b/a` 为偶数、`c/a` 为整数、判别式完全平方），旧的无设计 AI 题
  不再进入组卷池。
- 题目模板按设计类型分流，不再所有题共用“先除以 a”：
  - 面积题先列“长如何表示”，再明确选择出的面积方程；
  - 连续偶数题先表示相邻数，再明确选择乘积方程；
  - 根与系数题先求两根和、积，再求根；
  - 多步化简题先找公因数；
  - 选择题正确项位置随题目变化，不再固定在第一项。
- 应用题不再强制提交两个根：面积题只以正根作为有效答案；模板通过
  `answer_blank_ids` 标记最终作答空位，Web 与 CLI 按该元数据拼装答案。
- 每个难度预生成并缓存 20 道唯一设计题，组卷汇合时再做一次去重，避免同一
  场会话重复出题。
- 题池按二次项系数 `a` 轮转抽取：中档覆盖 `2/3/4/5`，困难覆盖 `2~7`，
  避免 `a=2` 集中占用前几道题。
- P2 收尾（V2 完结）：
  - Send 扇出并发：组卷中缺库槽位用 LangGraph Send 并发运行题目设计器
    （generated reducer 累加，check_assemble 汇合拼装）；批改扇出与交互式
    逐题作答天然冲突，归入 P3 外环/考试模式（§16.1 决策⑤ exam 分支）
    重组引入 plan_id 轮次版本号，旧扇出产物自动失效，防误用
  - 批改子图：单题批改管线（判分→逐空断点→事实落库）编译为 compiled
    subgraph 挂入会话图，状态隔离、共享键读写
  - LLM 全局异常兜底：归因异常降级为"仅程序证据"（evidence_source=program，
    程序判分事实不丢）；组卷/换题/重组异常置 llm_error 走 failed 节点正常
    收束，CLI/Web 提示重试；并发 Send 失败 reducer 保首条错误
  - 新增 4 项测试（扇出补齐/失败收束/批改兜底×2），全量 102 → 106 项
- 简易 Web 演示版（V2 收尾）：`app/web.py`（FastAPI + Jinja2）三段式页面流
  对应会话级图三阶段——组卷预审（approve/swap/regroup 表单，swap/regroup
  自动回审）、模板填空作答（choice 点选 + expression 填空，答题完成后统一
  展示题级程序初评、断点与 AI 归因）、H3 批量画像确认；单学生、无登录、
  graph/checkpointer/thread_id 全复用，会话凭 cookie 续跑刷新不丢；
  Web 全流程测试（accept/reject 分流 + 落库断言，新增 2 项，全量 102 项）
- C 会话级图（§16.2 落地，结构重构）：新增 `app/session_graph.py`——
  `read_profile → generate_question_set（按掌握度混难度 + 挑库优先，种子题
  同难度随机、库缺程序化设计题补齐）→ H1 组卷预审(interrupt①：approve/swap:序号/
  regroup:意图，图循环回审直到定稿) → 单题循环×N（程序判分 + AI 归因 +
  逐空断点 + 事实当轮落库，零打断）→ summarize_profile（按 kp 聚合批量建议）
  → H3 批量确认(interrupt②：accept 写 mastery，reject 只留痕) → write_back；
  一次会话打断老师 ≤2 次；`run_mvp` 切换会话制 CLI；`generate_question`
  支持指定难度带；questions 表新增 `params` JSON 列（模板与程序算答案的
  单一事实源）；`session_rates` 排序改按会话内最新作答时间（§16.5 时间序）
- 会话级图测试（新增 7 项：组卷/H1 循环审批/换题回审/重组/单题落库/
  H3 accept 与 reject 分流），全量 93 → 100 项
- A 模板填空（设计停点拍板后落地）：`app/template.py` 按配方法套路程序生成
  作答模板（choice 依据点选 1 空 + expression 式子填空 5 空，LLM 不参与模板），
  `judge_blanks` 程序逐空判定（数值/分数/容差/序号），第一个错空即断点；
  `grade_node` 合并逐空结果与 `program_breakpoint` 程序证据，对错仍按最终
  作答判定；`run_mvp` CLI 逐步作答；schema 稳定层预留 blank 类型扩展位
  （多路径题走题库自带/LLM 起草+程序校验，V3 语义判定不碰）
- P2 持久化（第一步）：checkpointer 改为文件级 `SqliteSaver`
  （`checkpoints.db`，进程重启/内存清零后凭 thread_id 续跑老师审批），
  `build_tutor_graph` / `build_profile_graph` 开放 checkpointer 注入
  （测试注入 InMemorySaver 保持隔离）；新增跨图实例 resume 测试
  （暂停 → 全新连接 + 全新图实例 resume → 落库恰好一次）
- B3 正确率归因：`accuracy_by_difficulty` 按 `answer_records` JOIN
  `questions.difficulty` 聚合各难度正确率，支持 kp/学生/会话过滤（零 schema 变更）
- B1 掌握度规则（§16.5 落地）：新增 `app/mastery.py` 会话聚合计算——
  按 `session_id` 聚合单次会话正确率，strong 需最近两个会话均 ≥0.8，
  mid 需最近 ≥0.6，confidence 取最近会话率；`propose_profile_change`
  接入会话聚合（进行中作答先并入当前会话聚合），`apply_to_db`
  同步写 confidence 与 evidence；替换原"一题一档"逻辑
- B4 学生即时反馈：`run_mvp` 批改后当场打印程序初评对错（程序事实），
  归因与画像仍走老师终审
- 种子题库入册（§16.1 决策③）：`data/seed_questions.json` 9 题
  （simple×3 / mid×3 / hard×3，均带 params 与结构标记），`app/seeds.py`
  幂等加载——答案由程序按 params 计算，入库前按 B2 难度带校验，
  知识点缺失自动建卡；"出题优先挑库"的选库逻辑随会话级图（C）实现
- B2 难度参数化：难度参数约束表（simple：a=1 整数根；mid：2≤a≤5 有理根；
  hard：2≤a≤7 + 结构标记），`generate_question` 出题参数按难度带程序校验，
  违约带边界信息重试；hard 缺结构标记且系数落在 mid 带内自动降级为 mid
- Prompt 文件接线：出题与批改分别使用 `question_gen_v1.md` / `grader_v1.md`，
  并按任务拆分 temperature（出题 0.7，归因 0）
- 出题 prompt 内容升 v2：写入难度带约束、判别式完全平方要求与
  `structure_tag` 结构标记字段（建模/根与系数/多步化简）
- 难度带校验、正确率归因、掌握度规则、种子题库测试（新增 32 项，全量 81 项）
- Prompt 接线与难度/掌握度词汇分域的基础设施测试（新增 7 项）
- CI 门禁：GitHub Actions 在 push/PR 时运行全量离线测试（Python 3.12 + unittest）

### Removed

- 将本仓库的维护说明改为本地文件，不再随仓库发布

### Changed

- B0 词汇表统一：新增独立 `DifficultyLevel` 类型，`Question.difficulty` 与
  题目表默认值对齐 `simple/mid/hard`，掌握度 `Level` 不再复用为题目难度
- 测试目录工程化：课程练习命名的 `test_l5_l6.py` 更名 `test_hitl_flow.py`（内容为
  HITL 守护/路由/落库分流的项目测试）
- `get_llm` 加 `lru_cache` 单实例缓存，图节点不再重复构建 LLM 客户端
- `requirements.txt` 拆分：V1 核心依赖 + pytest 入册；V2/V3 重依赖
  （chroma/sentence-transformers/fastapi 等）注释待启用，装包不再带未用组件

### Fixed

- 种子题全量盘查（用户第二次实测）：5 道题的"生活情境"为凑数框架
  （"成本满足方程"等现实逻辑不成立），改写为诚实的计算练习框架并同步
  题库；"根与系数"种子题的题干指引与固定配方作答模板冲突，一并修正；
  新增种子文件全量审计测试（难度带 + 根复算 + 题干唯一），全量 106 → 107 项
- 种子题情境与负根矛盾（用户实测发现）：4 道题的"生活情境"预设了正数约束
  （正整数/宽度/速度/面积）而方程两根含负值，老师审题时误以为程序算错；
  情境改写为两根均合法的框架并修正陈旧 analysis；应用题"舍根"的答案取舍
  模型归入 V3 判分表示升级范围
- 连续下标变量标签（如 `x₁₂`）在数值提取时整体剥除，避免残留数字污染
  数值根集合

### Documented

- 难度结构分层缺口（2026-09-10 用户实测）：当前三档难度只体现在系数与根的
  形态，作答结构共用同一套六空配方模板；hard 的结构标记未驱动模板差异。
  已记入 SPEC §15 差异账，规划模板按结构标记分型（建模/根与系数/多步化简）
- 全面对照审计（2026-09-09）：§16.3 设计稿契约同步实现（DifficultyLevel 分域、
  模板填空 Blank/QuestionTemplate/BlankResult、program_breakpoint/blank_results）；
  差异记账补 4 条漏账（profiles 表零写入与三层画像未实现、teacher_decision.target
  缺失、题库文件层未建、hint_given/used_seconds/images 等字段尾巴）；
  §14 已拍板清单加口径说明（✅ = 设计定稿 ≠ 已实现）；
  C 会话级图实施注记（节点全口径、求助随 P3、题量默认 10 可配置、
  schema 尾巴随 C 落库链路定稿）
- 路线调整（2026-09-09 定）：简易 Web 演示版（FastAPI + Jinja2，出题/答题/
  审批三页面，单学生无登录）纳入 V2 收尾，排会话级图（C）之后、
  P3 产品化之前——页面流跟着会话流程走，避免先 Web 后 C 返工
- 复核 V2 执行顺序：Prompt 前置 → B0 词汇表统一 → B2 难度参数化 → B3 正确率
  归因 → B1 掌握度规则 → B4 学生即时反馈 → 种子题库 → A 模板填空 → C 会话级图
  → P2 持久化/并发 → P3 Web；同步刷新项目文档中的测试数量口径
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
- 外部评审核实后补记账 §15 五项实现与设计差异（掌握度规则未实现 /
  难度非受控变量 / H1 缺失与高频打断 / Grader 无过程证据 / 温度共享），
  并定案改进路线：掌握度规则 + 难度参数化 → 模板填空 → 会话级图重构，
  家长会话简报与学生即时反馈进 V2 路线
- 三方评审统合落账：§15 差异记账补 prompt 文件债与难度词汇表三套并存；
  改进路线加 B0（DifficultyLevel 独立类型）与 B3 改 JOIN 归因（零 schema）；
  §10.4/§13.4 知识卡口径改 V3；§13.9/§13.5 降级条目逐条加触发条件；
  §16.1④ 改题 A/B 降级（触发=真实使用信号）、§8.5 求助机制随 P3；
  README 路线表拆注 V1 还债项与真 V2 产品项

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
