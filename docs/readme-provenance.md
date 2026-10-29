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

README 的发票／low 主表对应首版 `0a5b6f2a8824008dc3bba01803b1b43369016627`，使用上传报告的统计，并与[历史参照表](taskviews-post-v7-experiments-20261029.md)及其[结构化总账](../validation/taskviews-post-v7-experiments-20261029.json)交叉核验。22 次决策的原记录与后来同提交复现分别列示，不替换原记录。

VLC 交付缺陷属于后续 `4dd4f2b` 的 v3 核心实验，不冒充首版相同提交的直接成绩。历史 Mini v7 为 `ae27018`；当前指导模块版本名不等于该历史代码版本。开发版代码核心为 `3800520`，本次不新增其线上性能结论。

输出 tokens 包含推理 tokens；总 tokens 为输入加输出。不同版本、reasoning、任务和失败／未知用量不合并成单一收益。完整历史表中的 GIMP/high baseline 存在一次缺失 usage，应按已知下界理解。
