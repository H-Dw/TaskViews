# K3 v6 无 XML 动作的接口诊断与改进建议

本分析依据项目 `bd1e64762fb6f82fcd0981547ab6163cc0f59444`、官方 `3d778a3c9a34a079316f70df023b166700445792` 与已封存的四组真实评测。另对 14 个 actor 响应和旧 v4 首个 native 响应重建原始 SSE，并将三个致命响应离线回放到固定官方 QwenClient。没有调用模型 API、操作 GUI、启动实验或修改运行源码。原实验结果与封存文件不改写。

结论：OSWorld 的执行、坐标映射和评分底座已复用；此次失败发生在动作生成协议和自定义 K3 响应兼容层，尚未进入真实 CUA 执行。沿用官方底座应保证合法动作能够被按规范执行，但不能保证任意模型会遵守面向 Qwen 的 XML 输出协议。K3 的任务输出合规性、空动作流程和响应兼容仍需要分别验证。

## 实验事实与失败位置

|任务/两臂|完整 actor API / 返回决策|XML / CUA 动作 / 命令回执|官方成绩|终止原因|
|---|---:|---:|---|---|
|059 baseline|500 / 500|0 / 0 / 0|有效 0.0|500 次文字响应，官方上限后正常评估|
|059 TaskViews|4 / 3|0 / 0 / 0|无有效成绩|第 4 actor 空正文被 K3 XML 层拒绝|
|046 baseline|5 / 4|0 / 0 / 0|无有效成绩|第 5 actor 空正文被 K3 XML 层拒绝|
|046 TaskViews|2 / 1|0 / 0 / 0|无有效成绩|第 2 actor 空正文被 K3 XML 层拒绝|

表中的 actor 数排除了官方摘要和 TaskViews 分析请求。API 完整响应、适配器接受、合法动作、执行回执、任务评分是不同阶段。本轮没有发生坐标编译拒绝或动作执行失败；因为全部 508 个返回决策均未产生 CUA 动作。三个缺少 result 的组不能记作 0 分。

059 baseline 第一轮就返回“先最大化 GeoGebra 窗口、再看完整界面”的意图文字；后续重复“点击最大化”等表达。第一轮没有 TaskViews，也没有历史或摘要。其原始 SSE 完整，finish_reason=stop，并非 length 截断或网络中断。源码和抽样请求显示官方系统提示逐字匹配，模型图片为 1920×1080，原图哈希一致。原始响应没有被传输层丢掉的 native 工具分片。

这说明最初问题是输出没有落实到可执行调用。模型在文字中描述了可见应用和意图，不能据此认定其目标定位一定正确；零执行也无法验证定位能力。

## 为什么无动作没有触发两次官方修复

固定官方的 system prompt 把 `computer_use` schema 放在文本 `<tools>` 块中，要求使用 XML。HTTP 请求没有 API `tools` 字段，也没有 `tool_choice`。这是 QwenAgent 的正常实现，工具可用性依靠模型遵守文本协议。

`mm_agents/qwen/parser.py:48` 只解析完整 XML 块；完全不含 `<tool_call>` 的文字返回空列表，只有带标记但结构损坏时才抛解析错误。`actions.py:126` 对空列表返回空 commands。`main.py:424` 的修复只捕获解析/动作校验异常，所以纯文字不触发修复。

随后 `lib_run_single.py:1535` 把空 commands 视为向用户提问，调用原用户模拟器，轨迹记 ASK_USER；没有调用 env.step，也没有在该分支重取截图。上一轮文字与模拟器回答进入历史，同一画面再次送给模型。此次禁用了 terminal_status_judge，于是循环继续到官方 500 次上限。

该版本官方默认启用 terminal_status_judge，会对无动作文字进行结束分类，未完成时给 WAIT 和继续提示，但达到恢复次数也会返回 DONE(success)。本次关闭它是为遵守此前不允许恢复上限自动 DONE 的要求。盲目重新打开可能缩短无动作循环，却不能证明任务已经完成，亦不能保证会产生 GUI 动作。

原系统提示、解析与空动作规则组合，对已适配 XML 的模型可以工作；对当前 K3 实际任务请求没有体现出稳定的执行协议合规性。两轮合成红点/WAIT 探针只证明 K3 能在明确提示下输出 XML，并验证有限历史恢复，不能证明复杂真实任务、长期运行或空正文兼容。

## 三组致命异常是两个自定义层的契约冲突

三个原始 SSE 都只出现过初始 `content=""`，之后有 reasoning、finish_reason=stop 和 [DONE]，没有非空正文。不能把重建对象的 `content=null` 直接表述为服务端发回了非法 JSON 或发生传输故障。

`ui_kobe/api/kimi_stream.py:155` 的聚合器将 `''.join(content) or None` 作为正文。这个表示允许 native 工具响应只有 tool_calls。但 `ui_kobe/osworld/kimi_official.py:96` 又要求 reasoning 和 content 都必须是字符串。后者拒绝前者生成的 None，异常发生在官方 XML parser、修复和 env.step 之前。

