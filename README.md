# OSWorld K3 TaskViews

2026-10-16：Mini 优化已提交为 `2c6662c`。新增随想 `qwen3.8-max`、思考 `high`、每组 40 轮的 UI-KOBE-like → LLM baseline → TaskViews-mini 三组入口，使用显式归一化坐标和共同资源预算。配置与验证见 [Max/high 三组说明](docs/osworld-verified-invoice-sx-max-high40.md)，实际运行进度见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。

2026-10-15最终结果：随想qwen3.8-flash / low的v5发票核对比较已完成，UI-KOBE-like与TaskViews-mini各35轮，官方得分均0.0。内存检查通过，容器清理、源码校验完成，巡检已暂停。见 [最终报告](docs/osworld-verified-invoice-sx-flash-results-20261015.md)。下文保留实现和历史记录。

2026-10-15 21:58：按用户确认采用“真实空闲RAM>2GiB＋单独核算本项目占用”的新内存规则。56项相关回归、六例离线集成、大图在线检查和实测计数预检通过，独立v5计划已在真实环境取得完整模型响应及动作回执，20分钟巡检已恢复。模型qwen3.8-flash / low，UI-KOBE-like → Mini各最多35轮。机制见 [2GiB内存规则](docs/osworld-verified-memory-policy-20261015.md)，实时状态见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。下文保留历史记录。

2026-10-15 21:41巡检：v4在UI-KOBE-like完成9轮后因Windows可用RAM降至3.821GiB触发4GiB保护；9次模型调用完整返回，容器已清理、未评分、Mini未启动。巡检已通过应用工具暂停。证据和后续所需处理见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。下文保留启动与历史说明。

2026-10-15 21:16，按用户明确指令以新v4目录重新运行随想qwen3.8-flash / low的UI-KOBE-like → Mini比较，各最多35轮。启动前可用RAM约11.6GiB、零swap，代码与配置沿用已验证版本；v3历史记录保留。UI-KOBE-like已在真实环境取得完整模型响应与动作回执，应用已确认20分钟巡检恢复ACTIVE。实时进度见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。

OSWorld-Verified（OSWorld-1）的发票与流水核对入口为 `scripts/verified_invoice.py`。2026-10-15按用户指令使用随想接口、环境变量 `SX_QWEN_API_KEY` 和 `SX_URL_SB`、模型 `qwen3.8-flash` / low，每组最多35决策，UI-KOBE-like → Mini串行。含大图的真实接口检查、六例离线集成及运行预检通过；v3真实运行完成14轮及14次完整模型响应后，因Windows可用RAM降至3.736GiB触发4GiB保护，已清理容器，未取得评分、Mini未启动。当前配置与状态见 [随想接入说明](docs/osworld-verified-invoice-sx-flash.md)；历史证据均保留。

`mini` 分支提供 **TaskViews Mini M0**：一个共同 native actor、三个固定只读 views、零额外分析角色请求、显式 profile 与检查点。后续 Mini 测试先执行 `git switch mini`，使用带分支检查的 `scripts/validate_mini.py`。实现、配置和运行边界见 [Mini 使用说明](docs/taskviews-mini.md)，后续分层接入见 [路线图](docs/taskviews-mini-roadmap-20261012.md)。当前暂停的完整 V12 不迁移为 Mini。

以下 v7 说明是旧 Kimi 比较路径的历史接口文档，不是 Mini 或 Qwen 完整版的当前配置。v7 分为 **baseline、UI-KOBE-like、TaskViews 三组**，共用同一套 actor、K3 协议适配、截图/坐标契约和官方执行评分。baseline 不创建转换图数据库，也不读取扩展记忆；UI-KOBE-like 单独测试执行边的保存与检索，TaskViews 在此基础上增加任务模块和自适应视图。详见 [三组 actor 与证据边界](docs/cua-v7.md)。

baseline 的提示保留固定官方文本，native 路径仅替换 XML 的传输格式说明；移除项目追加的提示增强。模型只接收最小工具结果、真实错误或用户答复。原始 SSE、完整命令、控制器回执、后截图和评分保存在独立审计中，不自动拼入模型反馈。实验组只能通过有界可选上下文消费其记录。

