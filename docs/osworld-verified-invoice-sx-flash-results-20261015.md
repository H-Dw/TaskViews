# 发票与流水核对：两组35轮评测结果

2026-10-15 22:20完成审计。随想 `qwen3.8-flash / reasoning_effort=low` 在OSWorld-Verified（OSWorld-1）任务 `multi_apps/337d318b-aa07-4f4f-b763-89d9a2dd013f` 上，按UI-KOBE-like → TaskViews-mini顺序完成各一次、每组最多35个actor.predict轮的独立评测。

| 项目 | UI-KOBE-like | TaskViews-mini |
| --- | ---: | ---: |
| 官方得分 | **0.0** | **0.0** |
| 决策轮数 | 35 | 35 |
| 完整模型响应 | 35 | 35 |
| GUI命令 | 31 | 35 |
| WAIT | 4 | 0 |
| 已记录传输重试 | 0 | 0 |
| prompt tokens | 355414 | 301036 |
| completion tokens | 6512 | 9072 |
| 其中reasoning tokens | 4091 | 6237 |
| total tokens | 361926 | 310108 |
| 资源检查次数 | 37 | 37 |
| 检查中的最低真实空闲GiB | 4.698 | 5.908 |
| 最低审计预算余量GiB | 7.898 | 8.046 |

两组均达到35轮上限，执行记录中没有DONE/FAIL显式终止动作；随后由原官方runner调用原评分器。`result.txt`、`evaluation_result`遥测和`outcome.json`的0.0一致，均有真实评分证据。两组`complete=true`、`error=null`、`closed=true`、`cleanup_ok=true`。该完成状态指评测流程完整结束，任务得分仍为0.0。

合计70次完整模型响应、66个GUI命令、4次WAIT，总tokens=672034；prompt=656450、completion=15584，其中reasoning=10328。reasoning已包含在completion中，不重复相加。本报告仅汇总本次单任务的两组运行，不根据该结果推断完整基准性能或具体失败原因。

内存策略为用户确认的“Windows真实空闲>2GiB”，并单独记录本次actor、启动器和带精确运行标签VM的实测占用。预算余量=真实空闲+本项目占用，只作审计；硬限制不用作占用值，其他WSL工作不计入本项目。两组均完成启动1次、决策前35次、评分前1次检查，所有检查通过；日志位于各组`resource-monitor.jsonl`。最低值为检查点采样值。机制见 [内存规则](osworld-verified-memory-policy-20261015.md)。

Mini沿用`mini_fixed_v1`，固定current、attempts、lessons三个只读视图，controls关闭。35轮均记录视图生成和投递，各组模型请求数均为35，没有额外分析角色调用。两组各使用全新进程、官方Docker可写层和journal；此前失败运行的轨迹没有注入本次actor。

项目源码与v5冻结计划一致，上游任务、runner、controller、动作编译器及评分相关源码校验一致。审计时服务已正常退出（ExecMainStatus=0），本实验容器列表为空。20分钟巡检`osworld-20`已通过应用工具设为PAUSED并收到确认；未进行额外评分、续跑或重放。

证据目录：[v5运行](D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-invoice-sx-flash-low35-20261015-v5)。

后续离线分析见 [零分原因、CUA动作与得分差距](osworld-verified-invoice-sx-flash-failure-analysis-20261015.md)：两组均未取得评分目标路径下的PDF，轨迹显示共同的坐标语义问题，并发现Mini将空错误字符串误归为错误记录。分析没有修改原分数或重跑评测。

- [完整审计](D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-invoice-sx-flash-low35-20261015-v5/monitor-audit-20261015T1419Z.json)
- [机器可读汇总](D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-invoice-sx-flash-low35-20261015-v5/comparison-summary.json)
- [UI-KOBE-like官方分数](D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-invoice-sx-flash-low35-20261015-v5/ui_kobe_like/official/multi_apps/337d318b-aa07-4f4f-b763-89d9a2dd013f/result.txt)
- [Mini官方分数](D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-invoice-sx-flash-low35-20261015-v5/taskviews/official/multi_apps/337d318b-aa07-4f4f-b763-89d9a2dd013f/result.txt)
