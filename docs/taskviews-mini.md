# TaskViews Mini M0

2026-10-21 默认接口更新：当前 Verified Mini 入口默认使用 [AutoDL / Qwen3.5-397B-A17B](autodl-taskviews-mini-20261021.md)，通过 `AUTODL_API_KEY` 环境变量认证。以下旧版本的模型、接口和验证结果保留为历史记录。

2026-10-21：最新 Mini 迁入 `main`，旧主分支备份为 `backup/main-20261021`。当前准备、启动、恢复和离线验证入口要求 `main`；新计划记录 `source_branch=main`，历史计划的 `source_branch=mini` 保留原值用于审计，仍受原源码与检查点一致性校验约束。

2026-10-20 可选增加[任务级按键联网调研](task-keyboard-web-research-20261020.md)：默认关闭，开启后在新计划准备阶段识别软件、通过 API web search 保存 Markdown，再生成隔离的临时按键目录。准备调用单独计费和记录，正式 actor 保持原 View 预算。下文的历史版本与旧实验条件不包含该扩展。

2026-10-18 当前实现为 `mini_report_recovery_v7`：Mini 单独处理辅助报告错误，同轮请求按完整旧轮重新准入；保留共同的 predict、传输、官方执行／评分和原预算，只有 Mini 使用独立的有界候选循环。报告采用扁平结构，旧 v2 合规报告仍可读取，unknown 不升级。详见 [v7 恢复与离线验证](taskviews-mini-report-recovery-v7.md)。以下版本记录保留为历史。

2026-10-18 `mini_artifact_protocol_v6` 修复成功报告的指引／校验不一致和错误反馈不具体的问题，但未解决长回复触发同轮修复后的输入超限。其实现与当时的离线验证见 [v6 历史记录](taskviews-mini-artifact-protocol-v6.md)。

2026-10-17 当前按键实现修订为 `mini_keyboard_tools_v5`：默认只检索跨软件通用控制，Evince 翻页/缩放、文件管理器重命名与 GNOME 窗口绑定移入显式目录。软件类型、平台和软件名称分别建档，配方保持原生 `action:key / keys:[...]` 格式。四个 View、3000 UTF-8 bytes 与额外角色请求数 0 保持。使用、分类、研究来源和迁移边界见 [按键 tools](../tools/keyboard/README.md)、[索引](../tools/keyboard/index.md)与[检索记录](../tools/keyboard/survey.md)。下文的 v4、v3 与 M0 搭建记录保留为历史。

2026-10-16 当前实现修订为 `mini_artifact_evidence_v4`：四项产物状态默认为unknown；成功终止前需要引用真实观察的公开复核记录，模型报告不冒充独立认证。3000 UTF-8 bytes内优先保留有效操作与后续观察、未解决问题，再放匹配的键盘参考；最大化、最小化、切换窗口和重命名分别处理，无匹配则省略。四视图与额外模型角色数0保持。详见[v4实现与验证范围](taskviews-mini-artifact-evidence-v4.md)。旧v3评测与检查点保持原样，不能静默续跑为v4。

先前 `mini_keyboard_memory_v3` 的231项测试、生成对照及历史运行证据见[键盘复盘](taskviews-mini-keyboard-postmortem-20261016.md)和[auto-research策略](taskviews-mini-auto-research.md)。**以下是旧M0搭建记录，三视图表格和旧验证状态只描述历史版本。**

2026-10-15 更新：当前实现修订为 `mini_cua_feedback_v2`，修复空错误误分类，默认提供重复操作证据，并在正式 Mini 输入中明确坐标与结果检查要求。详见[本次修复及验证记录](taskviews-mini-cua-feedback-20261015.md)。下文保留最初 M0 搭建时的配置与验证记录；最新随想发票任务的 35 轮、0/0 分结果见[正式结果](osworld-verified-invoice-sx-flash-results-20261015.md)，不应与旧 Task059/Pinggy 配置混用。

