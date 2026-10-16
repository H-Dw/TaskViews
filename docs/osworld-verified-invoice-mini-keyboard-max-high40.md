# Mini 键盘视图与记忆优化后的独立评测

用户于2026-10-16明确授权提交优化版本，随后仅评测 TaskViews-mini：随想 `qwen3.8-max`、`enable_thinking=true`、`reasoning_effort=high`，最多40次 `actor.predict`（含空动作）。优化提交为 `130d207`；新入口 `experiment=sx-mini-max-high40` 只冻结 `taskviews` 一组，不调度 UI-KOBE-like 或 baseline。

任务为 OSWorld-Verified（OSWorld-1）`multi_apps/337d318b-aa07-4f4f-b763-89d9a2dd013f`。Mini 使用 `mini_keyboard_memory_v3`：`current/keyboard/attempts/lessons` 共用3000 UTF-8 bytes；键名参考、同 episode 键盘记忆和生成引导见[修复复盘](taskviews-mini-keyboard-postmortem-20261016.md)。旧运行不作为新 actor 的记忆输入。

当前计划目录为 `runs/verified-invoice-mini-keyboard-sx-max-high40-20261016-v2`。WSL Ubuntu-24.04 从 `SX_QWEN_API_KEY` 读取密钥、从 `SX_URL_SB` 读取唯一冻结入口。relative 每轴0–1000，原图1920×1080；history20/image1/fold1、text32000/reserve10000、消息序列化上限12M字符、单请求输出16000、单步32000及两次语义修复池均沿用原配置。完整响应及真实DONE后才接受动作。

使用官方 Docker 新环境、新进程、新 journal 和原评分器。VM3GiB、actor2GiB、启动器/巡检128MiB，零swap；Windows真实空闲物理内存>2GiB，本项目实测占用另记；C/D空闲阈值45/12GiB。显式终止或到达40轮后评分；无有效result时分数为null。仅清理本计划精确run label且镜像/资源匹配的容器。

启动前验证本次源码的 Mini 三例原运行器离线集成（上限、显式终止、空动作）、相关回归、Max/high接口和大图工具回执，并收集实际Mini四位置定位结果。单组评测把定位精度作为观测指标：完整收集全部位置，分别报告 `collection_complete` 与 `all_targets_passed`，不按精度挑选运行。启动仍要求当前源码/模型/坐标匹配、完整有效返回、合法可编译的屏内mouse_move和真实工具回执兼容；合成记录不当作真实环境启用证明。

首次v1合成定位的第一个点为(1588,179)，目标中心为(1620,180)，位于80×80目标内但超过旧中心误差30像素阈值，旧探针提前结束。保留该失败及所有usage；未启动VM或评分。新计划v2明确冻结 `collect_all_record_accuracy`，不会把后续采样用于抹除这次误差；原三组入口仍采用旧的全通过策略。新正式目录为 `runs/verified-invoice-mini-keyboard-sx-max-high40-20261016-v2`，v1仅保留为未启动的验证记录。

真实guest取得首个完整模型返回和有效决策后恢复原20分钟有界巡检；无实质变化时保持安静，完成后审计并暂停。实际启动状态及提交以新计划 `plan.json`、`state.json` 与[运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)为准。
