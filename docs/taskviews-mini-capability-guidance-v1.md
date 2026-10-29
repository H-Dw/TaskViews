# TaskViews Mini 按能力与流程阶段送达指导 v1

本次由用户明确要求结束本地评测后实施。当前 campaign 的 12 格已完成产物保留，剩余 6 格不再推进，结束记录为 `runs/verified-mini-legacy-flat-v7-high-low40-20261024-v1/termination-by-user.json`。没有重新启动评测、GUI 或真实 API 请求。

## 入口与兼容

`scripts/verified_invoice.py prepare`、`scripts/osworld_native_experiment.py` 的新 CLI 默认采用 `--keyboard-mode task_capabilities`。既有 Python 调用缺省值、旧计划缺少 `mini_guidance` 时仍走原选择器和原打包器。原路径对照显式选择 `--keyboard-mode task_names`（或原来的 `manual`），不可通过旧 checkpoint 切换新策略。

新建准备参数示例（本次不执行）：

```text
--keyboard-mode task_capabilities --mini-graph-mode legacy
--keyboard-mode task_capabilities --mini-graph-mode flat --mini-graph-packing evidence_first_delivery_v2
```

新指导在 legacy、flat、linked 都有独立的整组打包入口。对 flat/linked 未显式指定 codec 时，新准备入口选择 delivery v2；三模式身份、上下文预算与原执行协议保留。linked 仍只有已有的证据链接；本次没有增加图检索或路径规划，也没有安排 linked 在线实验。

`mini_guidance` 单独冻结策略版本、指导库 SHA256、公开任务字段哈希、能力集合、启用目录、检索窗口、有效期、失效规则和打包版本；原 `mini_keyboard_tools` 继续绑定旧目录身份。新字段说明覆盖旧 profile 中的选择与打包描述，旧 profile 的执行、复核和预算协议继续有效。manifest、验证结果、运行环境和 checkpoint 均携带或验证该字段。旧计划、旧结果不会自动升级；在新源码上启动实验需重新准备和验证。

## 意图、能力与来源

准备阶段仅读取原始 `instruction` 和 `related_apps`。除明确的软件名称外，用通用操作规则识别文件复制／移动／重命名、截图、导出、文本编辑等需求。文件操作、截图、导出会一并冻结 `type.file_manager` 辅助目录。不会根据 benchmark 编号、文件名特征、配置脚本、评分器或答案推断能力。

每轮自动检索采用：原任务中的通用操作；最近两次公开回复（最多相距两次决策）；同一 episode 最近 96 个原始事件中的实际执行与任务边界；原观察的不可变引用和已有图像哈希。空回复可保留短期自然语言提议，旧显式 lookup 不会被重新激活。复核 JSON 与 lookup 标签先从普通意图文本中剥离；常见否定表达不会成为正向操作需求。

已启用软件不等于前台应用。所有指导都标记 `conditional_verify_app_and_focus`，作用范围必须由 actor 结合当前画面确认。观察哈希仅用于比较同／异像素和字面重复动作，不产生 OCR、软件识别、焦点确认或业务成功结论。两个相同点击／滚动且图像未变时，可优先提供重新检查焦点的指导；复制后的图像未变不视为失败。

`<key_lookup>guide_name</key_lookup>` 是补充入口，仍接受已启用的旧 topic 和临时 `task.*` topic，不能打开未冻结的软件目录。软件目录中具备明确动作意图的暂停、缩小视图、快进等绑定可以自动检索；其他未覆盖的意图保留条件性通用指导或通过 lookup 查阅。无匹配时给出确认应用、弹窗、焦点和可见操作的短指南，不默认注入 Ctrl+A 或目录第一项。该路由是规则系统，不声称理解任意自然语言任务。

## 流程状态与完整指导组

复制／剪切必须是 journal 中完整的 `key` 派发，命令对齐、有回执、无失败或证据缺口，才形成 `pending_paste`。模型建议、未执行命令、key_down／key_up、重复参数及失败回执均不能推进阶段。

- 待粘贴状态最多保留到起始决策编号 + 6；目标目录输入等更直接的公开意图可以排在粘贴之前，粘贴仍是候选。
- 执行粘贴后进入 `verify`，最多保留到该决策编号 + 2。指导转向检查目标内容和位置，不持续推荐粘贴。
- 不同任务输入、Escape、未确认／部分按键、后续剪贴板写入、过期会失效或替换状态。记录源事件、阶段、到期编号和失效理由。
- 状态从原始 journal 重建，恢复不重放动作、不继承上一帧 packet。回执成功只表示工具返回，`effect_status` 始终 `unknown`。

