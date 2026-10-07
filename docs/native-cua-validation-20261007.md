# K3 native 与固定 CUA 契约：真实两臂短程验证

日期：2026-10-07。两臂均通过真实 API → 原生工具 → 官方完整批次编译 → 官方 env.step → 实际回执 → 后截图 → SQLite 转换记录 → 下一轮原 tool ID 反馈的核验。

这次每臂预先冻结 3 个官方决策，用于接口与记录兼容性检查；不是正式 500 决策任务性能评测。两臂原官方短程 result.txt 均为有效 0.0，原目标尚未完成，不据此比较 baseline 与 TaskViews 的任务能力。

## 配置与密钥读取

运行源码 commit：`2dd496368edb3669588d47d27525eb4e04daca25`。固定官方 checkout：`3d778a3c9a34a079316f70df023b166700445792`。两个独立 episode 使用同一冻结计划，baseline 清理核验后才启动 TaskViews。

- 协议预选 K3 native function calls；不要求 XML，不按模型输出自动切换协议。
- 两臂均为 max/16000、整步32000、actor保留16000、分析4000；整步930秒、actor生成600秒、connect15秒、idle120秒、传输900秒。
- absolute 模式、模型图1920×1080，所有角色使用同一官方处理后的模型图；schema、提示、frame 和官方编译参数逐项一致。不猜单位、不夹取坐标、不执行非法批次的前缀。
- Ubuntu 交互式 shell 能读取用户已设置的 KIMI_API_KEY；最初非交互式 shell 的缺省环境未继承它。此次启动器使用与现有服务相同的交互式配置。真实请求证实服务可读取密钥；仅记录存在布尔值，未输出、复制或提交密钥。无需增加另一套凭证存储。

## 修复与离线测试

空正文兼容复用固定官方客户端的 `_text`：生成官方 Completion 时归一化空字段，原 SSE、原 assistant reasoning/content 和供应商历史保持原样；不把空正文合成为 XML、动作或终止。被动记录将 SQLite 类型放入 `journal_kind`，消除与 emitter 的 `kind` 参数冲突，保留实际边语义。

[定向回归](../validation/native-cua-fixes-20261007.json)：146 passed、0 failed，Ruff 通过，官方源码未改。包括三份真实空正文 SSE、完整官方 predict/下一轮历史、真实 JSONL emitter 与 SQLite ID/回执/目标观察。此前首次新增测试的六项调用或断言错误留在 attempt1，不混作模型失败。详见 [修复说明](native-cua-fixes.md)。

本轮线上6个 actor 响应没有出现 content=null；空字段兼容的证明来自三份已封存真实故障 SSE 的离线回归，不能声称这次线上复现了该故障。native 使用两臂共同的项目响应/历史适配器，复用官方 schema、截图、坐标投影、编译、执行与评分，不称为原 QwenAgent XML predict。

## 实际结果

| 模式 | 决策 | 官方动作/转换边 | 实际命令回执 | 前后原图 hash 变化 | API完整/请求 | 已知输入+输出 | 费用未知请求 | 墙钟秒 |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| baseline | 3 | 8 | 6 | 6 | 3/3 | 50503+13638=64141 | 0 | 632.458 |
| taskviews | 3 | 3 | 3 | 3 | 8/14 | 70396+24337=94733 | 2 | 1011.166 |

合计已知输入120899、输出37975、总计158874；另有2个费用未知请求。失败的已知 usage 已含在总额，按 request_id 去重，未知不记实测0。

baseline 的8条动作包含2条 WAIT；WAIT 不调用命令接口，故只有6个命令回执。其余记录包含截图命令，不能称为6次点击。TaskViews 的3条动作均为点击，均有实际回执。原编译、env.step 返回、后截图与反馈逐项一致；截图 hash 变化只表示像素改变，不证明意图实现或目标完成。

两臂 actor 各3次原生响应全部完整、没有 actor length/坐标拒绝/语义修复/网络重试/执行错误；被动记录警告均为0。所有动作使用提前固定的 absolute 契约，例如 TaskViews 的 `(1342,271)` 直接由原官方编译器生成 `pyautogui.click(1342,271)`，没有根据这个数字临时选择单位。

## TaskViews 的实际消费与限制

