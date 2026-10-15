# TaskViews Mini：坐标、错误分类与重复动作反馈修复

本次改动依据 [v5 零分原因审计](osworld-verified-invoice-sx-flash-failure-analysis-20261015.md)。目标是修复 Mini 输入和反馈中的确定缺陷，并用真实 actor 路径检验坐标说明。没有重新运行官方任务、操作 guest 或改变旧成绩；自动巡检保持暂停。

## 改动与原因

| v5 观察到的问题 | 本次代码变化 | 验证边界 |
|---|---|---|
| 模型多次输出疑似 0–1000 坐标，而执行协议为 1920×1080 像素；旧探测与正式提示不同 | Mini 在每次正式 `predict` 的当前截图旁加入固定坐标模式、原图/模型图尺寸、中心与边界示例。说明在可选 views 之前计入共同上下文预算 | 不根据返回值猜测单位，不暗中缩放或改写动作；仍由官方 compiler 投影 |
| 成功回执的 `error=""` 被当成错误，占用 lessons | SQL 区分非空错误、显式失败状态、`success=false` 和非零 returncode；null、空白字符串、false、空对象/数组不再单独构成错误 | 控制器执行成功仍不等于点中目标；原回执完整保留 |
| `controls_view=disabled` 时不发送重复动作摘要 | `current` 默认读取最近最多 4 条已确认 journal 转移，记录连续相同命令/参数次数及前后图片哈希相同次数 | 只报告事实，`effect_status=unknown`；不把图片变化判为成功，不封禁合法重复操作 |
| 没有检查可见效果，反复点击同处 | 当前帧固定说明要求检查预期可见变化、输入前确认焦点；无预期变化时重新定位或选择其他可见/键盘路径 | 这是 actor 指引，不是新增视觉裁判或已实现的焦点硬门控 |
| 旧探测独立组装提示，只覆盖单个目标 | 新增 `scripts/probe_mini_grounding.py`，用真实 SX Mini `predict`、views、schema、历史构造和官方 compiler 测四个不对称位置 | 仅合成图片与未执行的鼠标移动候选；不能代替 GUI 闭环或官方分数 |

Mini 仍只有一个 actor、三个固定视图：`current` 是当前帧及字面重复证据；`attempts` 是最近真实执行边；`lessons` 是真实错误与明确标记为模型提议的原始文字。每条记录保留来源 ID、seq 和哈希。没有额外 planner、感知调用、模型总结或任务答案注入。

三个视图总上限仍为 **3000 UTF-8 bytes**。过大的重复摘要可以整项省略并标记；不截断命令，不增加 views 预算。坐标说明独立于可选视图，因此即使可选包无空间，当前帧仍明确声明单位。

## 历史、版本与配置

新增说明只保留在当前帧。下一轮在共同历史压缩前移除旧帧中由本模块生成的重复说明，保留原任务、模型消息和工具回执。这样避免静态提示挤占长轨迹中的真实历史；当前帧说明仍参与相同的 32000 字符上限和 10000 字符预留计算。

固定 profile 名仍为 `mini_fixed_v1`，冻结契约新增实现修订 **`mini_cua_feedback_v2`** 及本次输入/错误/重复策略。旧检查点不能无提示载入新语义；旧运行、原始轨迹和分数完整保留。后续正式比较必须生成与当前源码对应的新计划，不能把修复后的结果续写进 v5。

已有默认配置仍为 **absolute、1920×1080**，旧计划没有改变。新增 `--coordinate-type relative` 可以在**新计划生成前**冻结归一化单位，两组使用同一合同，图片保持 1920×1080，由官方 compiler 将每轴 0–1000 换算为原屏幕像素。合同校验允许 relative 与固定图片尺寸同时使用，避免默认智能 resize 将 1080 高度扩到 1088、超过原无损传输像素上限。没有运行中自动猜测或切换单位。

本次实际复测说明，加强 absolute 提示仍不够稳定：第一次四个目标都通过；随后一次独立验证第 1 个通过，第 2 个目标 `(220,860)` 却收到 `(115,794)`，按 absolute 执行会点错，按归一化解释则约为 `(221,858)`。该次验证立即停止，后两个目标没有请求，报告为失败。随后预先声明 relative 的独立四目标验证全部通过。因此后续随想实验建议显式选择 relative，仍需 GUI 闭环验证，不能把一次四目标通过解释为长期可靠。

`scripts/verified_invoice.py prepare`、`scripts/validate_verified_invoice.py` 和两种探测均支持显式单位选择。计划顶层声明、完整 `cua_contract`、离线验证和在线探测必须一致；旧的 absolute 证据不能用于 relative。SX 新计划另要求 `mini-grounding-check.json`，检查真实 Mini predict 的四个案例、源码、模型、入口及坐标合同。原 text/大图/native tool/tool reply 检查仍需通过。修复后的探测用官方投影后的**屏幕像素**验收目标，避免把归一化返回值直接与像素答案比较。

正式比较的 35 个决策轮、输出 token、图片数量、文本/视图和内存预算未提高。500 轮测试是既有的**离线历史与检查点回归**，不代表正式评测放宽到 500 轮。

