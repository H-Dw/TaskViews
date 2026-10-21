# 任务级软件操作指引调研与临时按键目录

2026-10-20。新增用户 skill `task-keyboard-research`，安装于 `C:/Users/Wei/.codex/skills/task-keyboard-research/SKILL.md`；TaskViews-mini 新增默认关闭的 `--keyboard-research` 准备开关。实现版本为 `task_keyboard_research_v1`。

2026-10-21 补充：当前默认 actor 已改为 AutoDL。其公开示例只确认 Chat Completions，尚无本项目验证过的 Responses/web search 支持，因此 AutoDL 任务开启研究时必须显式提供 `--keyboard-research-config`，包含研究端点、协议、模型及密钥环境变量；不自动继承 AutoDL 聊天端点。下面的默认继承行为适用于此前 provider。

## 开关与使用方式

在已有的新实验准备命令后附加：

```text
--keyboard-research
```

支持 `scripts/osworld_native_experiment.py prepare` 的 Mini TaskViews arm，以及 `scripts/verified_invoice.py prepare` 的 invoice/VLC/GIMP 任务选项。既有任务、profile 和实验配置的限制仍适用。

不传此开关时不产生研究 API 调用，也不创建临时目录。开启后，默认复用该实验声明的 API base URL、模型及密钥环境变量，通过 Responses 接口发起准备请求；正式 CUA actor 的接口和生成配置保持原样。实际网关必须支持 `/responses` 和 `web_search` 并返回搜索来源，仅支持 `/chat/completions` 不足以确认兼容。

需要指定支持联网的研究接口时：

```text
--keyboard-research --keyboard-research-config configs/keyboard-research.responses.example.json
```

该[示例配置](../configs/keyboard-research.responses.example.json)读取 `KEYBOARD_RESEARCH_BASE_URL` 和 `KEYBOARD_RESEARCH_API_KEY` 环境变量。也提供 [DashScope 配置](../configs/keyboard-research.dashscope.example.json)，读取指定 `/api/v1` base URL 和 `DASHSCOPE_API_KEY`。不在 JSON 中保存密钥，不会把当前网关的凭证自动发送给其他提供方。

现有 `--keyboard-mode` 管理共享目录的选择；研究开关独立于它。使用 `--keyboard-mode manual --keyboard-research` 且不另加共享目录时，actor 使用 general 加本任务临时目录。使用默认 task_names 时，可同时使用此前匹配的共享目录和本任务临时目录。

仅生成资料、不准备正式实验时：

```text
python scripts/research_task_keyboard.py --prompt-file task.txt --related-app vlc --config configs/keyboard-research.responses.example.json --output outputs/my-task-keyboard
```

也可用 `--task-json <原始任务.json>` 替代 `--prompt-file`。skill 的 `scripts/research.py` 包装脚本调用同一实现，并支持 `--project` 指定项目路径。

## 准备过程

```mermaid
flowchart LR
    A[原始 instruction / related_apps] --> B[软件名提取与候选推测]
    B --> C[API 启用 web 搜索]
    C --> D[本地 Markdown 存档]
    D --> E[读取存档整理按键]
    E --> F[校验并冻结任务目录]
    F --> G[新计划准备完成]
    G --> H[原有授权和启动流程]
    H --> I[正式 CUA 按需查询]
```

1. **软件候选。** 模型读取公开任务正文、`related_apps` 和现有词典的名称匹配结果，区分 `explicit` 与 `inferred`。明确提及项保留原文短语，推测项保留理由，例如任务涉及移动文件时考虑文件管理器。该结果不证明软件已安装或在前台。
2. **联网检索。** 每个候选分别检索软件名称、Linux/X11 平台、通用操作和候选官方文档站点。搜索请求不传完整任务正文、评分器或 setup；操作术语由识别阶段生成。模型被要求省略文件路径、交付文件名、任务 ID 和私密内容。
3. **先保存 Markdown。** API 返回的调研答复、搜索范围、时间和来源写入 `archives/app-<software>.md`。这是带来源的 API 检索整理答复，不宣称是每个网页的完整镜像。
4. **再读存档整理。** 另一次关闭 web 工具的模型请求只读取已保存 Markdown 及 API 返回的来源。提取主题、作用范围、可见检查、组合键和短绑定摘录。出处 URL 必须来自 API 搜索来源，摘录必须实际出现在存档中。
5. **形成临时目录。** 通过键名、同时组合键、Linux 平台、引用和大小校验后，输出可读 `keyboard/*.md` 和运行时 `catalog.json`。生成文件的摘要与原任务摘要一起冻结。

来源仅允许使用与候选文档站点匹配的 API 返回 URL；站点候选来自软件识别模型，因此这是筛选约束，不是对网站官方身份的独立认证。原始搜索响应、候选站点和被排除的结果保留供复核。没有匹配来源或没有可靠快捷键时，可以归档结果但不生成该软件配方。

## 真实开启 API 搜索