第2步真实生成并分发一个任务模块及可选视图，planner/verifier 均完成一次 JSON 建议；actor 收到原 goal、同图及可选上下文。后续分析实际读取此前转换 ID、源/目标观察、指令引用及回执数。最终模块投影保留3条转换、cursor=21、gaps为空；模块仍为 active/paused，不自动变成 completed。

第1/3步可选分析降级：共4次 perception 输出4000额度耗尽、1次 view_controller 分析截止、1次 perception 分析截止。四次长度失败保留完整 [DONE]/length/usage；两次分析截止保留部分流且费用未知。共4次 advisory 语义修复（第1/3步各2），无 actor 修复，无网络重试。两次降级不阻断原生 actor。

分析截止为整步930秒提前让出 actor生成600秒和connect15秒所得的315秒窗口，未刷新整步时钟。两次 deadline 不是 actor600秒耗尽，也不是网络 idle120秒故障。角色成功、长度失败、截止、降级和费用是不同维度，不能重复计费。

源/目标节点、执行动作、对应指令、实际回执和目标观察分别保存；schema delta 为可选提议，未产生时保留 null，不伪造。模型 verified、视图 revision 或回执均不升级为完成证明；效果仍为 unknown，只有原 evaluator 定义评分。planner/verifier/controller 不注册执行工具，不改变单位或结束规则。

局限：本次证明 native 动作链路及一次成功的自适应上下文分发，未证明分析在所有步骤可靠、完整目标完成或长期记忆优势。后续应优先为结构化分析减少不必要的长 reasoning、缩小每次生成的证据/视图包，并用新的独立配置验证预算；同一 actor 与 CUA 契约继续保持。不得热修本次冻结源码或回写原结果。

## 按用途的全部请求

| 模式/用途 | 请求 | 完整 | 失败 | 已知总 usage | 未知费用请求数 |
|---|---:|---:|---:|---:|---:|
| baseline/executor | 3 | 3 | 0 | 64141 | 0 |
| taskviews/perception | 7 | 2 | 5 | 48669 | 1 |
| taskviews/view_controller | 2 | 1 | 1 | 6846 | 1 |
| taskviews/executor | 3 | 3 | 0 | 30362 | 0 |
| taskviews/planner | 1 | 1 | 0 | 4677 | 0 |
| taskviews/verifier | 1 | 1 | 0 | 4179 | 0 |

## SSE 分片时序

以下是每个请求的首个/最后一个已保存 SSE 分片 elapsed 秒；完整响应的 finish/[DONE] 与原 usage 逐项重建一致，部分流的最后分片不是完成时刻。完整响应另含首 reasoning/content/tool、最终 complete 等时序，保存在各组 diagnosis.sse.timings。

| 模式/用途 | request_id | outcome | finish | 首片秒 | 最后片秒 | DONE |
|---|---|---|---|---:|---:|---|
| baseline/executor | k3s-3f23024ab5954dc29c756f11c6d1eb00 | complete | tool_calls | 7.8905 | 425.9324 | True |
| baseline/executor | k3s-00502ecd7e4c4f7baf592f8eb6e7be80 | complete | tool_calls | 7.9108 | 23.4200 | True |
| baseline/executor | k3s-41644f3223204313b8c3c5d41496f1c4 | complete | tool_calls | 9.3520 | 18.6896 | True |
| taskviews/perception | k3s-b6009b91b3274b9d885c934f4ef1204d | error | length | 11.9107 | 124.3990 | True |
| taskviews/perception | k3s-f49870c3cca046b6aa88f19f64fc0d92 | error | length | 13.8811 | 124.1026 | True |
| taskviews/perception | k3s-6a3d1ad57d9f41018e2dbe5333802d8a | complete | stop | 4.4322 | 45.7074 | True |
| taskviews/view_controller | k3s-b4a5d9f748064be0a9120e0d8dee097b | error | None | 7.7958 | 19.7672 | False |
| taskviews/executor | k3s-35e979b6b6de4c2bb4d0ba174a4ccbb3 | complete | tool_calls | 11.6458 | 16.4804 | True |
| taskviews/perception | k3s-5a6fbf2c345d463c9f8dcf819bf39c68 | complete | stop | 9.8169 | 62.5501 | True |
| taskviews/view_controller | k3s-6961c489ad684cc2bb893c2a86bf244b | complete | stop | 5.6088 | 51.5129 | True |
| taskviews/planner | k3s-9b7b4336bfea4d869f55f0684a0bf52c | complete | stop | 7.6687 | 36.7784 | True |
| taskviews/verifier | k3s-d3fd34a53c98485a94a4f27754bc5702 | complete | stop | 11.2020 | 17.8098 | True |
| taskviews/executor | k3s-748f4aed899e4355b6b4ad2372106e83 | complete | tool_calls | 9.7476 | 12.7353 | True |
| taskviews/perception | k3s-f4e543c9fbf7407387d461e48eb9a021 | error | length | 10.4908 | 114.2081 | True |
| taskviews/perception | k3s-4e9ef4c971cc42e09f58a0abbb52318c | error | length | 8.8063 | 134.9224 | True |
| taskviews/perception | k3s-4ede5c31ebc843b08143ac2aafbc98ab | error | None | 4.4564 | 65.4388 | False |
| taskviews/executor | k3s-544577a3dc6e497f9cc004c8f812b842 | complete | tool_calls | 12.6581 | 43.3935 | True |

