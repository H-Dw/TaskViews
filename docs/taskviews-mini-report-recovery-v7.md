# TaskViews-mini v7：辅助报告恢复与输入重新准入

2026-10-18，`mini_report_recovery_v7`／`mini_artifact_review_v3`。仅改进 Mini，不修改官方 OSWorld 执行／评分、共同 baseline actor、传输、原生历史或 CUA 预算。本次只做离线代码验证，不提交、不启动或恢复线上 episode。

v4 的两次报告拒绝使必需原生文本达到 43,936 字符；v6 一次格式拒绝后达到 40,454 字符。两者都在本地 32,000 字符保护处停止。v6 改善了提示，但没有改变完整被拒回复和长推理进入同轮修复请求的机制。

## 错误分流

Mini 的成功候选仍需公开复核来源、内容、名称和目标目录，并校验真实同任务 observation 引用及当前帧内容预览。格式／引用失败保持独立 `ReviewError`，不再转换成原生工具 `StreamProtocolError`。

Mini 自己的有界候选循环对辅助报告错误只追加简短的字段／格式反馈。原始回复仍在 transport 遥测中；请求不回填被拒 assistant 消息、推理或工具调用，也不伪造 tool 收据。被拒 assistant／tool 整对不进入新输入，因此不会产生悬空工具 ID。原终止动作不执行，模型可重新给出报告与原生调用，也可继续观察。

真正的原生工具错误继续使用原 `repair_messages`，保留完整 assistant（包括 reasoning）和原 tool IDs 的错误回执。两类错误分别记为 `mini_report_rejected/mini_report_regeneration` 与 `candidate_rejected/semantic_regeneration`；`mini_recovery` trace 分开记录数量。旧 `mini_artifact_review_rejected` 是底层校验诊断，不应和 `mini_report_rejected` 相加重复计数。

两类错误共用同一个 executor `StepLedger`、原截止时间、原输出 token 池和 `tool_repair_retries`。没有新增报告重试池、模型角色或独立预算，也没有把重试次数设为 0。`semantic_regenerations` 的账本合计包含两类重新生成；实际 API 请求应按 request_id 归账。

## 同轮输入重新准入

每次候选请求发送前，Mini 按共同 ContextClient 的计量规则检查真实消息尺寸：包含 cached 四视图、label 和序列化转义开销，同时检查文本字符、序列化字符和粗估 token 限制。原 ContextClient 仍进行最终检查及实际附加视图。

准入从共同 actor 的 `self.turns` 获取真实完整旧轮边界，不根据语言推测。空间不足时逐个移除完整旧轮；完整被拒原生候选、配对工具回执及修复反馈属于受保护的当前轮后缀，不裁剪。原任务提示若附着于被移除的旧观察，只原样移到首个保留观察。系统消息、当前原图、当前几何说明、工具定义、原工具 ID 和消息内容都保留。

工具 ID 在每个完整旧轮和当前后缀内检查：拒绝缺回执、悬空回执或重复回执；不同已闭合轮次复用同一个 ID 是允许的。只修改本次发送副本，不修改 durable history、原始日志或模型事实。

没有旧轮可删或关闭 context rescue 时，若必需部分仍超限，明确抛出本地 `ReadAnomaly`，不截断推理、图片或工具参数，不追加 API 请求。这保留了原容量限制，不能保证任意大小回复均可恢复。

## 简化报告

新 prompt 只展示一个对象及四个 `[observation seq, short fact]` 条目；不再要求生成三层对象闭合。示例值必须替换为实际观察：

```text
<artifact_review>{"candidate":"PATH","source_confirmed":[1,"FACT"],"content_previewed":[1,"FACT"],"name_correct":[1,"FACT"],"destination_confirmed":[1,"FACT"]}</artifact_review>
```

不产生文件的任务另用 `{"no_artifact":"WHY"}`。引用仍是同任务真实 observation 的正整数，content_previewed 的引用必须等于 current.ref。原 candidate 300 字符、单项事实 160 字符、理由 240 字符、报告 2400 UTF-8 bytes 限制保持。旧 v2 的严格合规报告仍能规范化读取；无效 JSON 不补括号，缺事实、缺字段或缺引用不自动填入。

四项认证状态保持 unknown，模型复核不是独立内容认证。仍需先预览候选产物；观察截图、菜单关闭、时间戳和命令返回都不能证明导出内容正确。不新增截帧等任务专用指引。

报告规则压缩为短说明但保留全部硬限制。旧 opt-in controls 包也与默认视图一致，把 selector 留在 profile；controls 版本保留在原 record，不再在外层 extensions 重复。这为操作与字节相同的重复观察证据留出空间，不删除事实或审计引用。首次完整回归中该边界案例失败，原记录保留；修复后复验，未删除原证据断言。

## 离线验证与证据

`tests/fixtures/mini_recovery_failures.json` 只保存两次真实失败的长度、usage 数值和来源 SHA-256，不包含私密 prompt、推理或图像 payload。回归按 v4 的两次失败和 v6 的 22,307 字符推理构造无 GUI／API 的恢复输入，并使用真实 StepLedger 计量模拟输出。另覆盖原生错误的大回复准入、混合错误共用次数、未知 usage、截止时间、零重试配置、全部输入限制，以及任务／当前图／ID 配对的保留。

`scripts/validate_mini_recovery_saved.py` 直接只读原 v4／v6 事件、原始 SSE 和图像，校验 fixture 长度与哈希，分别验证新报告反馈和完整原生修复的准入。它不向模型重放轨迹，不执行原动作，不评分；结果不是线上成功率。

在两次原始保存输入上，新报告反馈含原 Mini 视图后的文本分别为 **23,801** 与 **19,632** 字符，均低于 32,000，且无需删除旧轮。完整旧原生修复输入经同一准入逻辑裁剪 7／12 个完整旧轮后，含视图分别为 **31,512／31,668** 字符，原被拒消息、推理、tool IDs 和回执全部保留。这是预算与结构验证，未生成新的真实模型响应。

验证记录位于：

- [原始失败输入的准入证据](../outputs/mini-report-recovery-v7-20261018/saved-failure-admission.json)
- [最终回归与源码核对](../outputs/mini-report-recovery-v7-20261018/regression-final.json)
- [保留的首次回归](../outputs/mini-report-recovery-v7-20261018/regression.json)
- [最终验收记录](../outputs/mini-report-recovery-v7-20261018/acceptance.json)

实现修订及 profile 契约已变化，旧 checkpoint／冻结计划不能静默继续为 v7。原成绩与失败证据保留；线上评测需新的用户授权与冻结版本。
