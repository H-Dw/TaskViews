# TaskViews v8：Task059检查点运行

固件兼容：固定Docker镜像原先通过可写raw pflash加载UEFI。检查点模式在启动前将同一份固定固件字节转换成qcow2，仍连接pflash设备，使固件写入与guest RAM、任务磁盘共同保存。首次reset前验证实际可写盘格式及整机save/load/delvm；不改变官方镜像或已初始化guest。

这是用户于2026-10-09授权的新TaskViews修复运行。旧v7六组的计划、原始证据、成绩和封存记录均不修改。新运行改变了分析配置与恢复策略，不用于声称旧三组同条件比较。

执行端保持KimiNativeAgent、原官方提示与1920×1080绝对坐标、完整批次编译、控制器、任务首次reset及最终评价。actor effort=max，每请求16000，独立32000输出池/930秒/最多2次语义修复。分析端effort=low，每请求至多4000，独立available16000/315秒/最多2次语义修复。费用按真实唯一request_id保存；unknown usage保持NULL，恢复分段的额外请求计费保留。恢复已完成步数累计到500，不重新获得500步；恢复请求会开始新的有界请求尝试，不退回此前费用。

必需上下文只保留原任务契约。模型候选与旧动作语义仍完整留在图和审计中，通过可选视图读取，不无限加入必需事实。合法锚点表独立传入控制器，不允许预算省略；未知实体ID严格拒绝，并在有界修复反馈中给出实际合法ID。视图空间由当前必需内容的实际字节数计算，删除固定20k二次扣除。分析失败、非法锚点、当前帧证据拒绝、未确认命令和检查点损坏均停止后续actor动作；没有静默降级为baseline。

HTTP 429保存至多8192字节的去凭证错误正文与白名单限流响应头，按照Retry-After等待，至少60秒，仍限制最多2次传输尝试与原deadline。等待超过本次deadline时暂停；actor不会在分析限流后立即继续请求。恢复必须满足暂停记录的最早重试时间以及原资源准入要求。

每次决策读取前保存QEMU整个guest的内存与所有可写qcow2磁盘快照，并保存原始输入截图、actor历史/reasoning/tool IDs/反馈/步数、执行SQLite事务备份、TaskViews图与模块游标。每个检查点使用独立UUID、完整文件hash与原子提交；保留最近3个可用快照。旧快照的manifest/hash与全部原始运行证据保留，过期payload仅在检查点目录内删除。检查点意味着状态一致性，不代表界面语义正确或任务成功。

QEMU首次启动时显式使用migratable=on,-invtsc，启动后核验两CPU实际属性并在首次官方任务reset前验证save/load/delvm；任何不兼容在任务初始化前拦截。首次模型/API/GUI动作前再进行实际save/load回环，并提交第0步检查点后暂停进程，验证同一VM的完整进程续跑后才开始推理，失败则保留现场暂停。运行中的资源门槛依旧为adjusted>=4/C>=35/D>=10 GiB，启动及续跑为adjusted>=5/C>=45/D>=12 GiB；VM3GiB/guest2GiB/2CPU/service2GiB/aux128MiB/Swap0不提高。门槛中断请求停止该worker及VM CPU，保留快照和overlay；ExecStopPost不删除可恢复现场。异常后API/控制器/失败图分支的原始证据保留。

恢复验证检查点所有文件hash、任务/actor契约、VM完整ID所有权、官方源码与素材、修复离线测试以及资源/冷却条件。重新连接原VM并loadvm；恢复actor、环境动作历史和累计计数，执行SQLite复制到新的恢复分支，官方结果写入独立续跑分段，原失败分支不覆盖。原官方运行循环仅在内存中改变step_idx与global_action_index的初值；官方源码磁盘字节不变，恢复路径不调用env.reset。原reset只在新运行第一次启动执行。

操作入口是scripts/taskviews_recovery.py的inspect、pause、resume。所有辅助操作必须使用Ubuntu-24.04官方venv Python，单128MiB/Swap0 systemd scope并require_scope登记。resume必须提供修复原因和当前源码通过的validation.json；可以明确选择最近3个仍可用的checkpoint tag，否则默认最后安全边界。原失败paused记录、resume请求、修复计划和旧manifest分别归档，不通过删除错误日志“修复”。

巡检每60分钟读取新运行实际状态。无变化或资源/限流等待保持安静；异常时读完整原证据，停止尚在运行的worker，做具体修复与回归验证，再从相应保留检查点续跑。禁止新建完整episode、改变原任务目标、人工GUI、用官方评分答案指导actor、提高资源上限、猜坐标或绕过锚点权限。仅任务官方评价、终止审计、最终资源清理完成后暂停巡检。

局限：这套恢复目前限定Task059本地guest，不能撤销Task046外部网站的副作用。协议/引用/帧绑定异常可自动拦截；所有模型对截图语义的误读无法仅靠格式校验完全识别，仍需巡检原截图和证据。若VM和磁盘快照同时丢失，或所需节点已超出3个保留快照，不会擅自从头运行。