native 三组继承同一个 `KimiNativeAgent.predict`，这是 native 协议桥接，不能称为未经修改的官方 QwenAgent。另行预选的 official-xml 三组继承固定 QwenAgent 的 `predict`、提示、历史、XML 解析和修复。两条协议路径独立冻结，不自动切换。

2026-10-07 的接口修复见 [空字段与被动记录修复](docs/native-cua-fixes.md)：复用固定官方客户端的空文本兼容规则，修复 SQLite 事件引用输出的字段冲突，并用三份真实失败 SSE 回归。新的 native 动作链路验证预选相同 absolute 1920×1080 契约，串行运行两臂；短程链路检查与正式任务成绩分开。

此前两臂真实 native 短程验证见 [原测试报告](docs/native-cua-validation-20261007.md)。它使用修订前的提示、扩展反馈与共同 SQLite，属于历史验证，不能代替 v7 三组的新在线验证。旧评分、分析失败、未知费用和证据保持原样。

选择 official-xml 前必须取得当前源码、配置与 K3 的真实 XML/历史兼容证明。此前实现、UI-KOBE 关系与证据限制见 [v6 历史说明](docs/cua-v6.md)。

官方底座固定为 `xlang-ai/OSWorld-V2@3d778a3c9a34a079316f70df023b166700445792`，从外部 checkout 加载；仓库不复制或修改官方执行器、评分器或任务答案。运行前逐字节检查关键官方文件，并保存运行前后源码索引。

## v7 历史 CUA 契约

- 默认配置：[cua-v5-absolute.json](configs/cua-v5-absolute.json)。预先选择官方 **absolute**，模型图固定 **1920×1080**，所有动作均以这张模型图的像素为单位。原图可以有其他尺寸，官方投影负责映射回 guest。
- 可选配置：[cua-v5-relative.json](configs/cua-v5-relative.json)。预先选择官方 **relative**，使用官方图片 resize，动作每轴 **0..1000**。实际模型图尺寸仍随 frame 保存；感知 bbox 始终是模型图像素。
- 两种配置都不猜单位、不夹取非法点、不执行非法批次的合法前缀。禁止根据某次模型输出临时切换模式。
- 同一 frame 对象生成 schema、提示、模型图片、元数据和官方编译参数。TaskViews 所有角色与 actor 使用完全相同的图片。
- 历史默认使用官方 runner 的 500 轮、20 图、10 轮折叠步幅。XML 路径使用官方 `build_messages`、上下文处理与原修复提示；原始 K3 reasoning/content 在供应商请求中恢复。官方 XML 历史的 success 文本是合成反馈，不冒充真实回执。native 使用同一份官方历史工具、原始 assistant/tool ID 和最小结果反馈，原任务放在首个保留观察中；其整轮裁剪不是官方 XML 摘要流程。
- 三组 actor 都保留最多两次动作修复、相同输出预算和完整执行期限。TaskViews 分析使用独立的账本、分析期限和两次分析修复池，不减少 actor 的可用额度。所有失败、修复、重试和未知费用分别保留；实验组的额外成本必须报告，不能声称总预算相等。
- TaskViews 的业务 JSON、角色范围在同一个有界校验修复流程中检查；控制器收到各消费者实际允许的 anchors。权限与范围检查继续生效。最终分析不可用时，原目标与同一截图继续交给 actor。
- 关闭 terminal judge、endless retry、一般 summary folding 和 zoom；XML 的原官方 context rescue 仍可调用摘要 LLM，native 历史封装另列。模型显式 terminate 或官方决策上限后，由原 runner 执行原任务评估。模型 success 与官方得分分开记录。

此前 v5 实现见 [接口优化说明](docs/cua-v5.md)。v6 official-xml 四组评测已封存，其失败分析见 [接口异常分析](docs/analysis/v6-k3-interface-failure-20261007/report.md)。协议兼容探针不等于任务成绩，单位合法也不等于视觉目标识别正确。

新授权的 max/16K 配置及单独验证见 [max16 配置说明](docs/max16-profile.md)：max/16000、整步32000、actor保留16000、分析4000。正式任务评测记录与此前兼容探针分开管理。

## 离线验证

使用 Ubuntu-24.04、官方 `.venv/bin/python`，同一注册的 128 MiB / 零 swap scope。测试仅使用本地官方代码、模拟模型响应和模拟资源；不操作 GUI 或访问模型 API。

