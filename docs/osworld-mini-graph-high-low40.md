# OSWorld-1 Mini Graph 三任务 High/Low 串行实验

本实验使用 SX `qwen3.8-max`，三个任务为发票核对、GIMP 背景透明化、VLC 当前帧截图。
每个任务执行 legacy/flat/linked × high/low 各一次，共18格。legacy 是原四 View Mini，
不是 LLM baseline。本实验没有 baseline arm。

## 固定条件

`enable_thinking=true`，reasoning_effort 分别为 high、low；temperature=0；流式原生工具。
40次 actor.predict（含空动作），请求16000 tokens、单步32000 tokens；1920×1080，
relative每轴0–1000；history20、image1、fold1；四View最多3000 UTF-8 bytes。
发票启用general；GIMP启用general+app.gimp；VLC启用general+app.vlc。临时联网按键检索、
controls及额外分析角色关闭。每格使用新进程、新guest可写层、新actor、新journal。

六格任务顺序为：

1. invoice：legacy/high、legacy/low、flat/low、flat/high、linked/high、linked/low。
2. gimp：flat/high、flat/low、linked/low、linked/high、legacy/low、legacy/high。
3. vlc：linked/high、linked/low、legacy/low、legacy/high、flat/high、flat/low。

全局执行锁跨运行目录共享，矩阵持有锁，直接子启动器继承锁描述符。
只有上一格完成原评分、保存结果并清理其精确所有权容器，才开始下一格。正常0分继续；
执行、配置、资源、接口或清理异常停止队列。

## 入口与证据

入口是 `scripts/verified_mini_graph_matrix.py`，提供：

- `qualify --validation-dir <新目录>`：依次执行54个原runner模拟场景和8个原媒体评分接入场景。
- `prepare --validation-dir <已通过目录>`：准备18份冻结计划、源码存档和持久修复账本。
- `qualify --live --validation-dir <新探针目录>`：两套provider检查和六套Mini定位诊断。
  完全相同的接口/模式配置可共享原始探针证明，保留来源，不伪装成多次请求。
- `check`：校验计划、证明、原镜像、共同预算及实际资源。
- `start --execute-approved-plan`：提交唯一后台串行服务，`launch`是其内部执行入口。
- `inspect`：单次有界只读检查；`report`：由现有证据更新派生统计。

均使用 `--root <唯一实验根目录>`。在WSL Ubuntu-24.04内执行，辅助命令置于
128MiB/零swap的systemd scope；完整actor/runner离线场景与正式actor使用2GiB/零swap。
guest RAM2GiB，VM容器3GiB，Windows真实空闲RAM>2GiB，C/D空闲至少45/12GiB。
启动服务通过既有本地环境包装器在进程内读取现有SX配置，不复制凭据到实验产物。

`matrix.json`是不可变实验协议，`state.json`指向当前冻结queue。每份plan、queue和源码
存档都有哈希；旧revision不覆盖。结果保留官方原分数，异常导致的无有效成绩为null。
发票/GIMP是0/1，VLC是连续分数，不新增阈值。GIMP评分不独立验证alpha，应另行审查。

## 40分钟定时巡检

使用绑定当前线程的Codex heartbeat，每40分钟一次。每次只执行一次inspect后退出，
不常驻、不循环睡眠、不密集轮询。上一检查或修复尚在执行时跳过重叠触发。
正常运行不改代码、不重跑，不因未在40分钟内完成就判故障。
异常判断依据进程启动身份、实际回执、冻结阶段时限、错误与资源记录。
任务全部完成、外部问题需要用户处理，或额度耗尽且仍需修复时暂停heartbeat。

## 最多10次自动代码修复

全实验共享repair-ledger.json。一次修复是一个候选修改及其验证；失败或回滚也计数。
只读诊断不计数。修改前执行：

```text
repair-begin --diagnosis <具体原因> --evidence <本实验已有异常证据>
```

只有队列异常停止、launcher已退出、所属guest均已清理才允许登记。先持久增加计数，
再修改代码。正常低分、模型操作失误或合法上下文省略不构成修复理由。不得热改正式运行。

修改后进行定向回归及当前源码匹配的离线资格验证，再执行：

```text
repair-finish --result passed|failed|rolled_back --validation <验证JSON>
```

通过证明必须标明passed=true及当前project_source；失败和回滚均保留其证据。
通过后使用新的离线目录执行reprepare，随后重新完成必要的live资格证明、check和start。
第10次修复通过后可继续评测；不允许第11次代码修改尝试。

影响范围采取保守规则：公共actor、Graph、工具、预算、评分或未知运行代码变化影响全部
任务；明确任务专属模块影响该任务；纯监控、归档、报告支持修复且行为不变时保留有效结果。
受影响任务全部六格重跑，不只补失败格。所有未开始格也重新冻结，已完成的无关任务保留。
每任务最终比较须具有一致行为指纹；不同任务行为版本不一致时不汇总整体增益。
保留所有修复前结果，不按分数挑选版本。

## 结果解释

results.json/csv和report.md包含18格官方分数、有效性、版本、决策、API、tokens、耗时、
packet投递与遗漏、关系与共享引用。探针/重测费用与正式当前队列分开；未知usage/费用留空。
flat/linked的事实一致性仅是离线同输入保证，在线轨迹可不同。更小packet伴随更多遗漏时
不能解释为无损压缩。每格一次，不计算统计显著性；历史baseline/Mini仅作版本注明的参考。
