# v7：三组共用 actor，审计与模型反馈分离

2026-10-07。此修订实现 baseline、UI-KOBE-like、TaskViews 三组；此前冻结计划、成绩、SSE 与封存证据保持原样。本次是代码和离线回归，新版本尚未进行在线任务性能评测。

## 实验变量

| 项目 | baseline | UI-KOBE-like | TaskViews |
|---|---|---|---|
| actor 提示、历史、工具、修复、预算、结束 | 同一实现 | 同一实现 | 同一实现 |
| 原始请求、SSE、动作、真实回执、后截图、官方成绩审计 | 保存 | 保存 | 保存 |
| SQLite 转换节点/边数据库 | 不创建 | 保存并检索 | 保存并检索 |
| 可选模型上下文 | 无 | 最近执行边及观察引用 | 转换图上的任务模块与自适应视图 |
| perception / planner / verifier / view controller | 无 | 无 | 仅生成非执行分析与上下文 |

native 的三组直接继承 `KimiNativeAgent.predict` 和 `generate_candidate`；实验组不重写 actor。所有 native 请求使用同一个 `ContextClient`，它只在既有输入末尾追加有界文本，不能替换原目标、原截图、system prompt、工具或动作。

UI-KOBE-like 的转换记录必须实际检索并送入上下文，才可能影响 actor；只写数据库不能证明记忆提升能力。当前检索最多8条最近执行边，优先保留新的完整边，超出包大小时省略边并记录遗漏数。它没有 TaskViews 的角色调用或任务模块，属于边记忆的独立消融组，不声称完全复刻 UI-KOBE 旧版探索策略。

TaskViews 从同一事件库维护任务目标、依赖、证据模块与视图变化。模型 `verified` 保存为模型判断；真实控制器返回、后截图与任务评分仍为独立证据。view revision、模块切换或接口返回不能自动表示目标完成。原事件和可选两端 schema 注释保留，源节点、目标节点、动作、对应指令、真实回执与目标观察的边语义不变。

## 提示与反馈

native system prompt 来自固定官方 `build_system_prompt` 与 `build_tool_schema`。仅把 XML 调用说明换为 native function call 格式；原官方日期、行为和批次规则保留。删除项目追加的 frame 来源说明、回执解释、额外结束提醒及扩展验证指引。截图和动作单位仍通过官方 schema 预先声明，完整 frame 元数据留在审计。

原任务用官方 `build_instruction_prompt` 放在首个保留观察中，使用官方 `previous_actions_text` 在历史被裁剪后补入先前动作描述。后续观察不重复添加自定义任务提示。保留原 assistant、reasoning、native call ID，并逐 ID 配对工具反馈。

模型收到的直接反馈通过独立投影产生：

- 有正常执行接口返回：`{"status":"returned"}`；不宣称动作效果成功。
- 没观察到执行：`{"status":"unobserved"}`。
- 实际异常或控制器错误：实际错误字段、非零 `returncode` 或原错误 `status`，不附整个返回对象。
- 原用户模拟器答复：实际 `user_response`。

完整 commands、stdout、controller receipt、env info、耗时、截图与原解释继续保存在 JSONL / SSE / 官方轨迹中。实验组另保存转换库，按各自记忆策略选取证据形成可选上下文。baseline 不创建或查询该数据库，完整审计也不会作为额外反馈回灌。

完整、格式合法但官方编译拒绝的候选，在修复请求中保留原 assistant，并用其真实 tool ID 配对最小验证错误。截断或身份结构不合法的候选只保存原证据，不制造有效 assistant/tool 历史。修复文本只说明实际错误和协议所需的完整格式，不追加任务策略。整批候选仍由官方编译器一次校验，拒绝后没有部分执行。

## 上下文、时间与成本

默认 `context_reserve_chars=0`，不为了实验组预先缩小 baseline 历史。可选上下文不得挤出 actor 已保留的历史，也不截断 JSON 包；包本身或总请求超过共同上限时整包省略并留证。未实际发送的包不推进事件/视图送达游标。非文本或不可用的上下文不会阻止 actor。

三组 actor 都在可选分析完成后获得完整的相同执行期限、输出额度和修复池。max/16K 仍指 max、每个 actor 请求16000、actor 整步32000、最多两次动作修复；connect15 / idle120 / generation600 / transport900 / actor 整步930秒保持。网络尝试与语义修复分开计账，失败 usage 也累计，缺失费用保留未知。