## 资源、源码与证据

| 模式/采样器 | 样本 | 活动期最低 raw GiB | 最低 adjusted GiB | 实测 owned+aux 采样峰 bytes |
|---|---:|---:|---:|---:|
| baseline/resources.jsonl | 57 | 5.553818 | 9.312912 | 4053905408 |
| baseline/vm-guard-memory.jsonl | 105 | 5.378242 | 9.137352 | 4054110208 |
| taskviews/resources.jsonl | 90 | 3.708469 | 7.191963 | 3765899264 |
| taskviews/vm-guard-memory.jsonl | 168 | 4.393429 | 7.876980 | 3790077952 |

公式为 Windows raw free + 实测 owned memory.current/Docker usage，完整 ID 去重，嵌套仅父组。没有加回硬限、峰值、整个WSL或无关内存；采样峰不称为宿主精确物理占用或最终 kernel peak。每臂完整 live 原件只采一次，kernel max 计数不等于 OOM。

启动 adjusted5/C45/D12、运行adjusted4/C35/D10保持；VM3GiB/guest2GiB/2CPU、service2GiB、web预算0.75GiB和单aux128MiB，总硬组件5.875GiB<6。所有辅助回放/诊断/报告在Ubuntu官方Python、注册128MiB/SwapMax0 scope串行运行。两臂 resource 公式、去重、硬限与无OOM核验通过。

源码、计划、官方任务素材逐hash一致；原官方评分器/答案未改。两臂原audit保留，独立diagnosis/report/evidence-index封存后逐文件重新校验。实验unit inactive/dead MainPID0，owned VM及overlay均不存在，Task059无owned网站，/proc/swaps空。未用Codex Computer Use或人工GUI。

plan SHA-256：`0d33dd5b727cca7b947a1d7aae0ff457a014bf9baafb3b4a20afd8598abf7773`；冻结归档 SHA-256：`74116b93c53557ef4f26950801b0d59f5a7a1c1b2027eb5e620ed8dd557e6018`。

- [总结果](experiments/native-cua-smoke-max16-20261007/final-results.md) / [全部记账](experiments/native-cua-smoke-max16-20261007/final-results.json)
- [baseline 诊断](experiments/osworld21-kimi-k3-task059-20261007-native-cua-smoke-max16/baseline/terminal-diagnosis.json) / [原件索引](experiments/osworld21-kimi-k3-task059-20261007-native-cua-smoke-max16/baseline/terminal-evidence-index.jsonl)
- [TaskViews 诊断](experiments/osworld21-kimi-k3-task059-20261007-native-cua-smoke-max16/taskviews/terminal-diagnosis.json) / [原件索引](experiments/osworld21-kimi-k3-task059-20261007-native-cua-smoke-max16/taskviews/terminal-evidence-index.jsonl)
- [空字段与实际上下文核验](experiments/native-cua-smoke-max16-20261007/response-context-inspection.json)

本报告提交到本地Git；大型原始实验/SSE/图片/SQLite/归档保留在本机忽略目录，不冒充已推送GitHub的可下载材料。旧v4/v6封存证据未覆盖、未重跑，旧心跳保持暂停。
