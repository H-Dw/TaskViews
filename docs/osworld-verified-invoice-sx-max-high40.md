# 发票与流水核对：随想 Qwen Max/high 三组比较

用户在 2026-10-15 明确授权：先提交 TaskViews-mini 优化，再使用 `qwen3.8-max`、思考开启 `high`，依次评测 UI-KOBE-like、类似 OSWorld 原生的 LLM baseline、TaskViews-mini，每组最多 40 次 `actor.predict`。

Mini 优化提交为 `2c6662c`；其运行依赖提交为 `edb6d9b`。本次三组接入另行提交，冻结后的计划记录实际项目 commit 和所有运行 Python 源码的 SHA。旧 flash/low、35 轮记录保留。

## 三组差异与共同条件

| 顺序 | arm | 输入与额外上下文 |
|---|---|---|
| 1 | `ui_kobe_like` | 共同 native actor + 最近 8 条真实执行边检索 |
| 2 | `baseline` | 官方风格 system/task/history、native 工具协议、官方 compiler；无扩展检索、Mini 提示或视图 |
| 3 | `taskviews` | 同一 actor + 优化后的 Mini 当前帧指引及 `current / attempts / lessons` 固定视图 |

baseline 使用 `SXBaselineNativeAgent`。它不是官方原样 XML agent：适配层将调用协议转换为原生 JSON tools；官方操作规则、动作 schema、图片/历史折叠、完整批次动作编译和 OSWorld-1 环境/评分保持相同。baseline 的 journal 只供审计，不读取或加入模型上下文。各组正常每轮只有一个 executor 调用，没有额外 planner 或 perception 角色。

共同配置：

- `experiment=sx-max-high40`，随想 `qwen3.8-max`；请求包含 `enable_thinking=true`、`reasoning_effort=high`，SSE 完整返回与真实 DONE 后才允许动作。
- WSL Ubuntu-24.04 从 `SX_QWEN_API_KEY` 读密钥、`SX_URL_SB` 读唯一冻结入口；不自动切换网关、模型、密钥或推理档位。
- 图片保持 1920×1080；预先选择 `relative`，每轴 0–1000，经原官方 compiler 换算为屏幕像素。不会按模型候选猜测或修正单位。
- history20/image1/fold1、text32000/reserve10000、可选 views 总上限 3000 UTF-8 bytes、原 16000 单请求/32000 单步输出预算及原两次语义修复池。
- 上限按 `actor.predict` 次数计，包括空动作；每次决策中的 GUI 命令数量、接口请求和重试另行计数。显式终止或到达 40 次后调用原官方评分器。
- 每组使用独立进程、官方镜像的新 Docker 可写层、新 actor/journal。上一组评分和清理全部完成才运行下一组；不为成绩重跑，不注入旧轨迹、分析结论或标准答案。

## 资源、连接和失败处理

VM3 GiB、actor2 GiB、launcher128 MiB，零 swap。运行器完整依赖集成检查与正式 actor 都使用既有 2 GiB actor scope；巡检仍是 128 MiB scope。之前将完整运行器导入放进 128 MiB 导致的 OOM，不再用作正式 actor 可运行性的判断。

内存保护沿用用户确认的 `verified-physical-free2-owned-accounting-v1`：Windows 真实可用物理内存必须大于 2 GiB；“排除项目占用后的预算余量”另记，不能替代真实余量。只核算本次 actor、已验证 PID 的 launcher 和精确 run label 的 VM，保留磁盘 C/D 45/12 GiB 阈值。

随想的大图上传等待从 30 秒调整为 120 秒，仍受原 600 秒生成、900 秒传输总期限及 930 秒单步期限约束；其它 provider 保留原上传等待。此项解决上传等待过短的限制，不宣称能修复远端中断。保留原有有界网络重试、原始阶段追踪、配额错误立即停止和完整响应要求。

每组的唯一所有权标签在计划生成时冻结。进程异常退出后，launcher 仅在标签、镜像和内存配额全部匹配时清理本组容器；清理失败则停止接续并保存错误。没有有效官方评分时写 `official_score=null`。

## 验证与运行证据

启动前需要：相关回归；三组 × 上限/显式终止/空动作共 9 场离线原运行器集成；新模型的 text/大图/native tool/tool reply 在线检查；Mini 正式 `predict` 的四位置定位检查。所有证据必须匹配当前源码、Max/high、坐标合同及 40 轮配置。

本次已经通过 [181 项相关回归及 Ruff](../outputs/max-high40-unit-r2.json)、三组共九场离线集成（`outputs/verified-invoice-sx-max-high40-validation-20261015-v1`），以及 [Max/high 三阶段真实接口检查](../outputs/verified-invoice-sx-max-high40-provider-20261015-v1/report.json)。大图 PNG 为 4,387,662 bytes，编译后目标 `(399,300)`；三次响应均有真实 DONE 和 reasoning usage。离线 0.125 仅是 mock evaluator 哨兵，任何 arm 的正式分数均不能据此填报。首次单元验证选错了一个测试文件名，其余 132 项通过；完整正确列表的最终报告为上述 r2，旧失败报告保留。

Mini 四位置定位的本次证据路径为 `outputs/verified-invoice-sx-max-high40-grounding-20261015-v1/report.json`；其 `complete` 字段必须为 true，随后才能满足启动条件。

运行目录计划为 `runs/verified-invoice-sx-max-high40-20261015-v1`。本文记录配置，实际进度与失败以该目录的 `state.json`、各组 `outcome.json`、`resource-monitor.jsonl`、`console.log` 为准。后续状态同时汇总至 `D:/cua_lty/osworld_verified_setup/运行状态.md`。

只有 UI-KOBE-like 在真实官方 Docker guest 中取得完整有效模型响应与合法决策后，才启用原 20 分钟巡检。每次有界检查后立即让出；状态无实质变化时保持安静，三组完成或无法自行解决的阻塞后暂停巡检。
