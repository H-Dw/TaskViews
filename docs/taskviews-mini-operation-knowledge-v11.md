# Keyboard 操作知识边界 v11（2026-10-30）

Keyboard 只提供适用的具体按键与操作方法。任务核验、结果检查和阅读进度由 Current、执行反馈及原终态复核承担，不由 Keyboard 卡片补充或证明。

## 删除内容

从指导库、准入契约和路由中删除 `view.zoom_check`、`view.readability`、`clipboard.verify`、`capture.image`、`export.file`、`image.edit`、`pointer.drag`。同时移除含阅读声明复用与结果判断的 `document.read`；具体翻页操作仍有 `navigation.down` / `navigation.up`。

指导库从 42 张减为 34 张。VLC 视频截图和 GIMP 导出等具体软件操作保留。没有覆盖的截图、导出、图像编辑和拖拽需求不再获得泛化替代卡；原生 GUI 工具仍可执行这些动作。

粘贴派发后仅记录该键盘流程已派发完毕，保留 `effect_status=unknown`，不生成检查卡，也不重启旧复制粘贴建议。缩放框尚待 Enter 时仍提供 `view.zoom_confirm`；Enter 后的真实缩放效果留在 Current，不生成 Keyboard 核验卡。已有阅读报告、调整链、真实错误与终态复核继续沿原来源和有效期规则处理。

## 空结果与提示元数据

`no_match` 原来是选择／送达状态，不是独立指导卡。现在无候选时 Keyboard 的 `records` 为空，不输出 `guidance_status.card=no_match`，不放替代提示。内部选择及可选查询回复使用 `empty` 表示空结果；它只描述是否有参考资料，不是一条操作知识。声明但未覆盖的缺口留在 Current 的 `knowledge_gap`。有候选但预算不足仍明确标记 `omitted_budget`。

每张送达卡不再添加通用 `when`。旧目录路径也不再送达 `check` 字段；v11 从目录导入配方时不再将 `check` 拼接进 `steps`。目录原始 `check` 仍作为来源说明保留在 catalog 和生成的参考文档中，不参与知识覆盖，不是一条独立按键配方。

保留卡的 `steps` 清理为操作步骤，去除任务完成、阅读结论与结果核验提示。软件、对象、控件和焦点等适用范围仍由 `scope` 及原准入规则限制。

## 覆盖判定

- 按键覆盖继续依照主操作对应的准确绑定判断。
- 普通方法覆盖改为显式 `procedure_operations` 契约，不再凭 `steps` 非空判定。没有绑定、只有泛化控件描述的卡不自动覆盖方法需求。
- 完整流程仍要求已声明的 workflow 及依赖；通用“选择一个绑定”不等于完整流程。
- 结果检查需求不能由 Keyboard 覆盖。混合需求中的“按键和结果核验”不能声称完整覆盖；“按键或结果核验”可只覆盖按键，并明确显示检查部分未覆盖。
- 即使 `steps`、`when`、`check` 含有 inspect / verify / check 等词，也不能据此补足结果检查需求。

## 冻结身份与验证

新指导／打包身份为 `operation_knowledge_v11`，选择契约为 `operation_knowledge_selection_v2`，准入契约为 `operation_knowledge_applicability_v3`。旧目录 policy 增加送达契约 `operation_reference_without_checks_v1`。新计划与 checkpoint 不可静默混用旧策略；历史源码、实验计划和 v10 验证摘要保持原样。

`tests/test_keyboard_operation_knowledge_v11.py` 覆盖删除条目不可经 lookup 恢复、核验需求不可冒充操作知识、通用 check 不补方法、粘贴／缩放后无核验卡、具体软件按键保留，以及三种 View 模式空查询后仍能派发原生动作。既有回归继续检查 Current 来源、阅读报告、终态复核、预算、查询上限和恢复隔离。

本次为离线代码与回归验证，没有模型 API 请求、GUI 在线重跑或新的成功率结论。

验证覆盖全仓 2146 项。最终全仓运行中唯一未通过项是新增快照比较断言：删除通用检查文字后，原预算可额外容纳一条已有按键记录。断言已改为检查该记录的同任务来源与 unknown 状态，并确认其余事实一致；Graph 模块 22 项重跑全部通过。静态检查、生成目录同步及 diff 检查通过。完整结果与源码哈希见[验证摘要](../validation/taskviews-keyboard-operation-v11-20261030.json)。
