# TaskViews-mini 复核纠错与统计优化

本次优化由用户在 VLC legacy/low 第15格异常后明确要求。原始失败记录、已完成14格的官方成绩和三个未启动格均保留。该异常没有证明 GUI 执行器或官方评分器出错；本次改进的是复核纠错信息和派生统计的可靠性。

后续r005出现的引用类型问题及第6/7次修复记录见 `taskviews-mini-review-reference-v3.md`。本文保留v2的历史诊断和验证结果。

## 代码溯源

1. `ui_kobe/osworld/mini_taskviews_native.py::validate_actor_candidate` 先调用共同工具校验与编译路径。只有候选动作声明 `terminate/success` 时，才要求公开产物复核。
2. `kobe_views/artifact_view.py::validate_review` 检查 `assistant.content` 中唯一、完整的 `artifact_review` JSON、字段、类型和长度。
3. `ui_kobe/osworld/mini_taskviews_context.py::validate_review_references` 按原 journal 验证引用为同任务、同 episode 的 observation，并要求最终内容预览引用当前观察。模型报告的证据等级仍是 unknown。
4. `ui_kobe/osworld/mini_recovery.py::generate_candidate` 在同一 actor 的时间、输出 token 和两次语义再生成额度内纠错。耗尽后抛出原错误，未通过的成功动作不执行。
5. 错误沿共同 `predict`、官方单任务运行器传回 `scripts/verified_invoice.py`，保存失败 outcome 并清理所属 guest；`scripts/verified_mini_graph_matrix.py::launch` 停止串行队列。

此次第13次 actor.predict 的三次 API 回复均完整到达：首次缺少复核标签；第二次有标签，但四个检查项复制了不对应 observation 的引用1；第三次再次缺少标签。原请求包含复核规范，后续请求也包含对应错误反馈，因此不能把停止归因为“指引未投递”。该格没有有效官方分数，不转换为0。

## 模块优化

### 有来源的复核纠错

引用校验现在一次报告四个字段中所有可确定的引用问题，包括实际提交的编号、跨任务引用、未来编号和过期内容预览。来源完整性错误仍立即阻断。校验只读取模型明确引用的事件，没有增加历史候选检索范围。

纠错反馈补充经过 journal 确认的当前 observation seq，并说明其用途：编号有效不等于截图已经展示了产物内容。成功回复须在同一次 completion 的公开 content 中提交完整复核，并配对原生 terminate/success；证据不足时可以继续检查。

修复提示使用 `OBS_SEQ`、`VISIBLE_FACT` 和 `PATH` 等明确占位符，并列出与校验器一致的字段长度、JSON字节限制及无文件任务形式。它不填入任务答案、文件事实或历史解法，也不回放被拒绝的模型推理、公开事实声明和工具调用。

新增 `mini_report_recovery_exhausted` 记录完整错误代码序列、当前尝试次数和停止原因；反馈版本为 `mini-review-feedback-v2`。仍然共享原来的两次纠错额度，模型调用、工具 ID 配对及官方动作编译协议不变。

### 基于回执的统计

`mini_fixed_views` 在请求前发出，初始 `delivered=false` 只是打包阶段状态。统计现在使用相同进程、帧和 packet 哈希的 `mini_views_delivered` 回执确认投递，同一个 packet 的重复回执只计一次。

明确省略单独计入 `omitted_packets`；既没有投递回执、也没有明确省略的包计入 `unconfirmed_packets`。哈希冲突、矛盾回执和无来源回执记录为审计错误，不推断成功投递。

`step_token_accounting.semantic_regenerations` 是每一步内的累计快照。统计改为计数 `mini_report_regeneration` 和 `semantic_regeneration` 事件，避免把0、1、2的快照相加为3。另列复核拒绝数、纠错耗尽数和最后错误类型。统计版本为 `mini-event-receipts-v2`，旧日志也可以重新派生报告。

## 验证和比较边界

- 三模式覆盖“缺标签 → 无效引用 → 合法复核 / 再次失败 / 继续检查”三个分支，确认最多三次请求、两次纠错，拒绝动作不执行，unknown不升级。
- 检查纠错过程不重新选取或打包 View 事实，每次 packet 仍不超过3000 UTF-8 bytes。
- 保留原 legacy 请求及 packet 固定样本回归，以及 Graph 身份、引用、恢复和同输入消融测试。
- 统计测试覆盖重复投递回执、多个进程的相同帧名、明确省略、无回执、错误哈希、孤立回执和累计快照。
- 原始运行器的54个模拟场景与8个媒体评分接入场景须通过后，才能重新冻结计划。模拟结果不是 benchmark 成绩。

第一次候选验证有249项通过、1项因验证脚本外层全局锁与独立CLI测试冲突而失败，已计入第4次修复。第5次保留相同应用代码、纠正验证脚本锁用法，250项回归及 Ruff 均通过；54个原运行器场景和8个媒体评分接入场景也全部通过。完整证据位于本实验根目录的 `repairs/r004-review`、`repairs/r005-review`，其中 `repairs/r005-review/validation.json` 绑定当前源码及两类验证的真实证明。

对原日志重新统计得到469个packet、469个实际投递回执，和独立诊断的逐格统计一致，原始官方分数全部保留。新统计报告归档于 `revisions/r003-resume02/report-before-r005`，版本来源和哈希见 `prior-version-results-r005.json`。

共享纠错模块发生行为变化，影响 invoice、GIMP、VLC 三个任务，必须使用新版本重新运行全部18格才能进行同版本比较。旧14格有效成绩仅作为旧版本结果保留。这些离线验证不证明任务成功率提高，也不能保证模型以后不会违反复核格式。

## 启动验证与后续执行

2026-10-24（北京时间），新版本完成两套 High/Low provider 检查和六套模式定位诊断，共30次真实API请求，全部返回。定位诊断按冻结规则保留未命中样例，完成采集不等于定位全对，更不等于正式任务成功。此次探针输入118,015、输出30,053 tokens；金额未知，已单独记入 `preflight-costs.json`，不混入正式任务用量。

最终 `check` 确认18格计划就绪、来源一致且资源余量达标。`revisions/r005/queue.json` 已由唯一串行运行器启动，首次有界巡检确认 launcher 身份有效、源码未改变、无 issues，活动格为 `01-invoice-legacy-high`。启动证据见 `repairs/r005-review/activation.json`、`launch-receipt.json` 和 `start-inspection.json`。

原40分钟 heartbeat 已恢复 ACTIVE，累计修复计数为5/10。后续依旧每次只做一次有界巡检，异常按持久状态处理，正式任务不并行，不持续驻留监控。本次修改仅保存在本地。
