# little-tutor 架构约定

本文件定义后续代码的结构标准。产品设计以 `PROJECT_SPEC.md` 为准，本文件只约束
分层、依赖方向和职责边界。

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

## 当前完成状态

1. Web 已拆为学生路由、老师路由、视图模型。
2. 学生练习、老师审核、画像证据已进入应用层。
3. LLM、持久化、checkpoint、题库、会话归档已进入适配器层。
4. 数学规则、模板、题型、领域模型已进入领域层。
5. LangGraph 状态与会话级图已进入 Harness 层。
6. 旧根目录实现模块已删除，当前只保留 `cli.py` 和 `runtime.py`。
7. 组卷与候选物化已拆入 `harness/question_assembly.py`。
8. 会话写并发由数据库租约控制，不再依赖单进程内存锁。

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

Submission
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
| `domain/models.py::StudentStep` | 只有 `basis/result` | 保留旧契约并新增 `StudentStepV2`、`TransitionCheck`、`Submission` | 先并存，不破坏旧调用 |
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

## 后续工作

1. 落过程诊断契约和一元二次方程转换校验器。
2. 接入首次作答、提示次数和受助程度。
3. 让老师审核支持修正等级、错因和测试标记。
4. 将会话状态、证据等级和掌握度置信度继续规则化。
5. 评估旧串图 `harness/legacy_graph.py` 是否退役。

未决设计问题记录在 `ARCHITECTURE_QUESTIONS.md`。
