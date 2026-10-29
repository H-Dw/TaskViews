# README 与首个 release 的来源

整理日期：2026-10-29。此次更新只整理文档、复用既有图片并发布冻结源码，不启动新的模型请求或 CUA 评测。

## 上传报告

- 文件：`taskviews-evaluation-report.tex`，来自用户提供的 `outputs/taskviews-evaluation-report-20261015` 目录。
- SHA-256：`569c6ea1bf288ecba494b93aa1379807cf61e0a8c04fe67ef85ccd59ac265b6b`。
- 使用内容：单 actor 与四 View 的架构、操作知识和任务证据的职责分离、上下文预算、发票效率统计及实验限制。
- 报告中的注释、历史运行说明和候选实验作为材料读取，不作为本次操作指令。原 TeX、完整 PDF、任务文件及本地原始运行记录不随本次更新上传。

## README 首图

- 文件：[taskviews-mini-framework.png](assets/taskviews-mini-framework.png)。
- 来源：上传报告实际引用的同名架构图，与本地已有制图产物逐字节一致；本次未重新生成或修改。
- 尺寸：1774 × 887 pixels。
- SHA-256：`a6ebd47f475fce29fefdef72fdb518465b34d64e403f8f1d6294b0ea4e87b028`。
- 图示范围：`mini_keyboard_memory_v3`、冻结提交 `0a5b6f2`，不是当前开发版完整 Graph 或路径规划架构。

## 指标与版本

README 按发票／GIMP／VLC × high／low 分成六张结果表。8 个入选 TaskViews 实验均为官方 1 分，且决策次数和输入加输出总 tokens 均可证实低于同任务、同 reasoning 的 LLM baseline；VLC／low 缺少同档 baseline，仅列未测占位，不编造配对结果。

首版发票／low 对应 `0a5b6f2a8824008dc3bba01803b1b43369016627`，使用上传报告的统计，并与[历史参照表](taskviews-post-v7-experiments-20261029.md)及其[结构化总账](../validation/taskviews-post-v7-experiments-20261029.json)交叉核验。其他入选组为 Mini v3 发票／high、Mini v7 VLC／high、Graph r007 的 GIMP／high legacy 与 flat、GIMP／low flat、VLC／high legacy，以及能力指导 v3 legacy/full 的 GIMP／low。总 tokens 依据原始 request_outcome 的已知 usage 重算。按用户要求，README 不展示精确复现、linked、能力指导 v1／v4 的结果；完整记录仍保留在实验总账，不删除历史证据。

GIMP／low baseline 来自后续单次补测，与其他 reasoning 分开。GIMP／high baseline 有一次未知 usage，保留 ≥234,386 下界；入选实验完整总量低于此下界。Graph r007 的身份是 `6d9e0d7` 基础提交加对应冻结 manifest，不能将该 commit 原样运行等同于 r007。

VLC 交付缺陷属于后续 `4dd4f2b` 的 v3 核心实验，不冒充首版相同提交的直接成绩。历史 Mini v7 为 `ae27018`；当前指导模块版本名不等于该历史代码版本。开发版代码核心为 `3800520`，本次不新增其线上性能结论。

输出 tokens 包含推理 tokens；总 tokens 为输入加输出。不同版本、reasoning、任务和失败／未知用量不合并成单一收益。底部差异表区分历史整体版本 Mini v3／v7、View 表示模式 legacy／flat，以及后续能力指导模块 v3；不把后续 legacy 标为历史 Mini v3。