`key_tools/guidance.json` 是独立的通用指导库，未修改原 catalog/general 文本。指南描述常见文件操作、编辑、确认、打开／保存、查找、滚动、截图、导出与检查。GIMP 导出和 VLC 截图带文档版本及作用范围；只提供操作方法，不写入本实验任务内容、坐标、目标名称、目标图像或评分规则。参考来源保存在每个组及冻结库中，包括 GNOME、GIMP、VideoLAN 官方手册。

整组接纳与省略遵循以下语义：复制与剪切是替代选项；明确移动时，剪切—导航—粘贴—检查构成完整组；没有说明复制还是移动时，转移组同时说明二选一及后续必需步骤。编辑并确认、文件重命名也有完整依赖组。旧目录的独立按键标为可选操作，不把相邻条目推断为流程。

排序按流程阶段、公开意图、原任务相关性以及适用条件，最后用基于内容、来源、平台和范围的稳定 ID 决定同分顺序。既不取前 N 条，也不永久把 Ctrl+V 提到首位。整组及其必要来源能容纳才入包；无法容纳就显式省略整组，不能拆掉流程的末尾步骤。

当前状态、完整复核协议、关键动作和错误证据先于指导；补充上下文仍最多 3000 UTF-8 bytes。极小预算可能省略整个包，指导送达没有硬性保底。flat/linked 在同一日志快照和预算下按 linked 成本选同一组事实，flat 删除关系后不补充其他内容。

## 度量与边界

`mini_guidance_prepared` 保存带来源和版本的候选、排名、所需组估计、阶段与失效原因；`mini_guidance_delivery` 仅依照原实际请求回执更新送达信息。准备好 packet 不等于请求已经成功返回。

| 指标 | 分母与解释 |
|---|---|
| 包送达率 | 有成功请求送达回执的 episode/frame ÷ 已准备 frame |
| 目录可见率 | 实际请求中含启用目录菜单的 frame ÷ 已准备 frame |
| 所需配方送达率 | 送达的所需稳定配方 ID ÷ 所需配方 ID；默认需求来自路由器估计 |
| 流程完整率 | 完整送达的所需流程组 ÷ 所需流程组；不得以单条配方替代整组 |
| 已知过时／不适用率 | 不属于本轮有效候选的送达组 ÷ 所有送达组 |
| 语义不适用率 | 无独立标注时为未知，不能把条件性候选全部记为正确 |

原始参数相同只能证明匹配；审计中的 `adoption` 为 unknown。不会根据后续动作反向宣称 actor 采纳了建议，也不会把运行成绩用于选择指南。

用 `scripts/audit_mini_guidance.py --events <events.jsonl> [--events ...] --output <新报告.json>` 汇总。它按 episode/frame 去重重试，并单列回执数量；无候选配方的分母为零时返回 null，不伪造 100%。

要测量实际需要和语义适用性，可用 `--annotations <独立标注.json>`。标注只能依据原任务、可见状态和公开执行证据，不读取 gold。格式为下列对象组成的数组：

```json
{
  "episode_id": "原 episode",
  "frame_id": "原 frame",
  "needed_recipe_ids": ["稳定配方 ID"],
  "needed_workflow_group_ids": ["完整指导组 ID"],
  "stale_or_inapplicable_delivered_group_ids": [],
  "applicability_review_complete": true
}
```

报告分别显示规则估计指标、独立标注指标和标注覆盖率。没有标注不声称当前需要完全送达或指导都适用。

## 验证和保留产物

`tests/test_keyboard_guidance.py` 使用通用合成任务验证能力冻结、阶段切换、失效、同分稳定性、整组预算、空意图与旧目录查阅、实际请求回执、三模式、恢复和严格消融。旧 legacy 请求基准继续保留。所有测试使用本地模拟传输，没有真实模型调用或 GUI。

本次修改前的源文件备份、原工作区补丁和哈希在 `outputs/mini-guidance-v1-20261026/before/` 与 `before.json`。验证结果写入同目录。离线结构验证不代表 benchmark 成功率提高；新的正式实验尚未启动。
