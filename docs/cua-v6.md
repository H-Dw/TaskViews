# 执行转换图、任务模块与官方 Agent 迁移

日期：2026-10-06。修改基于本地 v5 commit `31af44e`，原 UI-KOBE-TaskViews 已封存八组实验保持原样。本版本没有任务评测成绩。

## 两臂共用的执行记录

`TransitionJournal` 是被动 SQLite 事件存储，每个 episode 独立建库，插入事务采用 FULL 同步，禁止修改和删除事件。只记录官方 `predict`、`env.step`、控制器回执、`evaluate` 与 `close` 已产生的数据；不再请求截图，不执行额外动作，不调用页面匹配模型。记录层异常只生成警告，保持官方返回值和原异常。

| UI-KOBE 边语义 | v6 记录 |
|---|---|
| 源节点、目标节点 | 每个前后观察各有不可覆盖的版本 ID；原图、官方处理后模型图按 hash 保存。逻辑页面 ID 另作可选注释 |
| 执行动作 | 每条官方 command 独立事件，关联已编译完整决策、tool/command 索引和实际回执 |
| 对应指令 | 原始 instruction 和引用、完整模型响应、可选 local instruction；不把模型意图当作已执行 |
| 目标观察 | 官方 step 原返回的截图引用；缺失或异常明确标记 gap，不沿用旧帧或补造目标 |
| 可选 schema delta | 仅在同一可见页面的两个注释都有 schema 时派生；区分字段缺失与 null，保留两端证据引用及 model_proposal 等级 |

相同页面或相同动作的多次尝试不合并。官方 WAIT、DONE 没有命令接口回执时保留空回执；异常后尚未执行的 command 记录为 unexecuted，不产生假边。`effect_status` 始终 unknown，官方评分另列事件。

关闭时导出 `.ui-kobe.json` v2，UIKobeAdapter 按单次配对事件转换。旧 UI-KOBE 的平行可选数组仍以 aggregate_unpaired 保留，不猜对应关系。没有目标的事件保留在原库和 adapter.gaps，不能作为有完整两端的图边。可以用 `open_readonly` 重建导出。

## 任务模块位于转换图之上

TaskViews 将记录投影到现有 TaskGraph：观察、执行转换、用户模拟器原回答、分析注释和评估事件都有原记录引用。持久语义投影去掉动作坐标；原动作、图片与几何留在审计层，当前 frame 仍走官方截图契约。

控制器基于已有任务对象、关系、子目标选择 needs，以 stage 与对象 anchors 建立稳定任务模块。模块记录 goals、输入 anchors、模块依赖、执行产物引用、缺失证据和角色报告。切换模块保留先前模块为 paused；页面变化不自动创建“完成”判断。执行产物仅证明产生过记录，不证明目标达成。verifier 的 verified 是模型提议，不改为 done，也不授予官方分数。模块及投影游标持久化，重复读取已处理事件不会重复写图。

这是第一版任务模块管理。模块依赖来自已有 module anchors，尚未自动执行依赖调度；没有程序化验证的子目标不会被自动标为完成。完整原件保留，提示投影有明确容量和 omission，不承诺将全部历史塞进上下文。

## 自适应 TaskViews 的更新

每次预测先读新的执行事件，再处理同一张官方模型截图。即使感知失败，前后截图、动作和回执仍已由公共记录层保存。感知可为观察添加逻辑页面和可见字段；注释按精确模型图 hash 绑定，不做相似页面匹配，也不推断动作单位。

控制器看到转换历史和模块库存，按消费者实际可读 anchors 选择语义视图；planner、verifier 在限定视图内提供非执行报告。模块最近转换、changed_execution_ids、图 revision 和角色 view_change 随当前上下文交给 actor。视图增量使用 `task_view_delta`，只在成功传送 actor 请求后推进内存基线；重启后重新提供完整投影。actor 仍收到完整当前视图，避免其官方历史裁剪后缺少 delta 基线。已完成 views 在同一步修复时复用，新截图重新生成。

模块提示包最多 6000 UTF-8 字节，优先当前模块，遗漏逐项披露；完整模块状态和 SQLite 事件仍可审计。语义视图为模块和角色报告预留空间。原目标与当前截图始终保留；可选上下文失败降级 unavailable，不制造动作、回执、补偿或结束信号。

## 尽量原生的 baseline

参照为 [固定版本官方 QwenAgent](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/mm_agents/qwen/main.py)，关键文件逐字节核验。`OfficialK3Agent` 继承它，未替换 `predict`、system prompt、`build_messages`、context rescue、XML parser、完整批次 compiler、原修复提示或 terminal 处理。`_process_observation` 调用原方法并返回同一个截图对象，仅为传输建立整步账本和 frame 元数据。`_messages` 在 baseline 返回原方法结果，TaskViews 仅插入当前回合的可选数据上下文。

薄 K3XMLClient 处理供应商 sampling/output 参数、SSE、usage 和 Completion 映射。官方历史存放带 think 的 rendered 文本；实际 K3 请求恢复该次响应的原 reasoning_content/content，修复历史也如此。缓存按精确 rendered 身份区分；冲突或缺失明确报错，不猜历史、不拆模型思考文本。K3 没有 Qwen tokenize 接口，短超时恢复仅使用明确的保守估计；费用仍取实测 usage。

相对于官方默认配置，试验仍显式关闭 terminal judge、endless retry、summary folding 和 zoom，保持此前用户的无隐藏自动 DONE 要求。500 轮、20 图、折叠步幅、截图/坐标模式都是计划参数。XML 的历史/context 判断使用官方流程，native 组的历史封装单列，不能声称二者无差别。官方 XML 历史中的 success 是合成占位；共同记录库中的实际回执是另一类事实。

传输仍有共享的 930 秒整步期限和实测输出账本、600 秒生成/900 秒传输上限。原 XML 修复循环决定是否修复；记录层观察其修复 payload，不另设语义动作 gate。length 或结构不完整的 SSE 不执行。TaskViews 分析采用有界 JSON 修复且为 actor 留出时间与输出，均不刷新整步期限。

## 迁移证据与分组

离线测试调用真实固定版本 QwenAgent，验证继承方法、原 prompt/历史一致、官方坐标拒绝后原 XML 修复、原 K3 推理回传、TaskViews 仅补充当步上下文及分析降级。真实 `probe_k3_official_compatibility.py` 再检查两个合成截图回合的服务器响应、第二回合发送的 assistant 字段和同图契约。所有编译动作不执行，不创建 VM，不评分；官方 success 历史文本因此也不能被描述为执行回执。

准备 official-xml 新计划时必须冻结当前 source/profile/CUA 对应的 live compatible 证据。探针缺凭证、网络失败或 length 只能说明未验证，不能宣称 K3 不支持 XML。未知响应格式不自动改用 native。需要 native function calls 时，以新计划预选 k3-native，两臂共用相同 native 适配器和公共记录层，作为单独比较组。

这里只验证接口兼容与代码行为，没有证明新的策略提高了任务成功率，也没有用新代码解释或改写旧实验分数。
