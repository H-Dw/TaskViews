# Pinggy / Qwen 3.8 Max 恢复配置与复测

2026-10-15，用户要求切回 Pinggy，并明确确认恢复 `qwen3.8-max / low`。本次不继续 Tinker 或 OpenRouter；保留它们的适配代码和诊断证据。

## 当前配置

| 项目 | 设置 |
| --- | --- |
| provider | `qwen`，`--provider qwen` |
| base_url | `https://pjfdspqowq.a.pinggy.link` |
| 实际请求 | `POST /chat/completions`，不额外添加 `/v1` |
| 模型与密钥 | `qwen3.8-max`，仅读取 WSL `QWEN_API_KEY` |
| 推理 | `reasoning_effort=low`、`enable_thinking=true`、`preserve_thinking=true` |
| 请求 | SSE，temperature=0，top_p=0.9，单次总输出上限16000，每决策输出池32000 |
| 比较 | UI-KOBE-like → TaskViews-mini，每组最多35次predict，独立官方Docker guest |
| 网络 | `trust_env=false`，不复用空闲连接，保留原有阶段追踪和有界重试 |
| Mini | 固定 `current / attempts / lessons` 三视图，controls关闭，无额外模型角色 |

## 真实连接复测

北京时间18:52—18:53：

- 默认解析连接到IPv6；TLS1.3和TLS1.2均在TCP连通后收到连接重置，无HTTP发送。
- 固定IPv4 `173.255.198.74`，保留原主机名SNI和证书校验；两种TLS版本同样失败。
- 使用现有WSL `QWEN_API_KEY`、原low/SSE参数发起一次真实有界API请求。TCP约0.65秒完成，TLS约0.92秒失败。trace明确记录 `confirmed_no_origin_http_dispatch`；HTTP头、正文尚未发送，0个SSE事件，无DONE、无模型输出，usage为null。

这仍是TLS建立阶段的连接故障，不能归因于模型参数、余额、图片大小或读取等待。仅凭客户端证据无法确定具体关闭方。未尝试访问未知远端机器或管理隧道。

## 项目与运行状态

旧失败目录 `runs/verified-invoice-low35-review-final` 保留；Tinker目录也不复用。独立新计划 `runs/verified-invoice-pinggy-low35-20261015-v2` 已生成，状态为 `prepared_not_started`。两组完整离线验证的六例全部通过，证据位于 `outputs/verified-invoice-pinggy-validation-20261015-v2`；源码哈希与新计划一致。

两组各自通过：35轮上限（70条模拟GUI命令）、第7轮终止（12条模拟GUI命令）、35轮空动作（0条GUI命令）。镜像哈希、Docker镜像及原始runtime导入检查也已通过。`check`仅做基础预检，不探测模型，因此其中的`ready_for_user_review`不能解释为网络已经可用；用户运行授权已经给出，实际阻塞来自TLS。合并状态见 `readiness.json`：`blocked_before_launch_tls_reset`。

上次已验证的当前源码回归为141项通过，Ruff通过；本次未修改Python项目代码，只切换既有provider并刷新其离线证据。原任务、原官方镜像、执行器和评分器保持同一冻结来源。离线模拟分数0.125仅为fixture哨兵，benchmark_score为null。

本次尚未启动新的Docker评测，未产生官方成绩。入口恢复前不重复创建VM。本实验所有权标签下无遗留容器。20分钟巡检继续PAUSED，只有UI-KOBE-like实际进入Docker并取得完整模型响应后才启用；不通过持续聊天或后台探测代替该条件。

## 证据

- [有密钥API阶段追踪](D:/cua_lty/osworld_verified_setup/qwen-api-preflight-20261015T105334Z.json)
- [默认地址TLS检查](D:/cua_lty/osworld_verified_setup/pinggy-tls-retry-20261015T105227Z.json)
- [固定IPv4 TLS检查](D:/cua_lty/osworld_verified_setup/pinggy-tls-retry-20261015T105335Z.json)
- [新计划](D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-invoice-pinggy-low35-20261015-v2/plan.json)
- [基础检查与网络检查合并状态](D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-invoice-pinggy-low35-20261015-v2/readiness.json)
- [当前运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)
