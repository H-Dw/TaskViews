# TaskViews-mini 跨 View Graph v1

四个 View 保持 `current / keyboard / attempts / lessons`。新模式从同一 episode 的原始 SQLite journal 和冻结按键目录建立确定性身份与关系，不增加模型调用。任务目标仅表示原始任务总目标。

实现验证：545 项回归与九种原运行器离线组合通过，详见 [验证结果与同输入消融](taskviews-mini-graph-v1-validation.md)。

## 运行选择

新建运行默认 `linked`，可在现有准备命令中加入：

```text
--mini-graph-mode legacy
--mini-graph-mode flat
--mini-graph-mode linked
```

该参数用于 `scripts/verified_invoice.py prepare`、`scripts/osworld_native_experiment.py prepare`，以及对应离线集成验证器与独立定位预检。正式执行读取冻结计划，不用启动时的命令行选项改写计划。三模式使用三个独立计划目录和运行环境；一个计划中的 TaskViews arm 只采用一种模式。baseline 与 UI-KOBE-like 的实际模式始终是 legacy。

| 模式 | 输入结构 | 用途 |
|---|---|---|
| legacy | 原有 packet、标签、选择和打包器 | 原始架构消融 |
| flat | 共享实体、稳定 ID、View 引用；`links=[]` | 统一组织方式的对照 |
| linked | 同样的实体、事实和引用，加显式关系 | 新建运行默认 |

`flat ↔ linked` 只衡量新增显式关系的作用。flat 仍有稳定 ID、原生前后观察和来源引用，不能称为完全没有关联信息。`legacy ↔ flat` 比较整体组织变化；`legacy ↔ linked` 比较整体改造。

计划、manifest、验证证明和 checkpoint 声明 `mini_graph_mode` 与完整 `mini_graph` policy，包括 schema、身份规则、打包版本及 3000-byte 上限。运行入口从冻结声明设置 `UI_KOBE_MINI_GRAPH_MODE`，恢复时拒绝更换模式。低层旧调用和历史文件缺少字段时按 legacy 解释。历史计划的源代码身份和哈希校验继续有效，不能因为兼容模式而用新代码冒充旧代码；在当前代码上运行 legacy 对照，应准备新计划。

独立定位预检使用与计划相同模式；旧模式的预检和离线集成结果不能用于另一模式。历史轨迹重放入口显式使用 legacy，避免受外部环境变量影响。旧 controls 扩展仅支持 legacy；两个新模式始终保留默认四 View。

## 数据与身份

原始事件、截图、动作回执和按键知识的存储不变。`GraphIndex` 增量读取新事件，仅保存身份、时间和建立关系所需的元数据；不复制截图或完整响应、回执。恢复时重新读取日志及冻结目录，不执行历史动作。

| 对象 | 完整身份 | prompt 内别名 |
|---|---|---|
| 事件、观察、实际动作、decision | episode ID 与原始事件 UUID；类型区分 | `e<seq>` |
| 总目标 | task ID 与原始 instruction SHA-256 的确定性哈希 | `g<hash-prefix>` |
| 配方 | 命名空间、目录、topic、平台、scope、配方内容及来源的哈希 | `k<hash-prefix>` |
| 派生记录 | 投影版本、类型及来源身份集合的哈希 | `d<hash-prefix>` |

短别名碰撞会被拒绝。配方排列顺序不改变身份；配方、适用条件或来源改变会改变身份。临时配方包含任务目录身份，不能与永久目录或其他任务混用。原有完整目录哈希仍用于配置和恢复校验。

每个 episode 导出 `<episode_id>.mini-graph.json`，保存完整身份映射、原始事件哈希和时间、游标、选中关系、实际投递状态及统计。该文件是可重建的派生审计索引，原始 journal 是事实来源。图索引按 episode 隔离，不跨任务读取经验。

## 上下文结构与关系

新 packet 包含 `profile / schema_version / mode / episode_id / frame_id / nodes / views / links / sources`：

