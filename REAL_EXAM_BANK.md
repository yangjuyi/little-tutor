# 真实题题库与验收规则

本文件定义 little-tutor 接入中考真题时的数据契约和能力验收标准。

## 核心原则

1. **真实题只负责验收，AI 生成题只负责训练和压力测试。**
2. 中考能力结论只能由真实题集得出，不能用程序生成题替代。
3. AI 生成题必须能追溯到真实父题或明确标注为 synthetic，不能混入真实题统计。
4. 没有真实题支撑的题型，不得在文档或简历中宣称“已支持中考能力”。

## 数据来源

能称为真实题的数据必须满足：

- 标注年份；
- 标注地区或考试名称；
- 保留来源链接或来源文档；
- 保留原题干、参考答案或参考解析；
- 不允许只有题干、没有答案来源；
- 图片题必须标记 `requires_image=true`。

模拟题和专题题可以加入题库，但必须标记为 `exam_style`，不能与
`real_exam` 混合统计。

## 建议字段

```text
RealExamQuestion
  id
  source_type          # real_exam / exam_style / classic_exam_style
  source_url
  year
  province
  stem
  answer
  reference_solution
  tested_skills
  capability_tags
  requires_image
  current_support
  review_status
```

## 能力状态

```text
imported
  -> structured
  -> solver_verified
  -> answer_verified
  -> process_supported
  -> accepted
```

只有 `accepted` 才能计入中考覆盖率。

## 样本量底线

单个题型低于 `15` 道真实题或中考专题题时，只能标记为探索性切片，
不得称为“已覆盖”或“已验证”。

```text
样本量 < 15       insufficient_sample
样本量 >= 15     具备进入能力验收的资格
```

达到 15 道后还必须通过 solver、答案、过程诊断和主链路四层验收，才算真正支持。

## 接入顺序

1. 导入真实题并保留来源。
2. 按能力矩阵聚类，不按题号逐题写死。
3. 为每类题实现结构化 spec、程序求解和有效解筛选。
4. 用真实题验证答案。
5. 再接过程诊断和老师预审。
6. 最后才允许 AI 基于真实父题生成变式。

## 验收与评测

评测报告必须分开：

- `real_exam_acceptance`：真实题通过率，能力声明只认这一项；
- `generated_regression`：AI 生成题的回归和压力测试；
- `teacher_assisted`：需要老师介入才能完成的题目；
- `unsupported`：当前系统不能处理，必须明确记录缺口。

当前私有中考探针已经扩展到 49 道，其中 30 道为中考真题，16 道为中考模拟/专题题，
3 道为经典中考题型。

离线多题型求解模块已完成第一刀：

- `20` 道真实/专题题达到 `solver_verified`；
- 覆盖增长率、判别式选择、方程还原、参数根、整体代换和根式一元二次方程；
- 使用程序建方程和 SymPy 求解，不依赖 LLM 算答案；
- 增长率 / 降价率已经达到 15 道，并完成结构化求解、程序判分和主链路验收；
- 判别式选择题已注册第二个 `QuestionHandler`，当前 1 道真实题通过
  handler 路径验收；距离 15 道样本门槛仍有缺口，不能宣称已覆盖；
- 其余主题型尚未完成主链路能力验收；利润/销售和面积/几何已有 15 道样本，
  但缺 solver、结构化作答和主链路验收，仍不能宣称已覆盖。

增长率 / 降价率主链路验收：

- `15/15` 通过 `solver_verified`；
- `15/15` 通过正确答案接受与错误答案拒绝；
- 其中 2 道完整 `(1)(2)` 题目接入子问题机制；
- H1 预审、原题型作答、程序判分、最终判定和画像会话流程可运行；
- 真实 LLM `accept/correct` 与 `reject/wrong` 冒烟通过。

后续扩展不再按单题写分支，统一走 `QuestionHandler`：

```text
新题型家族
  → handler + spec + solver + response schema
  → 真实题样本
  → 程序判分 / 主链路 / 评测
```

当前已注册通用 response element：`choice`、`numeric/expression`、
`symbolic/equation`。`Subquestion / Submission / Evaluation` 和逐子问题
老师确认已接入；下一阶段继续扩第二批题型家族、部分分策略和更多真实题验收。

## 第一试卷网私有镜像

2026-09-17 对 `https://www.shijuan1.com/` 的六个数理化分类页建立了完整题录索引：

- 扫描结果：`8232` 条；
- `2016-2026` 下载队列：`5370` 条；
- 年份不在范围内的条目：`2862` 条，状态为 `year_filtered`；
- 分类：初中数学、高中数学、初中物理、高中物理、初中化学、高中化学；
- 题录字段：标题、年份、地区、考试类型、发布日期、文章 URL、下载状态和错误信息；
- 原始压缩包：`outputs/private_sources/shijuan1/`；
- 解包文档：`data/private_questions/shijuan1/`；
- 清单：`data/private_questions/shijuan1/manifest.json`。

采集器支持断点续传、失败重试、年份过滤、并发下载和压缩包解包：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\collect_shijuan1.py `
  --delay 0.05 --workers 8
```

仅更新分类页题录、不下载文件：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\collect_shijuan1.py `
  --index-only --delay 0.1
```

私有镜像状态只代表“已发现”或“已下载”，不代表系统已经支持解析和作答。
图片题、缺答案题和未通过 solver 的题，仍必须按本文的能力状态逐层验收。

## 私有语料审计与录入队列

使用本地审计器逐份读取已下载 DOCX，按题号和关键词切块、去重并分类：

```powershell
.\.venv\Scripts\python.exe -X utf8 evals\audit_shijuan1_corpus.py `
  --per-family 40
```

2026-09-17 快照：

- 已下载题录：`1027`；
- 去重候选题块：`1988`；
- 首批候选队列：`280`；
- 候选中包含图片依赖 `1321`、含答案标记 `966`、多问题 `746`。

2026-09-19 采集状态补注：

- 已下载题录：`3173`；
- 待重试：`676`；
- 失败记录：`1521`，其中绝大多数为站点读取超时；
- 失败记录保留在 manifest 中，下一次断点续传会自动重试。

首批应该进入结构化整理的候选：

| 题型 | 候选量 | 首轮目标 |
|---|---:|---:|
| 利润 / 销售 | 184 | 30 |
| 判别式 / 参数范围 | 224 | 30 |
| 根与系数 | 105 | 15-30 |
| 整体代换 | 67 | 15 |
| 增长率 / 下降率 | 52 | 再补 15 |
| 面积 / 几何建模 | 1312 | 20 道文本型探针 |
| 动点 / 动态几何 | 121 | 10-20 道探针 |

录入规则：

1. 候选块先进入 `candidate`，不能直接写入正式题库。
2. 逐题补题干、子问题、标准答案、来源和图片依赖。
3. 答案能由程序独立求出的题进入 solver 验证。
4. 只有通过答案、过程诊断和主链路验收的题，才标记为 `accepted`。
5. 几何和动点题不会被“数量多”反过来绑架首批范围；它们只用于验证
   后续几何模型和视觉输入缺口。