Mini 最初在 `mini` 分支实现，当前代码位于 `main`。它复用共同 `KimiNativeAgent.predict` 和机械提取的 Qwen provider，不继承完整 TaskViews agent；v7 的 `generate_candidate` 只在 Mini 内分流错误并重做输入准入。执行仍由原 native tool schema、官方完整批次 compiler 和 controller 完成。没有模型驱动的分类、perception/controller/planner、DAG、语义图或 pointer guard。

本次交付是代码搭建与离线验证。没有启动新的正式 episode、VM、模型 API 或官方评分；当前 V12 继续暂停。V12 原230已执行而安全检查点229，不能把 Mini 装入旧 episode 或用恢复229重放230。

| 入口选择 | 实际 actor | 可选上下文 | 正常额外角色请求 |
| --- | --- | --- | --- |
| `mini_fixed_v1` / `taskviews` | `QwenMiniTaskViewsNativeAgent` | 固定 `current`、`attempts`、`lessons` | 0 |
| `mini_fixed_v1` / `ui_kobe_like` | `QwenTransitionNativeAgent` | 原 UI-KOBE-like 最近8条真实边 | 0 |
| 默认 `full_checkpoint` / `taskviews` | 原 `QwenTaskViewsNativeAgent` | 完整 TaskViews；原 opt-in feedback 策略 | 原独立角色链 |

每份 Mini 冻结计划仅选择一个 arm，未来同条件对照要使用两个独立获授权的计划。旧 Kimi 成绩不能当作这个 Qwen 对照的成绩。未知 profile、混入完整版 feedback、扩大预算、外来视图契约均会在运行前拒绝。

## 固定 views 的行为

`current` 绑定当前原 frame/observation/task-input ID 和原图 SHA，复用原 native 消息中的图片；不重复图片或任务、不生成 bbox 或数学事实。`attempts` 按真实 SQLite `event.seq` 查询最近4个原操作，保留原工具 ID、参数、前后观察、回执和错误。`lessons` 查询真实协议/controller 错误及有原件来源的 actor prose，分别标注 `execution_error_record` 与 `model_intent_proposal`；prose 不自动成为已确认应用失败。

可选包最多3000 UTF-8 bytes，且受共同8KB和实际32K上下文余量限制。每条投影整体保留或整体省略，记录完整省略数；原件始终在 journal。包的 SHA、来源 ID、frame、实际送达与后续修复请求的整包省略分别记录。视图容量不足不删除原历史、不加 API、不阻止本来合法的 native actor 请求。

送达回调在 provider 返回完整响应后记录成功。传输失败仍须结合原请求及未知使用账本判断；`delivered=false` 不代表请求未发送或费用为0。

当前帧/任务/journal 身份不一致、原命令未确认、完整 native 请求超限属于核心异常，下一模型请求前安全暂停。M0 **未实现**目标级 focus→type→submit gate，也没有对矛盾建议进行语义裁决；这些是 M1/L2 的工作。单 actor 和固定读取层减少信息源与角色冲突，不能保证模型本身不重复错误。

## 配置和检查点

共同配置是 [cua-mini-fixed-v1.json](../configs/cua-mini-fixed-v1.json)：absolute 1920×1080、history20/image1/fold1、text32000/reserve10000、views8000、payload2000000/rough12000，原两次语义修复不增。Qwen 使用原 `qwen3.8-max` 节点、non-stream JSON、thinking=false、temperature0/top_p0.9、单次输出16000/整步32000与原传输期限。密钥只从 Linux `QWEN_API_KEY` 读取。

Mini 检查点仍调用共同整机 RAM/全部可写 qcow2 的原快照机制，同时原子保存 actor 历史、pending/tool ID、累计步数、真实 journal 的事务备份和固定视图版本/送达游标；不建立完整语义图。恢复保留旧失败分支，清除旧 frame 的派生包。Mini、UI-KOBE-like 和完整 TaskViews 的检查点 profile 不能互换。

