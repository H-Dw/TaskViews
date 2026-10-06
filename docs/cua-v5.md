# 共同 CUA 底座的实现与边界

日期：2026-10-06。基于原 UI-KOBE-TaskViews 已封存八组实验的接口审计，修改发生在独立源码目录。

## 保留与复用

| 层次 | 新路径 | 说明 |
|---|---|---|
| 截图 | 官方 `process_screenshot` / `ProcessedScreenshot` | 两臂所有角色共用 frame；记录原图/model 尺寸、原图 hash、bbox/动作单位 |
| 动作定义 | 官方 `build_tool_schema` | 根据同一 frame 生成；不另设工具数量、keys/text/time 范围 |
| 动作编译 | 官方 `translate_tool_calls` / `project_point` | 完整候选一次校验；commands 原样由官方 runner 逐条执行 |
| 操作提示 | 官方 `build_system_prompt` | 只替换 XML 输出格式为 native 函数调用；保留日期、批次依赖、singleton 与验证规则 |
| 历史 | 官方 `folded_prefix` + native 消息封装 | 与官方折叠时序一致；保留原 assistant/ID/实际反馈，裁剪整轮 |
| 执行/结束/评分 | 官方 runner、DesktopEnv、Controller、task reset/evaluate | 不写另一套 GUI executor 或答案判断；终止 judge 继续禁用 |
| K3 | 原生 SSE 与供应商字段适配 | 原 reasoning、工具身份、完整响应、length、所有 usage 保留 |
| TaskViews | 现有任务图/角色范围/投影 | 非执行建议；没有官方等价模块可替代，故保留为实验变量 |

默认选择官方 absolute 模式来避免模型额外进行 0..1000 换算。这是新的预先声明协议，并非对旧候选作补救性转换。若切换 relative，必须准备新计划；固定尺寸与 relative 不兼容时在请求前拒绝。投影直接使用官方实现。

## 修复与上下文政策

官方校验错误分类、具体数值和范围现在进入修复反馈。完整候选未执行的事实明确给模型；错误原件留在 SSE/遥测中。没有虚构 assistant 或工具回执，也不强行把失败回执判成框架终止。

分析和 actor 各有一个最多两次修复池。分析四个角色共享自己的两次，不是每个角色都获得两次。原整体 deadline 和输出额度不刷新；actor 每次传输仍按剩余额度申请。分析截止于整体截止前的 actor generation + connect 预留，留出 actor 完整生成窗口。输出预留是一次完整请求的空间，不保证支持耗尽整次 cap 后的全部修复。

旧 byte-based 128000 旧文本规则改为可配置的官方默认上下文阈值：总 payload 10000000 字符、文本 120000 字符、粗估文本 100000 token。native 计数也包含 reasoning、函数参数和真实工具回复。两臂先为可选当前证据预留相同 32000 字符，再裁剪共同历史。XML 文本抽取/成功占位不适合 native，因此不直接调用官方 XML history/context 重写函数。

不实现摘要模型、无限恢复、zoom 和 terminal judge；开启这些选项会明确报错，其纯调参字段在 effective config 中标记 inactive。日期采用 runner 赋予的任务日期。坐标/历史/超时/修复配置均实际透传，未知选项不静默忽略。

## TaskViews

业务 schema 检查进入角色的有界修复循环；感知结构检查复用 TaskMemory 的纯校验方法，之后依旧由原内存层执行证据准入、geometry/credential 拒绝和事务。观测 bbox 允许原有“无效则遗漏并记录”策略，但绝不替 actor 自动点击或转换动作单位。

`consumer_allowed_anchors` 来源与范围检查相同的 `_reachable`，仅提供有界可选子集，明确记录遗漏。全局库存不代表消费者权限。无效 needs 仍拒绝，具体原因进入修复；不放宽范围来提高通过率。

分析修复后依然无效、容量不足或达到其截止时间，就记录 unavailable；原目标/图片继续给 actor。同一步 actor 重生成复用已完成 views；新截图清理当步缓存。规划/验证提议不认证任务结果、不触发自动补偿或隐藏 DONE。

## 官方结束流程与资源清理

被动 hook 记录 running / evaluating / evaluation_returned / closing / closed；官方 runner 保持调用顺序、返回值和原异常。遥测或 phase 写入失败只警告；缺失/损坏的 phase 证据不授予 teardown 豁免。评价返回不等于已写出有效 result.txt，审计依旧检查官方持久化结果。

supervisor 在活跃阶段继续 adjusted 4 GiB、磁盘、swap、OOM 与硬限制检查。官方 close 开始后，VM 释放是正常生命周期；RAM adjusted 不再被用作“活跃任务失败”，磁盘/swap/OOM/硬限继续检查，teardown 限时 120 秒。仅在可信 close 阶段允许 owned Docker list/reload 的 404；活跃 404 仍抛异常，不屏蔽其它 Docker 错误。丢失容器的 usage 不补造，不使用历史峰值/硬限作 memory credit。保存真实 runner exit code，退出后依旧逐项 cleanup/audit。

原有所有资源硬限和准入值保持。为了支持当前接口修订，Task046 需要新的源码对应准入证明；本次没有运行 setup 或模型评测。

## 验证与解释限制

离线测试覆盖两种单位、不同原图/model 尺寸、官方动作等价、完整批次拒绝、具体错误修复、角色业务 schema、允许 anchor 范围、actor 预留、native ID/反馈/折叠、结束和 Docker teardown 竞争。测试使用真实本地官方编译器、模拟 SSE/资源；官方源码完整快照前后比较不变。

最终 554 项离线测试与 Ruff 通过。官方关键文件逐字节等于声明的固定 HEAD，完整官方源码快照在验证前后相同；项目运行源码也保持相同。测试和报告始终在一个注册的 128 MiB / 零 swap scope 中。开发中的旧断言、测试依赖遗漏、验证器内存叠加和日志兼容问题均有保留说明，见 [验证记录](validation.md)；它们不是新模型评测失败。

接口修改只能减少单位失配和框架干扰，无法证明视觉定位或任务分数提升。两臂 actor 仍直接看图，TaskViews 上下文也会影响视觉注意，因此这是共同操作接口上的端到端比较，尚非纯粹规划推理的单因素实验。严格隔离 planning/grounding 需另行冻结共用低层 actor；本次不新增 grounder，不使用评价答案制作定位规则。
