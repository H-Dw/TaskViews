# TaskViews-mini 复核引用类型修复 v3

2026-10-24，r005 的 invoice/legacy/low 在第34次决策连续得到 missing_tag、missing_tag、report_fields，最后四项观察编号使用 JSON 字符串。原成功动作被阻断，官方成绩为 null，资源与执行时源码校验正常。

源码溯源发现 `mini_recovery.report_feedback` 的正式模板使用带引号的 `OBS_SEQ`。按字面替换占位符后仍是字符串，与 `artifact_view.validate_review` 的正整数要求不一致。此问题已通过真实校验器复现；这只能证明提示类型存在缺陷，不能证明全部模型失败都由它引起。

`mini-review-feedback-v3` 的模板改为不带引号的 `OBS_SEQ`，同时明确要求无引号的正 JSON 整数。实际编号和可见事实仍由模型根据同任务观察填写。严格校验、两次纠错、时间和token预算、证据等级及官方动作编译保持不变；不将字符串编号自动转换为整数。

第6次候选验证250通过、6失败，失败原因是新增集成测试误取错误说明中的省略号示例；已按失败计入账本。第7次候选只修正测试选择正式模板的范围，最终256项回归和Ruff全部通过，54个原运行器模拟场景与8个媒体评分接入场景也全部通过。

验证证明位于实验根目录 `repairs/r007-ref-template/validation.json`，绑定当前project_source；原始缺陷证据位于 `incidents/20261024T0455-review-ref-template/evidence.json`。模拟检查不是benchmark成绩，不证明任务成功率提升。

相对r005冻结计划仍存在共享actor变更，invoice、GIMP、VLC全部受影响，需要重新冻结18格。r005第01格有效官方分数0原样保留，异常第02格保持null，另外16格未启动。归档报告在 `revisions/r005/report-before-r007`，索引在 `prior-version-results-r007.json`，并指向更早版本的独立索引。不同版本不混算总体结果。

18格已全部冻结为 `revisions/r007/queue.json`。新的两套provider和六套定位诊断完成，共30次真实请求，输入118,022、输出44,143 tokens，金额未知；用量与正式任务分开记录。定位诊断保留未命中结果，不作为benchmark成绩。

最终check确认18格就绪且资源达标。2026-10-24 06:19:52（北京时间）唯一串行服务启动成功，随后核对了PID、start_ticks、boot_id、queue哈希及源码身份，证据见 `repairs/r007-ref-template/activation.json`。40分钟heartbeat保持ACTIVE，累计修复7/10；正式实验由后台运行器串行推进。
