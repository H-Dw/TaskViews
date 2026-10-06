# OSWorld K3 TaskViews

两臂共用 OSWorld 官方执行与评分，以及被动的执行转换记录。v6 的首选路径直接继承固定版本 QwenAgent，保留其 `predict`、提示、历史、XML 解析和修复；薄 K3 层只适配供应商参数、完整 SSE 与原始响应历史。TaskViews 在同一路径增加可选上下文提供器，从转换图维护任务模块和自适应视图。

迁移前必须取得当前源码、配置与 K3 的真实 XML/历史兼容证明。K3 native function calls 仍保留为另一组预先选择的两臂比较；不混用协议，不根据某次输出自动切换。实现、UI-KOBE 关系与证据限制见 [v6 说明](docs/cua-v6.md)。

官方底座固定为 `xlang-ai/OSWorld-V2@3d778a3c9a34a079316f70df023b166700445792`，从外部 checkout 加载；仓库不复制或修改官方执行器、评分器或任务答案。运行前逐字节检查关键官方文件，并保存运行前后源码索引。

## 共同 CUA 契约

- 默认配置：[cua-v5-absolute.json](configs/cua-v5-absolute.json)。预先选择官方 **absolute**，模型图固定 **1920×1080**，所有动作均以这张模型图的像素为单位。原图可以有其他尺寸，官方投影负责映射回 guest。
- 可选配置：[cua-v5-relative.json](configs/cua-v5-relative.json)。预先选择官方 **relative**，使用官方图片 resize，动作每轴 **0..1000**。实际模型图尺寸仍随 frame 保存；感知 bbox 始终是模型图像素。
- 两种配置都不猜单位、不夹取非法点、不执行非法批次的合法前缀。禁止根据某次模型输出临时切换模式。
- 同一 frame 对象生成 schema、提示、模型图片、元数据和官方编译参数。TaskViews 所有角色与 actor 使用完全相同的图片。
- 历史默认使用官方 runner 的 500 轮、20 图、10 轮折叠步幅。XML 路径使用官方 `build_messages`、上下文处理与原修复提示；原始 K3 reasoning/content 在供应商请求中恢复。官方 XML 历史的 success 文本是合成反馈，不冒充真实回执。native 组单独保留完整 assistant/tool ID 与实际反馈。
- actor 保留官方默认的最多两次动作修复；TaskViews 分析共用另一个最多两次修复池。所有请求仍共用原整步时间/输出预算，失败与未知费用保留。分析不能消耗 actor 输出预留；分析还须提前让出 actor 的完整生成时间窗口。修复次数不保证在额度耗尽后仍可重试。
- TaskViews 的业务 JSON、角色范围在同一个有界校验修复流程中检查；控制器收到各消费者实际允许的 anchors。权限与范围检查继续生效。最终分析不可用时，原目标与同一截图继续交给 actor。
- 关闭 terminal judge、endless retry、summary LLM 和 zoom；不支持的开关明确拒绝。模型显式 terminate 或官方决策上限后，由原 runner 执行原任务评估。模型 success 与官方得分分开记录。

此前 v5 实现见 [接口优化说明](docs/cua-v5.md)。v6 未进行新的在线任务评测；协议兼容探针不等于任务成绩，单位合法也不等于视觉目标识别正确。

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
  --output validation/v6-offline.json
```

`--dev-site-packages` 仅指定已有测试依赖位置，不读取旧实验；在新环境安装开发依赖后可以省略。测试文件按顺序运行，每个文件完成后以 `exec` 替换当前解释器；始终是同一个 PID、同一个 scope，不保留额外 Python 报告进程。

v5 的 [原离线验证](validation/offline.json) 保留。v6 的 [新验证记录](validation/v6-offline.json) 为 **575 passed、0 failed、Ruff 通过**，并新增不可修改事件、逐动作转换、任务模块恢复、视图变化与官方 Agent 历史/修复兼容测试。详细证据见 [v6 验证说明](docs/v6-validation.md)。新环境须重新生成与当前源码对应的验证记录。

## 新实验入口

只支持 v6 的新冻结计划。上一批 v4/v5 的计划和证据保持原样，不能让新代码继续旧目录，也不自动重跑旧实验。

先在同一个 128 MiB / 零 swap 辅助 scope 内运行 `scripts/probe_k3_official_compatibility.py --profile max-32k --output outputs/new-k3-xml-proof.json`，验证两个合成截图回合的真实 K3 XML 响应及原始 assistant 历史。每次使用新的证据路径。探针不执行动作、不创建 VM，也不评分。需可用的 `KIMI_API_KEY`；无凭证、传输错误或 length 不等于 K3 不支持 XML。

完成离线验证后，准备计划时通过 `--cua-config` 冻结共同契约；两臂只能使用这一个计划中的配置。例如以下命令只准备计划，不创建 VM：

```bash
PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope \
  --property=MemoryMax=128M --property=MemorySwapMax=0 \
  /home/dawei/osworld2/OSWorld-V2/.venv/bin/python scripts/osworld_native_experiment.py prepare \
  --root /mnt/d/cua_lty/OSWorld-K3-TaskViews/runs/new-task059-plan \
  --task 059 --profile max-32k --validation validation/v6-offline.json \
  --cua-config configs/cua-v5-absolute.json \
  --agent-interface official-xml --k3-compatibility validation/k3-xml-max32-final.json
```

实际启动由 `osworld_native_experiment.py launch --root <新计划> --arm baseline|taskviews` 完成，必须继续放在 128 MiB 辅助 scope 中。保留串行运行、VM 3 GiB、service 2 GiB、网站合计 0.75 GiB、单个辅助 128 MiB、禁止 swap、启动 adjusted 5 / 运行 4 GiB 和磁盘保护。Task046 另需当前源码对应的官方 setup/网站部署准入证明；此仓库没有把旧证明冒充为新版本已验证。不要手工调用内部 runner 绕过准入。

若选择 `--agent-interface k3-native`，两臂都使用同一个 native 适配器，作为单独的比较组。XML 迁移证据不能代替其他 profile、截图契约或修改后源码的兼容检查。配置文件的 v5 名称保持，但共同截图/坐标配置继续供 v6 使用。

本次交付源码、离线验证与协议检查工具，没有创建新任务实验计划或启动评测服务。

`ui_kobe`、`kobe_views` 与部分旧集成/测试工具保留上游来源；旧 GLM/Qwen/Task035 入口不属于本次 v6 比较路径。不要据其旧单动作策略推断当前行为。项目是本地 Git 仓库，尚未建立 GitHub 远程或推送。