```bash
cd /mnt/d/cua_lty/OSWorld-K3-TaskViews
PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope \
  --property=MemoryMax=128M --property=MemorySwapMax=0 \
  /home/dawei/osworld2/OSWorld-V2/.venv/bin/python scripts/validate_cua.py \
  --dev-site-packages /mnt/d/cua_lty/UI-KOBE-TaskViews/.venv/lib/python3.12/site-packages \
  --ruff /mnt/d/cua_lty/UI-KOBE-TaskViews/.venv/bin/ruff \
  --output validation/three-arm-actor-v7-20261007-complete.json
```

`--dev-site-packages` 仅指定已有测试依赖位置，不读取旧实验；在新环境安装开发依赖后可以省略。测试文件按顺序运行，每个文件完成后以 `exec` 替换当前解释器；始终是同一个 PID、同一个 scope，不保留额外 Python 报告进程。

v7 的 [离线验证](validation/three-arm-actor-v7-20261007-complete.json) 为 **614 passed、0 failed、Ruff 通过**，核验三组 actor 一致、baseline 无转换库、审计与模型反馈分离、原工具 ID、分析预算隔离和官方底座未改。此前 [v6 验证](docs/v6-validation.md) 与 v5 原件保留，不能当作当前源码的验证记录。

## v7 历史实验入口

只支持 v7 的新三组冻结计划。上一批 v4/v5/v6 的计划和证据保持原样，不能让新代码继续旧目录，也不自动重跑旧实验。

仅选择 official-xml 时，先在同一个 128 MiB / 零 swap 辅助 scope 内运行 `scripts/probe_k3_official_compatibility.py --profile max-16k --output outputs/new-k3-xml-proof.json`，验证真实 K3 XML 响应及原始 assistant 历史。每次使用新的证据路径。探针不执行动作、不创建 VM，也不评分。需可用的 `KIMI_API_KEY`；无凭证、传输错误或 length 不等于 K3 不支持 XML。

完成离线验证后，准备计划时通过 `--cua-config` 冻结共同契约；三组只能使用这一个计划中的配置。例如以下命令只准备 native 计划，不创建 VM：

```bash
PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope \
  --property=MemoryMax=128M --property=MemorySwapMax=0 \
  /home/dawei/osworld2/OSWorld-V2/.venv/bin/python scripts/osworld_native_experiment.py prepare \
  --root /mnt/d/cua_lty/OSWorld-K3-TaskViews/runs/new-task059-plan \
  --task 059 --profile max-16k --validation validation/three-arm-actor-v7-20261007-complete.json \
  --cua-config configs/cua-v5-absolute.json \
  --agent-interface k3-native
```

实际启动由 `osworld_native_experiment.py launch --root <新计划> --arm baseline|ui_kobe_like|taskviews` 完成，必须继续放在 128 MiB 辅助 scope 中，并取得新实验授权。保留串行运行、VM 3 GiB、service 2 GiB、网站合计 0.75 GiB、单个辅助 128 MiB、禁止 swap、启动 adjusted 5 / 运行 4 GiB 和磁盘保护。Task046 另需当前源码对应的官方 setup/网站部署准入证明；此仓库没有把旧证明冒充为新版本已验证。不要手工调用内部 runner 绕过准入。

XML 迁移证据不能代替其他 profile、截图契约或修改后源码的兼容检查。配置文件的 v5 名称保持，共同截图/坐标配置供 v7 使用；当前可选上下文预留为0，超出 actor 既有上下文上限时省略完整可选包，不挤出原历史。

为接口验证可预先声明 `--purpose cua_smoke --max-steps 3 --agent-interface k3-native`，使用 Task059 原任务和官方 runner 的短程决策上限。三组共用同一冻结计划；`benchmark_comparable=false`，不得与正式 500 决策任务成绩比较。正式 evaluation 的上限保持 500。

`ui_kobe`、`kobe_views` 与部分旧集成/测试工具保留上游来源；旧 GLM/Qwen/Task035 入口不属于本次 v7 比较路径。不要据其旧单动作策略推断当前行为。项目是本地 Git 仓库，尚未建立 GitHub 远程或推送。