Mini 恢复还读取原 journal 与同 episode 的续跑 journal：检查点之后已有真实命令则拒绝回退，不能把已完成操作重放。原 journal 缺失或无法验证同样失败。物理快照标签、SHA、最近3个保留、同 VM/reset=false、资源门槛与原累计500决策规则继续由共同恢复器执行。正式集成目前限定本地 Task059，不能冒充远端网站副作用回滚。

## 后续离线测试

每次先切换分支，选择新的 proof 路径；已有 proof 和失败记录不要覆盖。

```bash
cd /mnt/d/cua_lty/OSWorld-K3-TaskViews
git switch main
PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope \
  --property=MemoryMax=128M --property=MemorySwapMax=0 \
  /home/dawei/osworld2/OSWorld-V2/.venv/bin/python scripts/validate_mini.py \
  --dev-site-packages /mnt/d/cua_lty/UI-KOBE-TaskViews/.venv/lib/python3.12/site-packages \
  --ruff /mnt/d/cua_lty/UI-KOBE-TaskViews/.venv/bin/ruff \
  --output outputs/mini-next-validation.json
```

`validate_mini.py` 先验证128MiB/Swap0注册 scope 和当前分支，再以同 PID `exec` 进入原验证器。默认全仓回归；局部测试可用 `--tests test_mini_profiles.py test_mini_long_trajectory.py test_mini_taskviews.py`。每个 suite 顺序运行，新解释器替换旧解释器，没有重叠辅助 Python。

新增测试包含原帧/任务身份、空/超长 view、完整工具错误与原 IDs、原修复池、profile/manifest/branch 冲突、完整检查点状态、拒绝后退重放，以及500次 mock predict 在250步恢复后继续至500的真实 journal/原 compiler 路径。模型、GUI/controller、QMP 都是离线 fixture；这个测试不产生 OSWorld 成绩，也不证明真实整机恢复或任务产物成功。

## 未来正式准备入口

入口已支持：`scripts/osworld_native_experiment.py prepare` 添加 `--taskviews-profile mini_fixed_v1 --qwen-arm taskviews`（对照用 `ui_kobe_like`），其余选择 `--task 059 --agent-interface qwen-native --checkpoints --cua-config configs/cua-mini-fixed-v1.json`，提供当前通过的 `--validation`、原 provider compatibility 证据和新的 `--root`。源码必须验证后 commit、Gitclean；准备/launch/resume 都检查当前分支为 `main`。

准备不创建 VM，也不代表获得新 episode 授权。本次没有调用 prepare/launch/resume。未来获得新实验授权后才准备并启动独立 Mini episode；正常 native terminate/原500上限后才能官方评测。完整流程与原 score≥0.2、原 cleanup/audit 完成才算达标。

## 后续叠加

按[原路线图](taskviews-mini-roadmap-20261012.md)先验证 M0 的真实产物，再接 M1 同调用短意图/当前事实的依赖检查（先 shadow 后 gate），L2 单事件 planner 与采用/拒绝生命周期，随后依次接入产物 DAG、被动语义记忆、固定读权限、自适应 views、按需数学 verifier。每层独立 feature flag 与冻结 profile，关闭该层时必须保留 M0 行为。不要将完整角色链重新放回 M0 的正常每帧路径。

代码提取与 fixed views 分别提交于 `9f9d369` 和 `3a163e7`。两阶段通过记录是 `outputs/mini-provider-validation.json`、`outputs/mini-fixed-views-validation-r2.json`；当前最终源码验证以 `outputs/mini-m0-validation.json` 为准。初次 fixed-view fixture 清理失败和初次长轨迹 pending 类型预期失败的 proof、suite logs、初始测试源码均保留，不能称所有初次验证成功。

最终全仓验证为 **1104 passed / 0 failed / Ruff 0**，36个 suites，包括500步 mock 及中点恢复。官方源码和当前项目源码在验证前后均精确不变；注册的128MiB/Swap0 scope，peak134217728、oom0/oom_kill0。不同阶段的重叠测试数不相加。这是离线工程验证，Mini 尚无新的原官方分数。