官方 `mm_agents/qwen/client.py` 的 `_text(None)` 返回空字符串，流式 `_consume_stream` 聚合字符串列表。三个原始流离线回放到该官方方法均成功返回空正文，reasoning 逐字一致，XML 调用数仍为 0。完整回放证据见 [nullable-replay.json](nullable-replay.json)。

因此，致命终止属于适配器缺陷，不能归因于官方控制器、模型的坐标越界或任务不可完成。修复应在 XML 兼容边界规范化空字段，同时保存原始 SSE 和重建对象。它不允许从 reasoning 中猜一个点击，也不会单独解决持续无动作问题。

## 当前接口与固定官方 Agent 的差异

|环节|固定官方实现|当前 v6|判断与优化|
|---|---|---|---|
|视觉输入|截图、process_screenshot、smart_resize/固定像素图|调用官方处理，预先固定 absolute/1920×1080|保持。OSWorld 没有替任意 LLM 自动识别点击目标的通用 grounding 函数|
|坐标与动作编译|project_point、translate_tool_calls，整批校验|未改，采用固定模型图像素|保持。无需猜单位或裁剪越界坐标|
|执行与评分|runner、env.step、PythonController、官方 reset/evaluate|原调用链，加被动记录；046 实际原状态导入/共享 cgroup 已验证|保持。此次零动作，不能据 HTTP200 推断执行有效|
|actor predict|QwenAgent.predict 与 XML 解析/修复|继承原逻辑，telemetry 外包记录|保留算法逻辑；“官方源码未改”不等于全部运行选项都是默认|
|工具协议|文本声明 XML；面向 Qwen 的协议|同一文本声明，K3 API 未注册 tools|K3 工具协议应独立验证。现有 k3-native 路径可保留官方 schema/编译/执行，用供应商原生 function calls|
|响应字段|空字段正规化为空字符串，支持 reasoning 字段兼容|SSE 空正文变 None，XML 层再强制 str|必须修，属于两自定义层内部契约不一致|
|供应商参数|temperature=0、top_p=0.9 默认；enable_thinking 随角色|替换 temperature/top_p 参数策略；统一 effort=max，移除 Qwen enable_thinking，强制 SSE|字段翻译必要，具体限制需供应商当前证据。统一 max 会改变官方摘要的行为，不能称完全相同|
|历史|官方 build_messages、20 图折叠、默认100轮；文本 tool_response|官方算法、500轮配置；恢复 K3 原始 assistant reasoning/content|K3 恢复必要；避免内容字符串别名成为唯一身份。真实日志与 upstream 文本反馈语义应分别标注|
|上下文摘要|summary_folding 默认关闭，但 context rescue 仍可能调用摘要，默认4096/10次|context rescue 开启；摘要也被标 executor、也使用 max reasoning|059 baseline 486 次摘要、5次length。要按用途配置和记账，不能声称“没有摘要 LLM”|
|输出与时间|原客户端超时/重试、可接受 generation timeout Completion|自定义完整SSE要求、930秒整步/32000额度、600生成等|保持已授权保护，但这是共同适配政策，应文档化；截断不执行与完整空文本必须区分|
|结束流程|默认 terminal judge 可把 text-only 变 WAIT/DONE|两臂关闭 judge，显式 terminate/500 次上限|保留原授权；若加入空动作修复，作为另一个公开配置，不能冒充严格原版|
|TaskViews|官方没有该信息管理层|同图额外 perception/controller/planner/verifier；上下文注入、SQLite→模块→视图变化|允许实验差异，但权限限于证据和上下文，不替 actor 生成动作或控制结束|
|被动记录|原 trajectory 等|共同 SQLite + UI-KOBE 边语义；emit 参数kind冲突|必须修 observer 的命名冲突。写库已成功，告警不抛给执行，故非无动作起因|

TaskViews 在 actor 前使用额外模型推理，不是完全被动的存储系统。本次分析每角色 cap4000、max reasoning，且需在 315 秒内让出 actor 的完整生成窗口。059 TaskViews 有 7 次分析 length 和 2 次部分流期限截止；046 TaskViews 有 1 次分析 length 后恢复。这些是辅助链路问题，不能与致命响应字段拒绝或无 XML 混为一类。

本次 SQLite 能保留 episode、observation、task_input、decision/error 等；没有执行所以零转换边是正确事实。任务模块和语义字段可能是模型提议，不能被动当作任务完成证据。同截图上的 view delta 表示记忆更新，并不表示 GUI 状态改变。

README 的“关闭 summary LLM”和“v6 尚无在线评测”已不符合当前实际。准确事实是关闭一般 summary_folding、保留官方 context rescue，并已有本轮结果；本分析指出文档修订需求，不改运行或原实验文件。

