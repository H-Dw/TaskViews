# OSWorld-1 发票核对：Tinker 接入（2026-10-15）

本次采用 `Qwen/Qwen3.6-35B-A3B`，使用 WSL 中的 `TINKER_API_KEY`。官方模型列表页面是文档地址，不是推理 API。评测适配采用 Tinker 官方 OpenAI-compatible API：

`https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1/chat/completions`

截至本次检查，真实请求已完成 TLS 并收到 **HTTP 402**：账户计费状态禁止调用，服务要求添加付款。未收到模型 completion，未启动新的评测 VM，未启用 20 分钟巡检。不能据此声称模型、截图、工具调用或 `low` 已通过线上验证。

## 实现

- `ui_kobe/api/tinker_native.py`：独立 provider 配置，读取 Tinker 专用密钥，共用已有有界 SSE 传输、阶段诊断和输出记账。直连官方 HTTPS，禁用环境代理和空闲连接复用；不经过 Pinggy 或 Tailscale。
- `ui_kobe/osworld/tinker_native.py`：把同一个 provider 接到 UI-KOBE-like 和 Mini actor；共用既有截图处理、历史、动作校验和 OSWorld compiler。
- `scripts/verified_invoice.py prepare --provider tinker`：冻结新的独立比较计划，不覆盖旧 Qwen 失败记录。
- `scripts/probe_tinker_native.py`：独立的真实服务检查，依次验证文本、合成截图定位与 native `computer_use`、工具回执后的回答。完整 SSE、正确模型及有效工具参数均通过后才生成成功证明；不会执行 GUI 操作，也不读取发票内容。
- `launch` 在创建 VM 前要求成功的线上检查证明；402、400、401、403 均停止，无静默模型或 reasoning 回退。只收到 HTTP 200 还不算有效 completion。

| 比较设置 | 值 |
| --- | --- |
| 顺序 | UI-KOBE-like → TaskViews-mini，每组独立官方 Docker guest |
| 决策轮数 | 每组最多 35 次 predict，空动作计轮 |
| 模型 | `Qwen/Qwen3.6-35B-A3B`，不替换为 256K 后缀版本 |
| 推理请求 | 显式 `reasoning_effort=low`，`separate_reasoning=true`；服务接受性待真实验证 |
| 输出预算 | `max_tokens=16000`，每决策输出池 32000；思考与回答共用生成上限 |
| 采样 | temperature=0、top_p=0.9，延续原比较配置 |
| API 专属字段 | 不发送 Pinggy 的 `enable_thinking`、`preserve_thinking` |
| 环境和评分 | 原 OSWorld-Verified 任务、官方 OSWorld-1 Docker 镜像及 compare_pdfs；无新评分结果 |
| Mini | `mini_fixed_v1`，controls 关闭，无额外模型角色 |

用户示例中的 temperature=0.7、max_tokens=256 作为连接演示参数理解；未将它们替换进两组正式评测预算。

Tinker 官方文档明确：`reasoning_effort` 只适用于支持它的模型，不支持时返回 400。当前 402 发生在可用 completion 之前，不能从文档中的通用参数列表推断该 Qwen 型号接受 low。若解除计费限制后收到 400，本计划停止，需确定受支持的思考设置并重新冻结，不把 enabled/disabled 写成 low。

## 验证与后续入口

离线验证使用真正的 OSWorld-1 runner、actor、请求构造与动作 compiler；HTTP、GUI 与评分明确替换为 fixtures，并禁止联网和 VM 构造。两组各验证 35 轮上限、7 轮显式终止、35 轮空动作。mock 分数 0.125 是测试哨兵，实际 benchmark_score 为 null。

计划目录：`runs/verified-invoice-tinker-low35-20261015-v1`。
离线证据：`outputs/verified-invoice-tinker-validation-20261015-v1`。
真实检查保存在 `osworld_verified_setup/tinker-native-probe-20261015-v1`。

恢复 Tinker 账户计费后，从 WSL 的已有交互 shell 读取凭据，先执行一次：

```bash
cd /mnt/d/cua_lty/OSWorld-K3-TaskViews
PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope --quiet \
  --property=MemoryMax=1G --property=MemorySwapMax=0 \
  /home/dawei/osworld2/OSWorld-V2/.venv/bin/python scripts/probe_tinker_native.py \
  --root runs/verified-invoice-tinker-low35-20261015-v1 \
  --output /mnt/d/cua_lty/osworld_verified_setup/tinker-native-probe-after-billing-v1
```

使用新的 output 目录保留历次检查证据。全部通过后，已有用户运行授权仍然有效，可按既有串行 launcher 执行这个新计划。只有 **UI-KOBE-like 实际进入 guest，并收到完整有效模型响应** 后，才将现有 20 分钟 heartbeat 从 PAUSED 改为 ACTIVE；上述合成检查成功不满足这项巡检启用条件。

## Mini 的 taskviews

Mini 仍是共同 actor 加三个固定的只读投影，没有另起模型来创建视图。配置入口是 `kobe_views/fixed_views.py` 和 `ui_kobe/osworld/mini_taskviews_context.py`，不是 `configs/task_views.yaml`。

| 视图 | 来源与选择 |
| --- | --- |
| current | 当前观察、截图身份、任务输入和坐标契约 |
| attempts | SQLite journal 最近 4 条真实执行边，保留原工具参数及回执 |
| lessons | 最多 4 条已记录的执行错误和 2 条 actor 意图，区分执行事实与模型提议 |

总包上限 3000 UTF-8 bytes，attempts/lessons 条目配额分别为 1200/1000 bytes，超限整条省略并保留来源、哈希和省略计数。共同上下文预算还会限制可交付空间。UI-KOBE-like 使用最近 8 条执行边、8000-byte 上限，结果解释需同时考虑组织形式与容量差异。

新增发票、流水、差异等业务视图需要定义新的版本化 profile、来源字段、selector、过期规则、字节预算及投影器，另做测试和冻结；不能只改视图名称。本次按原三视图进行比较。

## SDK 示例的修正

官方 SDK 使用 `ServiceClient().create_sampling_client(base_model=...)` 创建 sampler；`sample` 接收 `ModelInput` 与 `sampling_params`，返回 Future，需 `.result()`；文本从 `response.sequences[0].tokens` 解码。用户示例中的 `client.sampling_client`、字符串 prompt、`params=` 和 `response.completion` 不对应当前文档接口。

修正后的独立 SDK 示例位于 `D:/cua_lty/osworld_verified_setup/tinker-sdk-example.py`，未作为成功调用证据。原生 `SamplingParams` 没有 low effort 字段；示例中的 thinking enabled 也不等于 low。评测采用官方兼容接口，以保留原 native tools/SSE 合约和显式 low 请求，无需安装本地模型权重或新增 torch。

参考：[模型列表](https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/)、[官方兼容 API](https://tinker-docs.thinkingmachines.ai/tinker/compatible-apis/openai/)、[ServiceClient](https://tinker-docs.thinkingmachines.ai/tinker/api-reference/serviceclient/)、[SamplingClient](https://tinker-docs.thinkingmachines.ai/tinker/api-reference/samplingclient/)。
