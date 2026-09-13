# little-tutor 产品参考研究

更新时间：2026-09-13

本文件只记录产品结构、交互模式和机制参考，不复制第三方题库内容。

## 组卷类产品

参考：

- 组卷网：<https://zujuan.xkw.com/>
- 知识点选题：<https://zujuan.xkw.com/zhishidian/>
- 新教育试题篮帮助：<https://hc.xinjiaoyu.com/Q-selection/select/zujuan>
- 园丁邦改编题目帮助：<https://yuandingbang.cn/help/content?id=150>
- 数苑网试卷修改帮助：<https://sciyard.com/chs/help/?subtype=1&hid=263&pid=30&tid=79>

共同模式：

```text
多维筛选
→ 试题篮
→ 查看答案和解析
→ 添加类题/相似题
→ 改编题目
→ 调整顺序/分值
→ 生成并下载试卷
```

关键结论：

- 题库母题通常通过“纠错”上报，不直接修改全站共享题。
- 老师真正编辑的是本次组卷的副本。
- 改编后可调整题干、选项、分值、顺序和删除状态。
- 最终仍可能需要下载 Word 做二次编辑。

## 智适应学习产品

参考：

- 松鼠 AI 产品资料：<https://songshuai.com/products>
- 松鼠 AI 公开介绍：<https://www.ebingou.cn/gongju/19510.html>

共同模式：

```text
知识点拆解
→ 智能诊断
→ 知识图谱
→ 动态学习路径
→ 虚拟教师互动
→ 持续反馈
```

关键结论：

- 自适应能力依赖细粒度知识点和前置关系。
- 推荐不是只调题目难度，还会沿知识点路径回退或前进。
- 学生长期状态和即时学习路径都是产品核心。

## Mastery Learning 产品

参考：

- Khan Academy Mastery levels：
  <https://support.khanacademy.org/hc/en-us/articles/5548760867853--How-do-Khan-Academy-s-Mastery-levels-work>
- Khan Academy Mastery Learning：
  <https://khanacademy.org/khan-for-educators/khan-for-educators-advanced-course/x2e5750eab575b791:khan-for-educators-advanced/x2e5750eab575b791:mastery-learning-on-khan-academy/a/mastery-learning-on-khan-academy>

共同模式：

```text
技能练习
→ 熟练度状态
→ 课程/单元掌握度
→ 继续推荐
→ 学习进度可视化
```

关键结论：

- mastery 是持续状态，不是一次答题结果。
- 学生、老师和学校需要看到不同粒度的掌握度。
- 学习报告和下一步建议属于核心体验，不是附属页面。

## little-tutor 的采用原则

1. 学生端采用自适应学习产品的持续练习、反馈、提示和 mastery 体验。
2. 老师端采用组卷产品的题池、改编、替换和批量确认能力。
3. 程序负责事实，AI 负责归因，老师负责结论，保持 HITL 差异化。
4. 老师修改的是会话题目副本，不直接修改公共母题。
5. 修订题干和参数后，由程序重新计算答案、解析和作答模板。
6. 知识点关系和长期掌握趋势后续必须补齐。

## 暂不照搬

- 大规模题库商城和资源权限体系。
- 完整试卷排版、细目表和 Word 导出平台。
- 相似题推荐和热度排序。
- 纯自动无缝推进；本项目仍保留老师终审。
