# 离线验证记录

2026-10-06，最终提交版本验证开始 10:08:48 UTC，结束 10:12:14 UTC。机器可读记录：[validation/offline.json](../validation/offline.json)。

结果：554 passed / 0 failed / 0 skipped，Ruff exit 0。测试使用 Ubuntu-24.04 的官方 OSWorld venv Python 3.12 和已有开发依赖；每个测试文件完成后替换解释器，同一个 PID 和同一个注册 scope。MemoryMax 134217728 bytes，MemorySwapMax 0，峰值 134217728 bytes；memory.events 的 max=835、oom=0、oom_kill=0。max 是触及限额的计数，不能解释成 OOM。

验证没有启动评测 service/VM、操作 GUI 或调用真实模型 API。HTTP/SSE、用户交互、执行回执、资源释放使用模拟数据；官方截图处理、schema、动作编译和折叠函数使用外部固定源码的真实实现。

覆盖包括：

- absolute 与 relative、三种原图尺寸、显式不同 model 尺寸；同一 metadata 驱动图片、schema、提示与官方投影。绝不按候选数值猜单位；非法批次整体拒绝。
- 冻结配置在两臂实际构造器中相同，官方 runner 参数与计划一致；缺失契约的旧计划在资源检查前拒绝。
- 原生多工具与一工具多命令，原 assistant/reasoning/tool_call_id、真实失败回执归属、整轮历史裁剪及官方折叠时序。
- TaskViews 四角色的业务 schema 有界修复、消费者可用 anchor 与原范围检查一致、分析降级后保留原目标/截图；actor 和分析修复池分开，共享费用与整步期限，保留 actor 输出/时间窗口。
- 原生 DONE/FAIL/WAIT/call_user 的官方编译结果；评价与 close 返回值、原异常和阶段顺序；记录 I/O 失败不能阻止官方执行/评分/关闭；活动期 Docker 404 不被吞掉，关闭期 404 不虚构内存 credit。
- 原有 TaskViews、SDK、资源保护、任务 fixture 和集成测试的回归。

固定官方 HEAD 为 `3d778a3c9a34a079316f70df023b166700445792`。关键 images/actions/parser/prompts/history/runner/DesktopEnv/controller 的字节等于 Git HEAD；完整源码在测试前后未变。项目运行源码在测试前后也未变，记录内附哈希。原 UI-KOBE-TaskViews 的七份关键 K3/TaskViews 运行源码哈希与开始时一致；原八组实验和已暂停心跳未继续运行。

开发中间状态保留在本地 ignored 的 validation 目录：第一次验证暴露了旧的默认 relative/128000 byte 断言、遗漏的可选集成源码，以及累计内存下两个旧 SDK 子进程握手超时；该轮无 OOM。补齐源码和显式契约后，驻留报告进程加测试子进程的第二轮确实触发 scope OOM，systemd Result=oom-kill。验证器随后改为同一 PID 的 exec 链；第三轮发现日志 tee 缺少 isatty，被主动停止并保留日志，修复后第四轮完整通过 554 项。最后统一新仓库换行、清理文件尾空行并修正新计划的授权说明，再对最终提交版本得到上述完整通过结果。没有因此扩大资源上限。所有验证过的运行源码工作文件与 Git 暂存内容逐文件相同，避免提交时换行转换改变冻结哈希。

这份记录证明离线接口一致性与回归结果，不提供新的在线任务分数，也不能证明视觉 grounding 或任务成功率提高。复制/更新 checkout 后应重新验证；冻结计划的源码哈希对应实际运行文件，而不是跨机器通用的准入凭证。
