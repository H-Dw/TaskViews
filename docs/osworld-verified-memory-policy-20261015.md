# 发票核对评测：2 GiB真实空闲内存规则

2026-10-15 22:20审计：v5两组均完成35轮和官方评分，各37次内存检查通过，最低采样真实空闲分别4.698GiB和5.908GiB。两组官方得分均0.0，容器已清理、巡检已暂停。见 [最终评测报告](osworld-verified-invoice-sx-flash-results-20261015.md)。

用户在2026-10-15明确要求优化内存保护，并选择“真实空闲内存 >2 GiB，同时记录排除项目占用后的预算余量”。本次采用新策略 `verified-physical-free2-owned-accounting-v1`，冻结到新计划的 `resource_policy` 中。

停止条件为Windows报告的真实空闲内存**小于等于2 GiB**。项目占用单独记录，不会被再次从空闲内存中扣除。另有审计指标：

`排除项目后的预算余量 = Windows真实空闲内存 + 本项目实测占用`

该预算余量不是物理空闲内存；它不能覆盖真实空闲<=2 GiB的停止条件。此前3.736和3.821 GiB的停止样本在新规则下均通过。阈值、指标定义、检查阶段和磁盘要求均写入冻结计划。

本项目实测占用包含当前actor的2 GiB限额cgroup、启动器的128 MiB限额cgroup，以及只带本次 `ui-kobe.verified.run=<run_id>` 标签的VM容器。使用cgroup `memory.current` 和Docker `memory_stats.usage` 的实时数值。父子cgroup和重复容器ID去重；启动器PID需要仍属于声明的cgroup；不把硬上限、guest配置的2 GiB、整个WSL的占用或其他实验容器当成本次实测占用。

在guest构造前、每次actor决策前及原官方评分调用前进行检查。每次将原始空闲、项目占用、预算余量、组件身份、OOM计数和检查结果写入各组的 `resource-monitor.jsonl`；即使余量不足，先落盘证据再停止。日志不加入模型上下文。

VM容器3 GiB、actor2 GiB、启动器128 MiB的硬限制及零swap仍有效。C/D磁盘检查仍为45/12 GiB。本次不改变模型、推理、图片/文本预算、三类Mini视图、35轮上限或官方任务与评分器。

56项相关回归通过，覆盖旧停止样本、2 GiB严格边界、预算回加不能掩盖低空闲、只核算本次容器、父子去重、实际用量与上限区别、PID所有权、无效计数、零swap、磁盘和失败证据持久化；Ruff通过。当前源码的两组共六例离线集成、大图在线接口检查和镜像/依赖预检已重新通过。实际有界cgroup与Docker/Windows计数预检通过，证据为 `D:/cua_lty/osworld_verified_setup/resource-accounting-preflight-v5.jsonl`。

2026-10-15 21:55启动新计划 `runs/verified-invoice-sx-flash-low35-20261015-v5`，模型qwen3.8-flash / low、UI-KOBE-like → Mini各最多35轮。旧目录完整保留，新授权和变更范围见新目录 `rerun-authorization.json`。新在线证明为 `D:/cua_lty/osworld_verified_setup/sx-native-probe-20261015-v6`，离线证据为 `outputs/verified-invoice-sx-flash-validation-20261015-v5`。实时状态见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。

21:58已在真实官方Docker环境取得完整模型响应与动作回执，21:58:30有2个完整响应和2个有效决策。最新采样真实空闲5.346GiB、项目实际占用3.227GiB、审计预算余量8.573GiB；由两条独立cgroup和本次VM的实测计数合成，没有用5.125GiB的硬上限代替实际占用。新目录 `monitor-activation.json`保存证据，20分钟巡检已通过应用工具恢复ACTIVE并收到确认。