- `nodes`：每个实体的共享字段及 `facets`。同一动作的执行尝试、错误记录、按键记忆可以共用节点。
- `views.<name>.record_refs`：有序的 `[node_alias, facet_name]` 对；保留 `omitted_records`。
- `links`：有序的 `[source_alias, relation, target_alias]` 三元组。flat 为 `[]`。
- `sources`：原始 seq 到事件哈希与类型，沿用原始事件校验。

facet 保留原有证据等级和完整入选字段。例如 `execution_attempt.receipt=returned` 和 `execution_error_record.receipt=error` 同时保留；共享节点不能抹去这种区别。当前状态来自 current 引用节点的 `original_input` facet。产物复核协议中的引用仍填写 observation 的数值 seq，不填写 `e` 别名。

| 关系 | 依据与限制 |
|---|---|
| in_task | 原始 task_input、decision 或 transition 中的 instruction 及明确观察端点 |
| issued_by | decision ID、命令序号、原始命令和工具绑定一致 |
| before / after | transition 的 source / target observation |
| followup | 原有有界选择器提供的后续观察 transition |
| reports_on | 模型复核或检查状态明确引用的 observation；错误 facet 本身定位其实际动作 |
| matches_recipe | 已启用、当前选中 topic 的配方与实际完整工具参数精确一致 |

`matches_recipe` 不说明 actor 参考了该配方，不说明当前软件或焦点适用，也不说明执行成功。修正建议、未发出的键以及 key_down/key_up 事件不匹配完整快捷键。未执行命令保持独立事件身份，不成为实际动作。所有关系端点及其必要来源随包提供；来源、任务、episode 或执行绑定不一致在下一个 actor 调用前阻断。

第一版不生成子目标、故障原因、修复成功、界面语义等额外断言；unknown 和 model proposal 身份继续保留。

## 预算与消融

历史候选范围不扩大：最近主动操作、错误、模型意图、复核和按键记忆均沿用原选择器。原始 legacy 打包器保留；新模式使用独立打包器，优先保护当前状态、复核协议、最近操作和相关错误。

flat 与 linked 先按完整 linked packet 的成本选取同一份内容，再为 flat 移除新增关系。flat 不用节省的空间回填事实，也不填充无用文本。两者在同一日志快照、相同原生输入预算下，除 `mode` 与 `links` 外完全一致。合法预算不足时整包省略，不静默切换 legacy。

每轮 packet 自包含，不依赖上轮图已进入模型记忆。补充包继续只注入本轮请求，不反复追加到持久 actor 历史。重复执行具有独立事件 ID，序号与证据保留；共享实体只去除重复载荷。

关系、端点和来源也占用字节。在 3000 UTF-8 bytes 上限下，新模式可能比 legacy 少保留历史或按键记录。审计记录每个 View 的遗漏量；比较报告会显示该成本，不宣称图结构必然减少 tokens 或提升成功率。在线轨迹会分叉，“相同事实”仅是离线同输入的保证。

## 离线验证与报告

`tests/fixtures/mini_graph_legacy.json` 来自改造前提交 `6d9e0d7` 的真实 Mini actor/context 实现：固定合成时间、UUID、日期及图片定位字符串，保存三轮 packet 和原始 actor 请求哈希。回归检查 legacy 路径逐字匹配。

在已安装官方编译器和开发依赖的环境中，生成同输入消融报告：

```bash
python scripts/compare_mini_graph.py --output outputs/mini-graph-ablation
```

输出三轮 × 三模式 packet、身份索引、JSON 与 Markdown 报告，检查 flat/linked 事实一致、来源、关系、遗漏和实际字节。仅使用模拟 actor 返回与模拟 GUI 回执，不调用真实 API、GUI 或 VM。

原运行器的离线集成通过 `scripts/validate_verified_invoice.py` 执行。分别传入三个 `--mini-graph-mode`，每种覆盖 `--case limit`、`--case terminate`、`--case empty`，各自选择新的 `--output` 目录。验证结果必须与后续准备计划的实际模式匹配。

恢复、跨任务隔离、精确配方匹配、部分按键、未执行命令、原始失败等级、中文及极小预算等由针对性回归覆盖。后续真实实验需保持任务、模型、初始环境、目录和预算一致，另外评估成功率、重复无效操作、tokens 与耗时。
