# K3 空字段与被动记录修复

日期：2026-10-07。原 official-xml 四组和 UI-KOBE v4 八组的结果、源码快照与封存证据保持原样。

## 修复与证据

1. `K3XMLClient` 在生成官方 `Completion` 时调用固定 checkout 的 `mm_agents.qwen.client._text`。`content=null`、缺省或空正文按官方规则成为空字符串，reasoning 可取原 `reasoning` 备用字段。原 SSE、usage、原始 assistant 消息及下一回合发给 K3 的历史保持原样。空正文不被变造成 XML、动作或任务结束；完整性、length、协议混用检查继续有效。
2. `record_transition` 将 SQLite 记录类型写入 `journal_kind`，与 `emit` 的事件类型参数分开。修复的是记录写入 SQLite 后事件引用输出的参数冲突。数据库格式、边语义和官方返回值未改；记录失败仍单独留警告，不阻挡执行。

三份真实 actor 空正文 SSE 逐字节复制为测试 fixture，含来源及 SHA-256；回放完整 `[DONE]`、stop、reasoning 和 usage，再走固定官方 `predict` 及下一回合历史。回归确认这些响应可合法返回无动作，后续真实 XML 候选仍走官方编译，不新增无动作修复规则。新增记录测试使用真实 JSONL emitter，核对 SQLite ID、源/目标节点、指令、实际回执和后观察，防止宽松 mock 遮蔽签名错误。

[定向验证](../validation/native-cua-fixes-20261007.json)：146 passed、0 failed，Ruff 通过，固定官方源码未改。运行在单个注册 128 MiB / MemorySwapMax=0 的 Ubuntu scope，峰值 127848448 字节。首次回归的六项失败为新增测试的断言/调用错误，原 [attempt1](../validation/native-cua-fixes-20261007-attempt1.json) 保留；不是在线模型失败。

## 两臂与权限边界

| 项目要求 | 实现与验证依据 |
|---|---|
| 同一 K3 native 适配器 | baseline 为 `KimiNativeAgent`；TaskViews 在同一 actor 路径插入可选上下文。相同 API tools、tool_choice、原目标、共享 ledger 和原响应历史；不按输出切换协议 |
| 截图与坐标预先统一 | 两臂冻结 absolute、模型图 1920×1080。schema、提示、图片、frame 与编译参数来自同一契约，官方 `project_point` 映射到 guest；不猜单位或夹取坐标 |
| 官方执行与评分 | 完整 native 批次先转原 `ToolCall`，交给未改的 `translate_tool_calls`；原 runner 逐条 `env.step`，控制器和原评价不变 |
| 共同被动转换边 | SQLite 保存 source/target、官方 command、instruction/ref、native call ID、真实 receipt、target_observation/ref。可选 schema delta 保留两端注释及模型提议等级 |
| TaskViews 只管理任务信息 | 读取共同图，保存/检索目标与依赖、证据和任务模块，维护投影游标，按变化分发可选上下文；不是独立执行器 |
| 证据分级 | 模型 proposal 和 verifier 的 verified 留模型等级；receipt 证明接口执行返回，后截图作为独立观察。`effect_status=unknown`，view revision 和模块切换不自动标任务完成 |
| 执行权限 | planner/verifier/view controller 只返回有界 JSON；不注册 CUA tools，不修改 actor schema、坐标单位或终止策略。只有 actor 的显式 terminate 或冻结官方决策上限进入结束流程 |

native 组使用项目的 native 响应与历史封装，不能称为原 QwenAgent XML `predict`；两臂共用该适配器，TaskViews 的变量限于可选任务上下文。官方截图、坐标投影、编译、控制与评分继续复用。

## 真实动作链路验证

新建独立计划，使用 Task059 原任务和原官方 reset；预先声明 max/16000、整步32000、actor reserve16000、分析4000、absolute 1920×1080，baseline 后 TaskViews，禁止并行 VM 和整任务自动重跑。

`cua_smoke` 仅允许预先设置 1..10 个官方决策，当前选择 3；通过原 runner 的 `--max_steps` 实现，正式 evaluation 保持 500。短程结果单独标记 `benchmark_comparable=false`，评分即使由原 evaluator 产生也不用于比较正式任务性能。

链路通过必须有真实原生 actor 调用、完整官方编译、实际 CUA 接口回执、动作后原截图，以及数据库中对应转换边；TaskViews 还核验消费这些记录、模块及变化上下文。服务启动、HTTP200、模拟动作、WAIT、模型 verified 或单位合法均不能单独证明通过。

完整 API/SSE、所有已知/未知 usage、网络重试与语义修复、模型与框架异常、源码/plan、资源样本和最终 unit/VM/overlay 清理均留在新的验证目录。未验证前不声称链路通过，旧心跳和旧封存目录不复用。
