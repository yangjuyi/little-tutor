# little-tutor 架构约定

本文件定义后续代码的结构标准。产品设计以 `PROJECT_SPEC.md` 为准，本文件只约束
分层、依赖方向和职责边界。

本文件不维护当前能力、测试数字、真实题样本、Eval 结果和版本优先级。
当前状态见 `CAPABILITY_STATUS.md`，路线见 `ROADMAP.md`，决策理由见
`docs/adr/`，验证流程见 `VERIFICATION_PLAYBOOK.md`。

## 定位

little-tutor 是面向一对一教学的智能教学系统：

- 教学领域模型是核心；
- Harness 负责控制 Agent 的流程、反馈、重试、记忆和老师介入；
- 应用层负责学生、老师的一次完整用例；
- 体验层按角色提供学生空间与老师工作台；
- 模型、数据库、checkpoint、OCR 等具体技术放在适配器层。

Harness 不是最外层皮肤，而是中间控制层。内部状态不能直接暴露给学生或老师。

## 当前分层

```text
app/
  domain/          # 判分、题型、模板、掌握度、会话与证据契约
  harness/         # LangGraph 编排、组卷、Agent 状态、旧版兼容图
  application/     # 学生练习、老师审核、画像证据、会话报告
  adapters/        # LLM、SQLAlchemy、checkpoint、题库、会话存储
  web/             # 学生路由、老师路由、视图模型
  templates/       # 学生端与老师端页面
  cli.py           # 会话制命令行入口
```

## 依赖方向

```text
web -> application -> domain
                  -> harness -> domain
                  -> adapters
```

- `domain` 不依赖 Web、LangGraph、SQLAlchemy。
- `harness` 可以调用 `domain` 和适配器接口，不生成页面。
- `application` 组织一次完整用例，不处理 HTTP 细节。
- `web` 只调用 `application`，不直接读 checkpoint、ORM 或图状态。
- `adapters` 实现外部技术接入，不决定教学策略。

## 硬规则

1. 学生端不能出现 `thread_id`、`session_id`、H1/H3、interrupt 等内部概念。
2. 老师端只呈现决策所需事实、证据、异常和结果。
3. 答题事实、会话结果、老师确认后的画像证据必须分离。
4. 测试、冒烟和评测只能使用隔离运行目录，禁止写生产数据库。
5. 模型调用必须经过模型适配器，不在业务模块写死供应商。
6. 过程反馈、最终判定、画像更新分别记录，不能混成一个 `is_correct`。
7. 结构化题目必须通过题型语义契约：题干事实与参数冲突时不得进入已审核题池，
   校验失败必须回到审核状态，不能破坏 H1 会话。
8. 题目答案、有效根、解析和作答模板只能由题干契约与结构化参数派生，数据库
   不可作为第二事实源。
9. 学生路由不得自动进入老师审核流程；老师入口必须独立并在部署时启用访问控制。
10. 同一会话的写操作必须持有数据库租约，不能依赖进程内锁或单 worker 假设。
11. 中考能力验收必须使用带年份、地区、来源和答案的真实题；AI 生成题不得
    计入真实题通过率，且变式题必须能追溯到真实父题。

## 结构落地记录

以下内容只用于说明分层已经如何落地，不作为当前能力状态源。当前能力状态见
`CAPABILITY_STATUS.md`。

1. Web 已拆为学生路由、老师路由、视图模型。
2. 学生练习、老师审核、画像证据已进入应用层。
3. LLM、持久化、checkpoint、题库、会话归档已进入适配器层。
4. 数学规则、模板、题型、领域模型已进入领域层。
5. LangGraph 状态与会话级图已进入 Harness 层。
6. 旧根目录实现模块已删除，当前只保留 `cli.py` 和 `runtime.py`。
7. 组卷与候选物化已拆入 `harness/question_assembly.py`。
8. 会话写并发由数据库租约控制，不再依赖单进程内存锁。
9. 结构化真实题通过 `domain/exam` 题型契约接入判分、组卷和 H1；当前增长率
   / 降价率完成 15 道主链路验收，普通配方法仍走原模板填空路径。
10. 新增 `domain/assessment` 题型 handler 注册表；核心物化、模板、判分和 LLM
    适配通过注册表分派，增长率成为第一个独立 handler，不再由核心层判断
    `question_type` 细节。
11. 新增通用作答元素注册：`choice`、`numeric/expression`、`symbolic/equation`
    由独立元素判定器负责；模板逐空判定通过元素注册表统一执行。
12. Subquestion 结果已可聚合、持久化和逐子问题老师确认；2024 西藏和 2025
    岳麓模拟两道真实 `(1)(2)` 题目已接入数据、模板和 UI，下一步扩更多家族。
13. `domain/exam/main_chain.py` 已从“增长题专用”收口为通用结构化题型入口：
    判别式选择、方程重构、参数根、整体代换和符号根均能完成物化与程序判分。
14. 最终答案判分按带标签根做严格集合比较，能够拒绝多写错误根，同时保留
    题干过程数字不参与最终根判断。
