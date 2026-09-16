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

当前私有中考探针已经扩展到 33 道，其中 24 道为中考真题，8 道为中考模拟/专题题，
1 道为经典中考题型。

离线多题型求解模块已完成第一刀：

- `14/14` 道真实/专题题达到 `solver_verified`；
- 覆盖增长率、判别式选择、方程还原、参数根、整体代换和根式一元二次方程；
- 使用程序建方程和 SymPy 求解，不依赖 LLM 算答案；
- 但每个题型的样本量都未达到 15 道，因此只能是探索性切片，不能宣称已覆盖；
- 但尚未接入现有组卷、学生作答和画像主链路，因此当前产品端可运行数量仍为 0。