## 为什么旧 UI-KOBE native Agent 能执行

旧 v4 max/32K Task059 两臂均取得官方 0.20，分别有 92/136 动作记录和 89/126 命令接口回执。旧版不是完全完成任务或满分；这至少证明该原生 function-calling 路径确实打通了动作执行。

本次离线核验旧 baseline 首请求：API 真正注册 1 个 computer_use 工具，tool_choice=auto，返回 finish_reason=tool_calls 与 1 个原生调用。当前 v6 XML 抽样的 14 个 actor 请求没有 API tools，且没有被遗漏的原生工具分片。二者的核心差异在动作生成协议，而不是旧版有一套更好的 VM 执行器。

旧 native 路径仍使用官方 translate_tool_calls、controller、runner 和评估；选择 native function calls 不意味着放弃官方执行底座。但旧 v4 的 relative 契约曾造成六组坐标拒绝，不能连同旧契约一起回退。新方案应继续采用已声明的 absolute/1920×1080。

v4 max32 与 v6 max16 同时改变输出上限、协议、提示、历史及结束选项，不能作单因素因果比较。此次所有 baseline actor 完整响应且未 length，增加 cap 并无证据能单独纠正格式问题。

## 建议的改进顺序

1. 修共同兼容层：空正文/缺少 reasoning 依固定官方客户端的语义规范化，保留原始 fields；将完整无动作、输出截断、传输错误、明确拒绝分别分类。三个真实原流纳入离线回归。同时修 emit-kind 冲突和摘要用途标签，更新文档。
2. 将“供应商→规范动作”定义为唯一共同接口。优先对当前 k3-native + absolute 契约做真实任务短程兼容验证；工具 schema、整批官方编译、env.step、评分继续原版，两臂共用同一协议，不按单次输出动态切换。XML 作为单独对照保留，不从自然语言或 reasoning 猜动作。
3. 更准确的迁移准入：合成 XML 能力、真实任务动作合规、nullable 响应、历史/repair/summary 与原回执分别验证。真实任务 smoke 应确认第一批动作实际执行及后截图/回执，不能只检查 HTTP、服务状态或生成了代码。兼容性 smoke 单独记录，不冒充正式任务分数；正式阶段仍用既定官方终止规则。
4. 如保留 XML 为主协议，可明确“CUA 意图须生成工具调用，需要用户信息则 call_user”，并考虑将完整但无调用的执行意图纳入有界修复。该策略须两臂共同使用、公布修改与费用，不能标成逐字原版。不能靠重新启用 judge 的自动 DONE 来掩盖无动作。
5. 将 TaskViews 限制为任务证据服务：消费共同转换日志，保存 source/target/action/instruction/receipt/target observation/schema delta；模块依目标/依赖/证据管理，按图变化分发。actor 仅消费可选上下文，执行与结束权限不交给 planner/verifier。模型 verified 与真实效果验证分开。相同 frame 与 revision 优先复用数据，不反复重算四角色。
6. 在保留 actor max/16000 前提下，声明摘要与分析各自的预算/推理策略；若供应商不能关闭 thinking，不假称已经关闭。给 bounded JSON 做真实预算准入，耗尽后留证降级，摘要不能悄悄使用 actor 标签。两臂 actor、图像、坐标、执行反馈与评估选项固定，只让 TaskViews 的信息管理和辅助推理成为实验变量。

修复响应兼容仅消除崩溃；打通协议才会产生可执行动作；TaskViews 只有在共同动作链路成立后才能评估其信息管理收益。目前数据不足以判断其 GUI 任务表现优劣，也不能承诺任意模型使用官方代码必然完成任务。

## 可复查证据

- [抽样请求/提示/图像哈希/SSE及源码索引](evidence.json)：四组首请求系统提示逐字匹配、1920×1080图像、14个actor原响应和旧native首响应。
- [三条真实原流的官方客户端回放](nullable-replay.json)：原流 content 只有一次空字符串 delta，官方 client 返回空文本，当前 accumulator 生成 None。
- [本轮四组总结果](../../experiments/official-qwen-v6-max16-20261007/final-results.md)、[旧 v4 八组报告](D:/cua_lty/UI-KOBE-TaskViews/docs/experiments/native-official-policy-v4-20261005/final-results.md)。
- 固定官方 [QwenAgent说明](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/mm_agents/qwen/README.md)、[parser](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/mm_agents/qwen/parser.py)、[client](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/mm_agents/qwen/client.py)、[main](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/mm_agents/qwen/main.py)、[prompts](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/mm_agents/qwen/prompts.py)、[runner](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/lib_run_single.py)。

本分析只新增独立报告与离线证据。冻结运行源码、计划、原始 SSE、审核、终止报告和索引保持；没有重跑或恢复已暂停心跳。神经模型为何偏好叙述的内部原因不能仅从日志确定，已证实的是执行协议不合规及框架具体处理路径。
