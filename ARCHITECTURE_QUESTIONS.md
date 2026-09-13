# little-tutor 架构待确认问题

本文件记录模块化过程中需要后续拍板的问题，不阻塞当前重构。

## 数据约束

1. `practice_sessions.status` 和 `review_status` 目前由应用层校验，
   是否需要在 SQLite 层增加 CHECK 约束？
2. `AnswerRecord.session_id` 目前没有外键到 `practice_sessions`，
   是否在三表稳定后补外键和索引？

## 旧流程

3. `app/harness/legacy_graph.py` 与 `app/harness/profile_graph.py` 是否继续
   作为调试路径，还是只保留会话级图？

## 会话与证据

4. `aborted` 是否要区分“用户主动退出”“系统异常”“组卷失败”？
5. 脚手架等级是否需要独立事件表，还是继续扩展 `answer_records`？
6. 多知识点会话如何表达？当前 `practice_sessions` 只有一个 `kp_id`。
7. 老师修正等级、错因、测试标记后，原 AI 建议如何保留版本链？

## 运行时

8. 会话写并发已改为数据库租约；`student_practice.py` 仍持有进程级编译图。
   是否继续拆成 runtime container / dependency injection，便于测试替换和
   多运行时装配？
9. `data_source=real/demo/test` 的写入入口是否需要显式配置，
   而不是依赖调用方传值？
10. 当前已实现 2 倍预审题池，自适应仍只能从已审核池选题。后续是否对结构稳定的
    程序化题型引入“预审出题策略/模板”，允许实时生成新的高难度题？
11. “连续两次独立答对升级、最近答错降级”目前是固定规则，是否需要按学段、
    知识点或学生画像配置阈值？
