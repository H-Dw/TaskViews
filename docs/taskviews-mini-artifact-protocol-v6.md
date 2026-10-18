# TaskViews-mini v6：减少产物报告格式失败

2026-10-18 修订 `mini_artifact_protocol_v6`，报告规则为 `mini_artifact_review_v2`。在已有 v5 键盘目录改动上实现，仍为四个 View、3000 UTF-8 bytes、额外模型角色 0。此次是代码修复和离线验收，没有调用线上模型、启动 guest、操作 GUI 或运行评分器。

## 修复原因

旧 VLC v4 第 10 轮第一次缺少报告标签，第二次 JSON 少一个闭合大括号；第二次三个 observed 字段还有 251／189／262 字符，超过未公开的 160 字符限制。旧解析器把这些错误都变成同一条提示。两次拒绝后，原修复链累加完整回复与推理字段，下一请求在 43,936 字符处被 32,000 字符输入保护阻止。

本版本针对进入该修复链的 Mini 格式诱因。共享 actor、repair_messages、native_history、CUA 输入／输出预算和 tool_repair_retries 不修改。官方 OSWorld 执行器与评分器不修改。

## 完整且一致的报告协议

`kobe_views/artifact_view.py` 用同一组常量生成完整四项 JSON 示例、prompt 长度说明、解析器限制与版本契约。成功候选需要在公开 assistant.content 中给出一个报告，同时保持原生 terminate 工具调用独立。示例值必须替换成实际观察；程序不自动填写路径、事实或认证等级。

限制保持原值：candidate 1–300 字符，observed 1–160 字符（建议不超过 80），无产物理由 1–240 字符，标签内部 JSON 最多 2400 UTF-8 bytes。字符串非空；引用是同任务真实 observation 的正整数序号；终止时四项齐全，content_previewed 引用当前观察。无产物分支仅用于任务本身不要求文件产物的情况。

模型复核记录与独立认证状态分开说明。current／lessons 的 source_confirmed、content_previewed、name_correct、destination_confirmed 继续保持 unknown；报告和 confirmed 声明都不把它们变成 verified。任务缺少观察依据时应继续检查，不能用报告格式代替证据。此处没有新增通用视觉语义认证器。

## 具体错误反馈

新增 `ReviewError` 与 `validate_review`，分别报告 missing_tag、tag_count、invalid_json、report_bytes、report_fields、invalid_reference、wrong_task_reference、stale_preview。JSON 语法错误指出行列；语法通过后一次列出全部字段错误及实际长度，不回显原始报告／推理。旧 `parse_review` 保留无效历史注记返回 None 的接口。

Mini 将错误明确标为公开报告问题，要求更正 assistant.content，保留原生工具语法；证据不足时先观察。仍使用原修复池、原截止时间与原预算。拒绝候选不执行，不自动补括号、不截断事实、不替换引用、不升级 unknown。遥测额外记录 Mini 拒绝类别。

## 3000 bytes 的选择与审计

完整报告协议与 current／lessons 的 unknown 状态先占位，随后选择关键操作＋后续观察、未解决错误／复核报告、匹配键盘参考及原始记忆。通用交互说明、重复意图和目录发现按剩余空间选入，整条省略，不截断原始事实。

为容纳完整模板，移除重复元数据：selector 定义留在 profile 契约；当前几何只在原有强制 frame contract 中出现；图片 hash 通过 current.ref 指向的完整 observation 核对；sources 仍保存事件 SHA-256 与 kind。键盘记忆省略固定的“recorded”收据说明，真实收据仍在原事件中。旧 opt-in controls 包的静态来源 URL 留在 controls policy，包内保留来源 ID 与目录引用，绑定内容不改。

遥测 `artifact_protocol_in_packet` 检查完整规则是否被选入，`delivered` 记录传输边界是否实际附加上下文。验收直接读取模拟 transport 收到的 prompt，检查完整协议、四项状态、操作、观察来源和键盘记忆，不能仅检查四个 View ID。

版本契约变化会拒绝旧 checkpoint 的静默载入。旧运行和成绩保留，不把旧失败 episode 恢复成 v6。

## 离线验收与边界

回归覆盖缺标签、未闭合 JSON、多个字段同时超长、字符与 UTF-8 bytes 的不同限制、部分历史报告与终止报告的区别、无效／过期引用、原生工具 ID 配对、首次合规完成、关键证据与键盘记忆在实际 prompt 中的保留。构造 16,939 字符的模拟 reasoning 验证首次合规报告不走修复；构造超大无效回复仍应在额外请求前被原输入保护阻止。

最终 17 个文件、330 项离线回归通过，包含新增 19 项协议测试及 500 轮模拟／第 250 轮恢复；Ruff 通过。首轮扩展回归中，一项旧测试仍要求每轮提供可选通用说明，随后按新优先级调整该断言，并复验其整个 18 项测试文件。两次扩展验收的生产源码快照相同，原失败日志保留；330 是按文件合并后的去重测试数。验收使用 128 MiB／零 swap scope，无 OOM。

原第 10 轮已选记录离线重排为 2994 bytes：完整协议、关键操作、观察来源和两处 unknown 状态均保留。新校验器对原两份公开回复分别返回 missing_tag 与 invalid_json；仅在内存中补齐第二份 JSON 的括号后，能一次报告 262／251／189 字符三个超长字段。原始响应没有被修改或重放。

官方关键执行／评分源码与共享 actor、repair、history、CUA 合同逐项核对未改；旧四组评测的 35 个证据文件 hash 一致，两条原巡检仍为 PAUSED。

这些是模拟协议与代码验证，不能证明真实模型的首次报告合规率，也不产生 OSWorld 分数。保留原预算意味着偶发长修复仍可能触发输入保护；本修复不声称从所有路径消除了超限。

离线日志与最终验收记录位于 [outputs/mini-artifact-protocol-v6-20261018](../outputs/mini-artifact-protocol-v6-20261018/)。真实线上比较应使用新的冻结提交与独立 run，不能覆盖既有结果。

- [合并验收记录](../outputs/mini-artifact-protocol-v6-20261018/acceptance.json)
- [原第 10 轮重排检查](../outputs/mini-artifact-protocol-v6-20261018/step10-repacking.json)
- [原失败报告的新诊断](../outputs/mini-artifact-protocol-v6-20261018/original-report-diagnostics.json)
- [相对于本轮开始工作区的补丁](../outputs/mini-artifact-protocol-v6-20261018/changes.patch)