15. 私有试卷采集器增加单实例文件锁和进程唯一临时清单，避免两个采集进程
    覆盖同一 manifest；PID 文件由采集器自身维护。
16. 新增双会话自适应验收：第一次会话的老师确认结果会改变数据库画像，第二次
    会话读取新画像后，预审题池的难度配比和目标难度确实发生变化。
17. 注册判别式选择题 handler，成为第二个真实题型家族；真实题验收同时验证
    handler 物化与判分路径，不再只验证底层 solver。

## 过程诊断契约（2026-09-14 定）

当前 `StudentStep = basis + result` 和 `answer_template` 的逐空判定只能定位
“哪个空填错”，不能定位“哪一次步骤转换不成立”。后续过程诊断以步骤转换，
而不是空位填写，作为最小判定单位。

目标契约：

```text
StudentStepV2
  step_no
  raw_latex
  operation
  source
  confidence

TransitionCheck
  from_step
  to_step
  is_valid
  rule
  error_type
  evidence
  confidence
  insufficient_evidence

ProcessSubmission
  mode              # final_answer_only / step_by_step
  steps
  final_answer
```

诊断规则：

1. `final_answer_only` 只判定最终答案事实。
2. `step_by_step` 同时检查每次相邻步骤转换；首次不成立的转换成为程序断点。
3. 步骤缺失时只能返回“证据不足/无法判断”，不能补造学生没写出的过程。
4. 过程反馈、最终判定和画像证据分别记录；错误转换不能通过覆盖
   `is_correct` 的方式偷写画像。
5. 一元二次方程作为首个垂直切片，后续题型按题型注册转换校验器。

## 重构映射

| 当前文件/职责 | 当前问题 | 目标职责 | 迁移方式 |
|---|---|---|---|
| `domain/models.py::StudentStep` | 只有 `basis/result` | 保留旧契约并新增 `StudentStepV2`、`TransitionCheck`、`ProcessSubmission` | 先并存，不破坏旧调用 |
| `domain/answer_template.py` | 同时生成模板和执行判定 | 降级为 legacy 输入适配器 | 新过程诊断稳定后再迁入 legacy |
| `application/student_practice.py::_build_student_steps` | 表单空位直接拼学生步骤 | 输入适配器 + 应用服务 | 拆成 `final_answer_only` 和 `step_by_step` 两条组装路径 |
| `harness/session_graph.py::_grade_compute_node` | 只调用 `judge_blanks` | 调用过程诊断并合并最终判定 | 先旁路接入，旧路径保留为回退 |
| 新增 `domain/process_diagnosis.py` | 不存在 | 相邻步骤转换校验、首个断点和证据 | 一元二次方程先落地 |
| `domain/grading.py` | 只负责答案事实 | 继续作为程序真值源 | 不把过程策略塞回这里 |
| `templates/answer.html` | 固定空位表单 | 后续改为步骤卡片输入 | 前端最后动，后端契约先行 |
| `harness/legacy_graph.py` | 旧串图调试路径 | 确认无引用后退役 | 等新路径全绿再删 |

迁移顺序固定为：

1. 新增契约和 `process_diagnosis.py`，只加测试，不接业务。
2. 在应用层新增 `diagnose_submission`，同时返回最终判定和转换检查。
3. `session_graph` 旁路接入新诊断，旧 `judge_blanks` 保留为兼容回退。
4. `student_practice` 支持两种 Submission 模式，模板仅作为一种输入适配器。
5. 前端改步骤卡片，不引入画布；拍照输入仍后置。
6. 全量测试、accept/reject、correct/wrong 端到端全部通过后，再退役旧模板主路径。

## 学科与训练插件

V3 起新增学科能力时，不把物理、化学规则塞进数学实现，也不建立一个包办一切的
“综合插件”。插件分成三类：

1. `SubjectPlugin`：单个学科的题面解析、答案 schema、单位规则、求解器、
   判分器和证据分级。
2. `TrainingPlugin`：一次训练的知识点、学科配比、难度、题型、提示策略和报告
   维度。
3. `IntegratedPlugin`：一道真正跨学科题目的组合求解链，例如物理描述 + 数学
   方程求解 + 物理单位校验。

共享核心永远保留以下能力，不交给学科插件重写：

- 会话生命周期、checkpoint、持久化；
- 作答事实、证据分级、掌握度和置信度；
- Harness 编排、老师介入和画像更新；
- 测试隔离、权限和运行环境。

建议目标目录：

```text
app/domain/plugins/
  contracts.py
  registry.py
  subjects/
    math/
    physics/
    chemistry/
  training/
    math_drill.py
    science_mixed.py
    diagnostic.py
  integrated/
    physics_math.py
    chemistry_math.py
```

插件只扩展领域能力，不重写 Harness 和业务闭环。

## 综合题扩展机制（2026-09-17 定）

“题型家族”和“拓展机制”必须分开：

- **题型家族**是业务内容，例如增长率、利润、二次函数、电路、化学方程式；
- **拓展机制**是平台接口，例如 QuestionHandler、Subquestion、
  ResponseElement、Evaluation、老师逐子问题确认；