已核对[阿里云联网搜索文档](https://help.aliyun.com/zh/model-studio/web-search/)及 [DashScope API 参考](https://help.aliyun.com/en/model-studio/qwen-api-via-dashscope)：

| 协议 | 请求中的搜索开关 | 用于核对检索来源的响应字段 |
| --- | --- | --- |
| Responses | `tools: [{"type": "web_search"}]` | `output` 中 `web_search_call.action.sources` |
| DashScope | `parameters.enable_search: true`；`search_options` 中 `forced_search/enable_source/enable_citation: true` | `output.search_info.search_results` |

API 返回非空来源后才进入整理。模型自行写出的 URL、HTTP 200 或 usage 中的搜索计数，均不单独当作“已检索到内容”的证明。没有启用代码执行、GUI 或文件访问工具。真实网关是否支持所选协议，必须由真实调用确认。

## 隔离与生命周期

默认保存位置：

```text
<新计划目录>/keyboard-research/
├── task.json                       只保存公开任务字段
├── settings.json                   研究接口和预算；不含凭证
├── discovery.json / discovery.md    明确软件、推测软件及依据
├── archives/app-*.md                先保存的联网调研资料
├── extractions/app-*.json            从归档提取的候选配方
├── keyboard/app-*.md                可读的任务专用按键目录
├── api/*.request.json               各阶段请求，不包含 Authorization
├── api/*.response.json              实际 API JSON 响应
├── usage.json                      各请求的 usage、耗时与状态
├── catalog.json                    临时运行时目录
├── README.md
└── manifest.json                   完成状态、scope ID、全部文件摘要
```

临时表示**生效范围只在此任务**，文件不会在任务结束时自动删除。失败尝试保留 `failure.json`、已完成的存档和调用记录；同一输出目录不能覆盖重试。失败时不会发布可加载目录或完成实验计划。

临时主题统一命名为 `task.<software>.<topic>`，例如 `task.vlc.snapshot`。它们作为 actor 实例自己的附加数据加载，不写入共享 `toolsets`、`task_aliases` 或既有 `tools/keyboard` 分类文件。写入共享库路径会被拒绝。

计划记录 `mini_keyboard_research`，原生入口将它复制到 manifest。运行前检查原任务和所有归档文件摘要；actor 在发起 CUA 模型请求前检查任务正文摘要，检查点还绑定本研究 scope 和内容摘要。普通任务、baseline/UI-KOBE 分支和离线 Verified 验证器清除继承的临时配置，防止沿用上个任务目录。

目录只提供参考。actor 看到已启用的主题后，在正文中请求：

```text
<key_lookup>task.vlc.snapshot</key_lookup>
```

下一轮按原有方式返回一个 keyboard 主题。当前窗口、焦点、keymap、模式与操作结果仍由画面确认。未知环境及重映射不能仅凭资料认定成功。

## 预算和实验比较

默认最多 4 个软件、每软件 2 个主题，每主题最多 4 条配方；一次软件识别加每软件一次搜索、一次整理，最多 **9 次准备请求**。配置可设置 1–6 个软件、1–3 个主题；单次最多 4096 输出 tokens、90 秒，整个准备阶段最多 600 秒。没有隐藏自动重试。

这是客户端请求和输出上限。提供方内部可能执行多次 web search，实际 usage 原样记录；未返回 usage 时保留 null，不填写 0。网络等待有截止时间，失败后不自动改接其他模型或提供方。

正式 actor 仍采用四个 View、3000 UTF-8 bytes 总预算和按需单主题派送；不在 CUA 过程中额外调用研究模型。研究请求计入独立的 `pre_cua_research` 成本，不能把开启研究后的结果描述为“全流程额外调用为 0”，也不能与历史 v7 的纯 general 条件混报。

开启开关会在 `prepare` 阶段发生模型和搜索调用；这一步早于计划冻结和正式执行。已有 `check`、`launch`、checkpoint 恢复读取冻结成果，不重新检索。对已失败或源码变化的准备使用新目录，历史实验保持原状。

## 验证状态

离线测试覆盖两种 API 的真实请求字段、先存档后整理、引用与键名校验、无来源失败、无凭证失败、关闭时零请求、档案篡改拒绝、跨任务拒绝、checkpoint 绑定，以及临时按键实际送达 actor。

最终相关回归为 13 个测试文件、354 项通过，失败 0；涵盖按键选择、原生/Verified 准备流程、Mini 控件与恢复、检查点及长轨迹。Ruff、skill 校验、共享目录生成文档同步检查、本地链接检查均通过。旧 general/catalog 备份和 v7 历史计划的摘要保持一致。

截至本次交付，当前 Windows/WSL 终端均未设置所需研究或 actor API 凭证环境变量，因此未进行真实网关联网测试。代码不将离线模拟标为实际 web 检索，也没有启动 VM 或正式 CUA 任务。技能文件及包装脚本已完成静态校验。
