Attempts 召回 v2 使用 `eligible_attempt_retrieval_v2` 策略。它只修改有 capability guidance 的 Mini 路径，不新增模型角色、查询工具、GUI 动作或图路径规划。原始 journal、真实错误、执行协议、终态校验和 3000 UTF-8 bytes 包体上限保留。

**检索与适用性。**

`decision_flow.attempt_recall` 与 `operation_support.navigation_recall` 委托同一个 `attempt_retrieval.retrieve`。后者保留“再次导航”的候选入口条件，但来源、对象、阶段、有效期与后续参数检查相同。正式 context 只调用统一结果，不再通过 `or navigation_recall` 恢复已排除记录。

查询必须来自本任务日志里的公开 decision 或本轮 knowledge_query，并有可解析的原始观察。上一轮意图仍是预取依据，不伪称本轮策略；空文本、纯界面状态、私有 reasoning 不产生召回需求。候选仍来自现有 96 事件窗口，保留 2 步需求与 12 步尝试有效期。

候选要求：完整派发边界、原始 decision 与前后观察、正确事件顺序、同任务与同 episode。截图、等待和部分按键动作不作为操作路线。来源完整但回执失败的动作可以作为 `avoid_repeat` 参考；它不会成为成功路径。

已明确提及的软件、文件、引号内对象与命名输入控件互相冲突时排除。别名来自已有目录，名称匹配不证明当前软件或焦点。未知对象不被补造为确定对象；当前实现不做视觉对象合并或跨对象的完整流程泛化。

**参数与阶段。**

后续同一公开缩放范围的输入可使旧输入不再适用；已经确认输入时，不再召回旧输入／聚焦步骤作为下一动作。剪贴板后续写入与粘贴派发也会使旧的待粘贴参考退出。明确的新比例与旧参数不同，会排除旧输入。具体判断及后续事件引用写在审计中。

这些是执行顺序和公开范围上的适用性判断，不代表 GUI 参数已生效。后续失败回执记为 `later_attempt_failed`，不宣称值被成功替换。原始输入、失败和重复次数完全保留。未被排除的历史工具参数仍是历史事实，带 `historical_only_rebuild_current` 与重新定位标记，不自动重放。

可重建的参数检查依赖有来源的公开范围。它不替代 Current 的真实截图，也不保证识别所有语义相同的控件或重复操作。当前 Keyboard 的缩放状态机未在本次改动中重写。

**打包与实际送达。**

当前事实、最新真实动作、真实错误和按键保持约束优先。通过检查的完整召回随后参与预算，优先于可选 Keyboard 卡，不要求出现 `keyboard_lookup` 或 Current.strategy。无匹配继续为空；预算不足明确省略，不截断动作事实，不增加预算。

原始记录若已在 Attempts 候选中，附加召回用途而不复制同一事件。完整来源通过短引用解析，本地保留哈希和原载荷。flat／linked 仍按相同 linked 成本选择，不改变两者的离线消融条件。

新增审计事件：

- `mini_attempt_retrieval_prepared`：当前 journal 游标、查询来源、候选入口、排除原因、参数替代事件与选择结果。
- `mini_attempt_retrieval_delivery`：frame、context revision、packet 哈希、选中引用、包内引用与实际投递状态。

`selected_ref`、`in_packet_refs`、`delivered` 分别表示本地选中、进入包和实际投递；不能互相替代。没有调用 Keyboard 查询也完整记录。参数匹配、送达和模型采用仍是不同指标，不推断模型采用率。

**冻结与验证。**

新策略写入 `mini_guidance.decision_flow.attempt_retrieval`，包含检索与打包规则版本。旧配置／checkpoint 不能在新策略下静默恢复；须使用旧源码，或重新准备新冻结计划。本次不修改历史实验、结果和冻结代码快照。

回归使用通用合成场景，覆盖两个入口相同的来源门槛、对象／软件冲突、100→200→确认、不同输入控件、失败回执、空需求、稳定选择、无查询的 legacy／flat 实际请求、紧预算省略和恢复策略拒绝。真实 benchmark 收益仍需独立评测，本次验证不产生新的在线评测成绩。