- 作答形式（选择、填空、方程、多步步骤）属于通用机制，不属于某个题型家族。

新增题型家族时只允许新增：

```text
domain/assessment/handlers/<family>.py
spec / schema / solver / validator / tests
真实题数据与评测用例
```

不得在核心层新增：

```text
if question_type == "..."
```

只有两个以上题型会共同使用的能力，才允许提升为通用机制，并必须补全量回归。

当前分层：

```text
QuestionHandler
  supports()
  materialize()
  supports_template()
  build_template()
  check_answer()
  question_roots()

ResponseElement
  choice
  numeric / expression
  symbolic / equation
```

当前已落地的综合题契约：

```text
SubquestionSpec
Submission
EvaluationPart
Evaluation
```

新的多步解答题先拆成子问题：

```text
第(1)问：列方程或求数值
第(2)问：继续计算
第(3)问：说明理由或筛选有效解
```

程序只判可计算节点；rubric 和开放理由交给 AI 提取证据、老师终审。最终结论
继续遵守三层分离：程序初评事实、AI 归因证据、老师确认后的有效结论。

批改链路的实现边界同样遵守这一原则：

```text
validate_input
→ compute_program_grade
→ attribute_error / attribution_fallback
→ merge_grade_result
→ record_fact
```

`compute_program_grade` 不调用 LLM，负责最终答案、过程断点和逐空事实；
`attribute_error` 只输出建议性错因字段，不拥有 `is_correct`。归因模型异常时，
`attribution_fallback` 将结果降级为 `evidence_source=program`，程序事实仍可
继续落库并进入老师确认。

## 真实题语料审计与架构改动（2026-09-17）

对第一试卷网已下载的初中数学语料完成一次全量粗切审计：

```text
已下载题录       1027
去重候选题块     1988
首批候选队列     280
```

审计产物在本地忽略目录：

```text
outputs/private_sources/shijuan1/corpus_audit.json
outputs/private_sources/shijuan1/corpus_audit.md
outputs/private_sources/shijuan1/intake_shortlist.json
```

候选只代表文本和关键词层面可抽，不代表答案正确或已经支持。录入顺序固定为：

```text
candidate -> curated -> structured -> solver_verified
-> answer_verified -> process_supported -> accepted
```

### 首批录入范围

| 题型家族 | 审计候选 | 首批录入建议 | 架构动作 |
|---|---:|---:|---|
| 增长率 / 下降率 | 52 | 再录 15 道，现有 15 道保留 | 扩展现有 handler 的周期、方向和反求类型 |
| 利润 / 销售 | 184 | 录 30 道 | 新增独立 handler、solver 和子问题 schema |
| 判别式 / 参数范围 | 224 | 录 30 道 | 新增符号约束和参数范围判定 |
| 根与系数 | 105 | 录 15-30 道 | 复用符号等价，新增根关系 solver |
| 整体代换 | 67 | 录 15 道 | 复用符号等价，新增目标表达式求值 |
| 面积 / 几何建模 | 1312 | 只留 20 道文本型探针 | 不进入首批 handler，先验证几何参数契约 |
| 动点 / 动态几何 | 121 | 只留 10-20 道探针 | 后置到图形模型和视觉输入阶段 |

物化、高中和其余四科当前各只有少量下载，不进入本轮录入。它们只能作为
将来 `SubjectPlugin` 的边界探针，不能据此声称学科支持。

### 语料触发的契约改动

1. `QuestionHandler` 继续保持领域插件边界，但需增加题型元数据，而不是在核心层
   新增 `question_type` 分支：

```text
handler.kind
handler.capabilities
handler.response_schema
handler.requires_media
handler.source_policy
```

2. `Subquestion` / `Submission` / `Evaluation` 保持通用。首批候选中多步题占比
   较高，不能为利润或增长率各写一套子问题机制。

3. 新增题库 intake 契约，生产数据与派生结论继续解绑：

```text
source_article_id
source_url
year / region / exam_type
dedupe_hash
parse_status
media_requirements
review_status
structured_questions
```

4. 几何题只先增加“媒体依赖”标记和探针题，不提前把图形结构、OCR 或视觉模型
   塞进核心判分链。只有文本几何契约稳定后，才允许提升为几何领域模型。

5. 学科插件边界暂时不变。现有语料不足以证明物理、化学需要哪类共享契约；
   在没有各科真实题和独立验收前，不新增“综合大插件”。

本轮架构修改只影响领域契约、handler 元数据和题库 intake；Harness、应用层、
Web 和数据库结构暂不因这批语料提前重构。

## 架构迁移顺序

以下只描述架构迁移顺序，优先级和排期见 `ROADMAP.md`。

1. 将已实现的过程诊断接入主链路，旧 `judge_blanks` 保留兼容回退。
2. 继续规则化会话状态、证据等级和掌握度置信度。
3. 扩展真实多步题型、部分分策略和更多题型 handler。
4. 评估旧串图 `harness/legacy_graph.py` 是否退役。

未决设计问题记录在 `ARCHITECTURE_QUESTIONS.md`。