## 验证记录

交付证据汇总为 [delivery.json](../outputs/mini-cua-feedback-v2-delivery.json)。以下检查已通过：

- [15 个相关 suite、277 项回归](../outputs/mini-cua-feedback-v2-release.json)：0 失败，Ruff 0，含 500 轮、第 250 轮检查点恢复、最近工具回执保留、错误分类、重复反馈、原 compiler 及新计划约束。官方源码与本项目源码在验证期间均未改变，128 MiB/零 swap，OOM 0。
- [最终探测内存修复的 43 项定向复查](../outputs/mini-cua-feedback-v2-probe-memory.json)：0 失败，Ruff 0；验证释放缓冲区后生成的合成 PNG 字节和哈希仍一致。它与前述测试有重叠，不能把两组数字相加。
- [最终 Mini actor 的四目标归一化验证](../outputs/mini-grounding-20261015-v2-release/report.json)：4/4 通过，四个编译后屏幕坐标分别为 `(1617,179)`、`(223,872)`、`(1747,934)`、`(1023,341)`；全部距预期中心每轴不超过 30 像素。此后仅修改普通接口探测脚本的内存管理和阶段记录，Mini actor/视图/编译/计划代码没有变化；交付 JSON 单独列出源码差异，不把不同源码的整项目证据冒充同一个版本。

仍有两项完整预检未通过，因此本次**未声明可以启动正式比较**：

- 普通接口探测的图片为 4,387,662 bytes PNG、5,850,238 字符 data URL。初次已收到 text 和 vision 的完整响应，第三个请求因探测脚本保留临时图片而 OOM；已释放临时 noise/PIL/PNG 缓冲区，并在每阶段保存未完成报告。随后两次检查均完成 text，但大图请求上传时报 `WriteTimeout`：[第一次](../outputs/mini-provider-relative-v2-memory-fixed/report.json)、[第二次](../outputs/mini-provider-relative-v2-final-check/report.json)。未放宽超时、改图片或切换入口；不能把请求超时推定为零费用。
- 六场景原运行器集成检查在第一场、完整环境导入阶段触及 128 MiB 限制，0 场完成；其余五场未启动。[失败记录](../outputs/mini-verified-relative-v2/startup-failure.json)。没有提高内存上限或替换官方环境导入来制造通过结果。下一正式计划仍需补齐与所选合同及当前源码一致的六场景证据。

保留此前失败记录，避免只报告成功的末次：

- 初版新增说明过长，在既有 500 轮测试第 493 轮超过上下文预算；缩短后能够完成 500 轮，但末轮最近工具回执被挤出。修复方式是仅保留当前帧的说明，没有增加预算或弱化测试。
- 第一版合成探测载入整个评测环境，在 128 MiB scope 内因 OOM 于首次模型请求前退出。探测现只载入官方 compiler 和 actor，仍使用 128 MiB、零 swap；没有提高内存上限。
- 首次完成的在线探测记录为 [absolute-r2/report.json](../outputs/mini-grounding-20261015-v2-absolute-r2/report.json)：四个目标均通过。这份记录对应历史提示去重前的源码。
- [absolute 复测失败](../outputs/mini-grounding-20261015-v2-final/report.json)：第 1 个目标通过，第 2 个失败后停止，共 2 次请求，后 2 个未测试。不能只保留第一次通过结果。
- [relative 初次验证](../outputs/mini-grounding-20261015-v2-relative/report.json)：四个目标通过，4 次请求；对应冻结计划入口整合前的源码。
- [普通大图探测首次 OOM](../outputs/mini-provider-relative-v2-release/startup-failure.json)：3 次请求开始、2 个完整响应，第三次使用量未知；没有产生完整通过报告。

Mini 探测必须显式传 `--live`；环境从 WSL 读取 `SX_QWEN_API_KEY` 和选定的 `SX_URL_SB`，模型 `qwen3.8-flash`、reasoning `low`。每个案例独立新 actor，首个定位失败即停止，不为通过而自动重试或改单位。报告明确 `benchmark_launch_qualification=false`：它只是新的启动必要条件之一，不能单独证明所有前提已满足，也不能冒充正式 guest 进入和动作成功证明。可用 `--root` 将证据绑定到已有的新冻结计划；本次没有创建或启动正式计划。

## 尚待正式验证的能力

四个合成位置不能覆盖密集图标、窗口焦点、PDF 阅读、滚动后的重定位和文件移动。重复提示也不能保证模型采纳。后续仍需在新的获授权实验中验证“实际动作 → 预期可见状态”，再判断是否能在 35 轮内读取发票/流水、保留字段证据、识别差异并提交正确产物。原 v5 的 0/0 不变，本次不宣称已经提高官方得分。

本次主要文件：`ui_kobe/osworld/mini_taskviews_native.py`、`mini_taskviews_context.py`、`kobe_views/fixed_views.py`、`ui_kobe/osworld/cua_contract.py`、`scripts/probe_mini_grounding.py`，以及比较计划/探测入口及相关回归测试。UI-KOBE-like 的逐帧提示没有随本次 Mini 优化修改。