TaskViews 分析另有独立账本和截止时间。当前 max/16K 的分析单请求4000，分析池可用输出16000，截止窗口315秒，最多两次跨角色分析修复。分析失败后同一 actor 继续运行，分析修复和输出不会减少 actor 额度。UI-KOBE-like 没有额外分析 LLM。必须同时报告 actor 与分析费用，以及总墙钟；这不是三组总计算预算相等的比较。原 v6 共用整步预算的封存结果不按新口径重算。

## 官方复用与剩余差异

官方固定 checkout：`xlang-ai/OSWorld-V2@3d778a3c9a34a079316f70df023b166700445792`。

| 部分 | 来源与处理 |
|---|---|
| 截图处理、坐标投影、schema、动作编译 | 直接调用固定官方函数；同一 frame，默认 absolute 1920×1080；不猜单位或夹取 |
| commands、控制器、runner、reset、评分和素材 | 官方原件；批次逐条 `env.step`；官方 result 定义成绩 |
| official-xml 的 actor | 三组均继承官方 QwenAgent `predict`、提示、历史、XML 解析和动作修复；薄 K3 层兼容参数、SSE、空字段和原响应历史 |
| native 的 actor | 项目统一协议桥接；共用官方提示、历史辅助函数和编译器，但其 `predict`、native ID 历史与预算封装不是原 XML Agent |
| 上下文恢复 | XML 保留原官方 context rescue / 摘要请求；native 按整轮裁剪原 assistant/tool 对，不新增摘要 LLM；这两条协议不能混作同一组 |
| 配置、重试、预算与结束 | 三组统一，但保留此前声明的 K3 参数与资源政策；不声称完全等于官方 CLI 默认值。按用户要求关闭自动 terminal judge / endless retry，显式 terminate 或官方决策上限进入原评估 |
| 被动记录和可选记忆 | 项目实现；baseline 仅完整审计，实验组单独转换图和记忆变量 |

因此，此修订减少了 baseline 的非协议策略，不能宣称所有剩余差异都只有 API 地址替换，也不能承诺框架统一后 LLM 必然完成任务。

## 验证与迁移

离线测试使用固定官方编译器和模拟供应商/环境，核对三组实际 actor payload 一致、baseline 没有转换数据库、真实回执与后观察仍完整、模型直接反馈最小、工具 ID 配对、分析额度隔离、可选包遗漏后游标不推进，以及固定官方源码未改。运行在单个注册的 Ubuntu 128 MiB / 零 swap scope；没有调用模型 API 或操作 GUI。

最终完整回归为 **614 passed、0 failed、Ruff 通过**；官方与项目运行源码在验证前后未变。scope 的采样 peak 为134217728字节，`oom=0 / oom_kill=0`，达到 cgroup 上限的 `max` 计数不等于 OOM。没有放宽内存或 swap 限制。

验证记录：[最终完整回归](../validation/three-arm-actor-v7-20261007-complete.json)、[阶段定向回归](../validation/three-arm-actor-v7-20261007-targeted-final.json)。新夹具的模块模拟、日志根目录及断言问题保留在 [attempt1](../validation/three-arm-actor-v7-20261007-attempt1.json) 和 [第二次检查](../validation/three-arm-actor-v7-20261007-targeted.json)。[首次完整回归](../validation/three-arm-actor-v7-20261007.json) 的六项失败来自旧测试要求逐轮重复任务提示；修订为核对首个保留观察的官方任务文本。

后续验证进程在两个不同测试切换点发生 `os.getcwd` 初始化 ENOENT，[第一次中断](../validation/three-arm-actor-v7-20261007-interrupted.json) 和 [第二次中断](../validation/three-arm-actor-v7-20261007-interrupted2.json) 保留未完成状态与原 state hash。精确的文件系统原因未确认；仅在 exec 前设置项目 cwd 仍不充分。验证工具现会在切换前和新解释器入口从文件系统根重新进入项目目录，[专项验证](../validation/three-arm-actor-v7-20261007-worker-check.json) 的208项通过，包含删除当前临时目录的复现和两个中断处的测试。上述中断不是在线模型失败。最终回归另覆盖 XML 摘要费用保留、同观察分析只做一次、图读取失败降级及实际包送达游标。

准备和运行入口只接收新 v7 三组计划，arm 为 `baseline` / `ui_kobe_like` / `taskviews`；同一个计划固定协议、profile、坐标与截图契约、记录权限和成本口径。旧计划在资源检查/启动之前拒绝，不继续旧目录或自动重跑。已存在的前驱必须完成源码审计和资源清理，得分不作为后继启动门槛。

新的在线实验需要新冻结源码、配置和实际链路验证；选择 XML 还需新源码对应的 K3 XML/历史兼容证明。现有两臂 native smoke 和 v6 正式结果仅作为历史证据。本次提交不启动模型任务、不修改旧实验原件。
