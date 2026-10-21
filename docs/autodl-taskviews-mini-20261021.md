# TaskViews-mini：AutoDL 默认接口

2026-10-21。当前 `main` 的 Verified Mini 入口默认使用 AutoDL。地址和模型名称依据用户指定配置，并与 [AutoDL 官方模型文档](https://www.autodl.art/docs/Qwen3.5-397B-A17B/)核对一致。

| 设置 | 当前默认值 |
| --- | --- |
| provider | `autodl` |
| API base URL | `https://www.autodl.art/api/v1` |
| 实际请求 | `POST /chat/completions` |
| 模型 | `Qwen3.5-397B-A17B`，区分大小写 |
| 认证 | `AUTODL_API_KEY` 环境变量，Bearer token |
| 输出 | `stream=true`，请求 `stream_options.include_usage=true` |
| 输出上限 | `max_tokens=16000`，整步输出及修复共用原 32000-token 额度 |
| 采样 | 继承共同 actor：`temperature=0`、`top_p=0.9` |
| 思考模式 | 提供方默认，不发送未经确认的 `enable_thinking`、`reasoning_effort`、`preserve_thinking` |
| 默认任务配置 | `autodl-mini40`，仅 TaskViews-mini，最多 40 决策轮 |
| 可选对照 | `autodl-pair40`，baseline → Mini，分别独立运行 |

默认入口为 `scripts/verified_invoice.py`，支持 `--task invoice|gimp|vlc`。现有名称源于最初发票任务，当前已覆盖三种任务。旧 `osworld_native_experiment.py` 保留历史 OSWorld-V2/Kimi/Qwen 配置，不自动切换历史计划的提供方。

## 配置密钥

在实际运行 TaskViews 的进程中设置变量。当前执行环境为 WSL/Linux；仅在 Windows PowerShell 中设置不会自动传入 WSL。

```bash
export AUTODL_API_KEY='替换为自己的 AutoDL 令牌'
```

仓库的 [.env.example](../.env.example)仅为变量模板，程序不会自动加载 `.env`。不要将真实令牌写入源码、命令示例或计划 JSON；日志会遮蔽此环境变量的值。

## 离线验证与准备

先在已安装本项目依赖、固定 OSWorld-1 运行器和 OSWorld-V2 编译器的环境中，对每种 case 使用新目录。以下不发起真实网络请求，也不启动 VM。

```bash
for case in limit terminate empty; do
  python scripts/validate_verified_invoice.py \
    --arm taskviews --case "$case" \
    --output "outputs/autodl-mini-validation/taskviews-$case"
done
```

随后按现有流程指定镜像、资源、资产等准备参数；下列命令展示新增默认值。准备完成并不自动运行任务。

```bash
python scripts/verified_invoice.py prepare \
  --root runs/new-autodl-mini-plan \
  --validation-dir outputs/autodl-mini-validation
```

不写 `--provider` 和 `--experiment` 时分别使用 `autodl`、`autodl-mini40`。对照配置显式添加 `--experiment autodl-pair40`，并为 baseline、taskviews 分别提供全部三种离线 case。GIMP/VLC 沿用各自任务资产、已注册的执行 scope 以及独立 metric 验证要求。

需要核查旧接口时显式选择 `--provider qwen|tinker|openrouter|sx`；这些 provider 未指定 experiment 时仍使用原 `legacy-low35`。原 SX Max 40 轮配置仍需原 `sx-*` experiment。AutoDL 与旧实验标签不能混用，旧计划不会被改写。

## 实际接口检查

AutoDL 官方示例证明了文本流式接口的请求方式，并未提供本项目所需的视觉、native tools 或联网搜索兼容性证明。正式任务继续要求当前源码对应的实际文本、图像工具调用、tool reply 和 Mini 定位检查；使用新证据目录。

```bash
python scripts/probe_native_provider.py \
  --root runs/new-autodl-mini-plan --output outputs/autodl-live-provider

# 在原注册的 128 MiB / 零 swap 辅助 scope 中执行：
python scripts/probe_mini_grounding.py --live \
  --root runs/new-autodl-mini-plan --output outputs/autodl-mini-grounding
```

这些诊断会产生真实 API 调用和费用，但不启动 VM、不操作真实 GUI。正式 CUA 仍使用原 `check`、`launch` 流程和原执行授权要求；这里的接口接入不构成自动启动实验。

## 实现与兼容边界

- 新增独立 [API 适配](../ui_kobe/api/autodl_native.py)与 [actor 适配](../ui_kobe/osworld/autodl_native.py)，复用原流式传输、截止时间、预算和修复逻辑。没有把旧 Qwen 模块的端点或模型全局替换。
- 支持空 `choices` 用量尾帧、文本/思考片段和分片工具参数；只有完整流通过响应及工具身份校验后才交给原编译器。保留原始 SSE、工具 ID 和真实 usage；缺少 usage 仍记为未知。
- HTTP 400/401/403、余额阻断及不兼容字段不会触发更换接口、模型或凭证。AutoDL API 默认不继承系统代理；GitHub 同步仍使用此前配置的 VPN 出口。
- Mini 的四个 View、3000 UTF-8 bytes 上限、图像像素与坐标契约保持；使用已有 12 MB 请求封装上限容纳原 8 MiB 无损 PNG，未增加图像数、文本或输出额度。
- 按键研究默认关闭。启用时须另传完整的 `--keyboard-research-config`，选择支持 Responses/web search 或 DashScope 搜索及来源返回的端点。AutoDL Chat Completions 不自动被当作搜索服务。

## 本次验证结果

- 16 个相关测试文件，327 项通过、0 失败；覆盖 AutoDL 传输、流式工具参数、缺失用量、异常响应、凭证隔离、默认选项、旧 provider、按键研究和 Mini 行为。Ruff 与 Git diff 检查通过。
- 原 OSWorld-1 运行器的 6 个独立离线集成全部通过：`autodl-mini40/taskviews` 与 `autodl-pair40/baseline` 各执行 `limit`、`terminate`、`empty` 三种情况。模拟请求数分别为 40、7、40；提前终止场景同时覆盖大图。Mini 读取四个 View，baseline 不读取 View。
- 本地证据分别保存在 `outputs/autodl-provider-20261021-v1/` 和 `outputs/autodl-baseline-20261021-v1/`，按原规则不提交原始输出。全部标注 `live_api_called=false`、`vm_started=false`、`benchmark_score=null`；运行器打印的 0.125 只是模拟评估哨兵值。
- 旧 v7 冻结计划的 SHA-256 仍为 `bda6a92e8b83a1a5b773b3522a77d83bdcf7289ca0117f280f5f9795d368cac4`。

本次交付环境未设置 `AUTODL_API_KEY`，因此真实网关、图像输入、工具调用及其计费行为尚未实测；离线模拟不记为实际接口成功。没有启动正式 CUA 实验。
