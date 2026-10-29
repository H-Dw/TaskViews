# TaskViews

![TaskViews-Mini：单一 CUA actor、四类 View 与执行证据回路](docs/assets/taskviews-mini-framework.png)

*首图展示首个 release 所用的 Mini v3 核心（`0a5b6f2`）：四类 View 从预置操作知识和本次任务的执行记录中组织补充上下文。当前开发版在此基础上增加了指导选择、阶段状态和跨 View 引用。*

TaskViews 为 computer-use agent 按信息职责组织上下文：让基础操作知识、当前界面、已执行尝试和历史错误各有位置，帮助同一个 CUA actor 复用证据、选择下一步动作。Mini 路径采用确定性的检索与打包，正常操作中不增加规划或分析模型调用。

**首个 release：[TaskViews-Mini v0.1.0](https://github.com/H-Dw/TaskViews/releases/tag/v0.1.0)**，固定到 [`0a5b6f2`](https://github.com/H-Dw/TaskViews/commit/0a5b6f2a8824008dc3bba01803b1b43369016627)。该版本在已测任务中实现了 CUA 决策效率提升，但在部分复杂任务上存在结果提交缺陷。`main` 是后续开发版本，不能用其运行结果替代首版成绩。

## 工作方式

```text
任务 + 当前截图 + 原生历史 + 本轮 View 补充包
                         ↓
                   单一 CUA actor
                         ↓
               原生工具 → 官方执行器 → 桌面
                         ↓
               观察 / 参数 / 回执 / 错误
                         ↓
                 episode SQLite journal
                         ↓
                 下一轮检索与上下文打包
```

|View|提供的信息|证据边界|
|---|---|---|
|`current`|当前观察、任务和坐标约定；开发版还投影已有检查状态|引用当前帧，不额外生成界面事实|
|`keyboard`|适用的准确按键、完整操作指导及同 episode 按键记录|目录启用不代表软件、窗口或焦点已确认|
|`attempts`|实际动作参数、回执，以及动作前后和后续观察|工具返回、按键匹配或截图变化不等于业务成功|
|`lessons`|真实执行错误，以及带来源的模型公开意图／复核报告|模型判断保留 proposal 身份，`unknown` 不自动升级|

四个 View 共用 **3000 UTF-8 bytes** 补充上下文上限，并受实际请求余量约束。完整记录按预算准入，完整事件、来源和省略信息留在本地审计中。补充包每轮独立可读；任务记录按 episode 隔离。

项目沿用 UI-KOBE 的执行转移记录和检索思路，将其组织为固定职责的 View。GUI 动作仍经共同的 native 协议桥接与外部 OSWorld 执行／评分底座处理。模型声称完成和官方评分分别记录。

## 已观察到的效率与限制

下表来自历史发票任务的同档 baseline／Mini 记录，模型为 `qwen3.8-max`，thinking 开启、reasoning 为 `low`，温度 0，最多 40 次决策。两组源码均冻结于首个 release 的 `0a5b6f2`，使用各自独立 guest 和空任务记忆。

|指标|LLM baseline|TaskViews-Mini v0.1.0|
|---|---:|---:|
|官方分数|1.0|1.0|
|决策次数|28|22|
|GUI 命令|27|22|
|API 尝试／完整返回|28／28|22／22|
|输入 tokens|219,061|190,785|
|输出 tokens|7,803|6,095|
|其中推理 tokens|4,723|3,865|
|总 tokens|226,864|196,880|

这次记录中，Mini 的决策减少 **21.4%**，总 tokens 减少 **13.2%**。输出 tokens 已包含推理，不能重复相加。同提交后来一次原样复现也为 1 分、22 次决策，输出为 6,973 tokens；单次运行不代表固定开销，也不足以证明所有任务均有收益。

**已知限制：效率提升不能保证交付正确。** 首版尚未包含后续的严格产物来源复核。复杂任务可能完成了界面操作，却提交了来源不符或内容不正确的产物。例如，同属 v3 核心的后续提交 `4dd4f2b` 在 VLC 截帧任务中把观察截图作为交付图片，官方连续分数为 `0.08199028328542753`。这是另一提交的证据，不能冒称 `0a5b6f2` 的直接 VLC 成绩；它揭示了首版架构需要补强的提交检查。

完整版本、指标定义、失败用量下界和后续实验见[实验与版本总账](docs/taskviews-post-v7-experiments-20261029.md)。不同提交、reasoning、目录和运行日期分别报告，不把离线结构验证当作在线成功率提升。

## 首版与当前开发版

|版本|范围|
|---|---|
|`v0.1.0` / `0a5b6f2`|历史 `mini_keyboard_memory_v3`；单 actor、四个 View、预置按键与 episode 记忆。保留原样，作为冻结参照。|
|历史 Mini v7 / `ae27018`|增加产物报告协议、来源校验、短纠错及同轮输入重新准入。不是首个 release，也不是当前指导模块的“v7”。|
|当前 `main`|代码核心提交 `3800520`，后续提交补充报告与文档；包含阶段化复核、阅读进度、适用性优先的操作指导及三种 View 表示。最新指导候选有离线验证，尚无对应线上任务成绩。|

当前开发版支持以下表示方式，选择模式并不等于切换到某个历史提交：

|`--mini-graph-mode`|行为|
|---|---|
|`legacy`|原四 View 的表示／打包路径；仍使用所冻结提交的公共 actor 和指导模块|
|`flat`|统一实体 ID、共享事实与 View 引用，不输出新增显式关系|
|`linked`|与 flat 使用相同事实选择，额外输出有执行字段依据的关系|

flat／linked 在相同日志输入和预算下按 linked 成本选择相同事实；flat 删除关系后不回填记录。**linked 当前没有完整图检索或路径规划**，不应把关系输出本身当作已验证的效率优化。新入口默认显式选择 linked；旧计划缺少模式字段时解释为 legacy，恢复时不允许切换。

当前指导路径先检查能力、动作、对象、应用与流程阶段是否适用，再排序和打包完整指导组。软件名匹配、通用能力冻结与任务级联网调研是不同选项；联网调研默认关闭，其 API 成本另计。目录扩充和指导改写不保证比原 v3 更高效。

## 开始使用

Python **3.10+**。以下命令安装代码并预览确定性的目录选择，不启动 CUA、虚拟机或模型请求：

```bash
git clone https://github.com/H-Dw/TaskViews.git
cd TaskViews
python -m venv .venv
# Linux / WSL
source .venv/bin/activate
# Windows PowerShell 可改用 .venv\Scripts\Activate.ps1
python -m pip install -e ".[native,dev]"
python -m kobe_views.keyboard_selection \
  --keyboard-mode task_capabilities \
  --instruction "Read and compare PDF documents"
```

检出首版源码：

```bash
git switch --detach v0.1.0
```

首版没有后续新增的命令参数，应按该提交自己的代码与冻结配置使用。返回开发版用 `git switch main`。

实际 OSWorld 评估需要另外准备 Linux／WSL、Docker／KVM、guest 镜像、任务资源和外部执行底座。项目固定使用 `xlang-ai/OSWorld-V2@3d778a3c9a34a079316f70df023b166700445792` 的执行／评分代码，并校验来源；仓库不附带 VM 镜像、任务答案、凭据或完整原始运行数据。

当前 Verified 入口为 `scripts/verified_invoice.py`，支持发票、GIMP、VLC。默认 API 为 AutoDL 的 `https://www.autodl.art/api/v1`，模型 `Qwen3.5-397B-A17B`，密钥由 `AUTODL_API_KEY` 环境变量提供。**上面的历史成绩使用 SX 接口的 `qwen3.8-max`，不是 AutoDL 成绩。** 模型、reasoning、坐标、预算、按键目录、源码身份和模式都应在新计划中显式冻结；准备、检查、启动和恢复按对应说明执行。

## 文档与复现

|内容|入口|
|---|---|
|首个 release、已知缺陷和证据范围|[v0.1.0 发布说明](docs/releases/v0.1.0.md)|
|架构图与上传报告的来源|[README 来源说明](docs/readme-provenance.md)|
|v7 之后的冻结版本与逐格 performance|[实验总账](docs/taskviews-post-v7-experiments-20261029.md) · [CSV](validation/taskviews-post-v7-experiments-20261029.csv) · [JSON](validation/taskviews-post-v7-experiments-20261029.json)|
|Mini 实现与早期沿革|[Mini 说明](docs/taskviews-mini.md)|
|Graph 三模式与消融边界|[Graph v1](docs/taskviews-mini-graph-v1.md) · [送达 v2](docs/taskviews-mini-delivery-v2.md)|
|阶段上下文与当前按键适用性|[指导 v5](docs/taskviews-mini-guidance-v5.md) · [适用性审计](docs/taskviews-keyboard-eligibility-v7-audit.md)|
|按键目录与可选联网研究|[目录入口](tools/keyboard/README.md) · [目录选择](docs/taskviews-keyboard-auto-selection-20261020.md) · [任务级调研](docs/task-keyboard-web-research-20261020.md)|
|AutoDL 配置与离线／真实接口验证边界|[API 接入](docs/autodl-taskviews-mini-20261021.md)|
|冻结矩阵、串行执行与审计|[三任务运行说明](docs/osworld-mini-graph-high-low40.md)|

历史文档保留当时的默认值和验证结果；复现应以目标提交、该次冻结计划和原始指标来源为准。离线测试、接口探针和正式任务成绩分别核算。

## 来源与许可

本项目衍生自 [UI-KOBE](https://github.com/YuxiangChai/UI-KOBE)，保留原作者署名、[上游 README](README.upstream.md) 和 Apache-2.0 [LICENSE](LICENSE)。衍生源码与外部 OSWorld 底座的边界见 [UPSTREAM.md](UPSTREAM.md)。
