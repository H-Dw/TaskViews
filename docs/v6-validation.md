# v6 验证记录

2026-10-06，最终全量离线回归为 **575 passed / 0 failed / 0 skipped，Ruff exit 0**。记录：[v6-offline.json](../validation/v6-offline.json)。验证使用固定官方 OSWorld venv Python、Ubuntu-24.04、单个注册 128 MiB / 零 swap scope，每个测试文件按同一 PID 的 exec 链顺序执行。

官方与项目运行源码在验证前后未变，官方关键 Agent/history/context/parser/repair/runner/evaluator 文件逐字节等于固定 HEAD。memory.peak 为 134217728 bytes，memory.events 的 max=393、oom=0、oom_kill=0。max 为触及上限次数，不是 OOM。

新增回归覆盖：

- 逐条官方 command 的 source/action/target 配对、真实回执、指令与 tool 身份、未执行尾部和缺失观察；SQLite 禁止修改/删除、关闭导出和只读重建。
- 重复动作与不同指令仍是独立事件；可选 schema delta 区分缺失/null，保留 proposal 等级。
- 任务模块从转换事件记录输入、输出、证据缺口；重载不重复写图，verifier=verified 不提升为实际完成，持久语义排除动作几何。
- 视图 delta 只在实际交付对应上下文后推进；分析 unavailable 或预算省略的视图不被错误确认。
- 直接调用固定版本 QwenAgent 的 predict/原提示/历史/解析/修复；K3 原始 reasoning/content 精确回传、重复 content 的歧义拒绝、非法坐标走官方 XML 修复、length/native 格式错配不执行或自动切换。
- TaskViews 只增加当前可选上下文；同图、原目标及原 actor 保留，跨步读取共享转换图。旧计划、混合协议或未验证 XML 在资源创建前拒绝。
- 被动记录和脱敏异常不能成为执行 gate；原官方返回字段、异常和评分保持。

原有 SDK、K3/native、TaskGraph/TaskViews、资源及集成测试全部回归。离线测试不调用模型、不操作 GUI。

## 实际 K3 兼容探针

探针每次只调用两个合成截图回合的 predict；官方编译出的 commands 全部未执行，没有 VM、task reset、控制器回执或评估分数。第二回合的实际出站 payload 与第一回合原始 assistant reasoning_content/content 逐项比对。SSE、图片、时序、usage 的原件位于各报告 evidence_dir，完整文件 hash 索引随报告保存。

最初的 [low/16K](../validation/k3-xml-low16.json) 和 [max/32K](../validation/k3-xml-max32.json) 均 compatible=true，各两个请求，分别实测 10,347 和 10,925 token，未知费用 0。之后补强公共观察器和视图交付边界，因此这两份原件保留但只证明对应的中间源码；不能作为当前冻结计划的迁移准入。

最终源码的 [low/16K](../validation/k3-xml-low16-final.json) 和 [max/32K](../validation/k3-xml-max32-final.json) 均 compatible=true，各两个已结算请求，实测分别为输入 10,175 + 输出 116 = 10,291 token、输入 10,234 + 输出 212 = 10,446 token，未知费用 0。两次均核对第二回合实际出站原始 assistant 历史与同图契约，官方源码未变；77 份项目运行文件与全量离线验证及提交前源码逐 hash 一致。两次 scope 的 oom/oom_kill 均为 0。

四次探针合计 8 个请求，输入 41,067 + 输出 942 = 42,009 token，未知费用 0；这是接口检查的实测费用，与已封存任务实验分开。准备 XML 计划时同时核对源码、profile、预声明 CUA 与 compatible=true，任何一项不匹配都会拒绝。两回合只能证明被检验的响应和历史兼容，不覆盖长期上下文、所有动作或新任务成功率；native 仍作为独立预选路径保留。

## 中间记录

本地 ignored `outputs/` 保留 v6-first/second/third-validation，以及 v6-full-first-validation 和其逐 suite 日志。首轮发现测试误用了 native 消息布局；首次全量的一个新测试误要求返回元组本身保持对象身份，实际字段与引用均保留。按原官方返回布局修正断言，同时验证未交付视图不推进 delta 基线，最终重新全量通过。中间失败不当作模型评测失败，也没有扩大内存额度。

最初非交互 shell 未载入 K3 凭证，探针在请求前退出；随后沿用既有交互 shell 配置执行，不输出 key。这不代表 K3 协议不支持。所有已发出的初始和最终探针费用分别保存在原报告；没有重写旧实验或将 probe 当作新 benchmark。
