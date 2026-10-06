# OSWorld K3 TaskViews

两臂共用 OSWorld 官方截图处理、动作 schema、完整批次编译、执行、任务 reset 和评分。K3 层负责原生工具消息、流式传输、供应商参数、真实工具身份与费用记账。TaskViews 只追加当前截图对应的语义证据和规划建议。

官方底座固定为 `xlang-ai/OSWorld-V2@3d778a3c9a34a079316f70df023b166700445792`，从外部 checkout 加载；仓库不复制或修改官方执行器、评分器或任务答案。运行前逐字节检查关键官方文件，并保存运行前后源码索引。

## 共同 CUA 契约

- 默认配置：[cua-v5-absolute.json](configs/cua-v5-absolute.json)。预先选择官方 **absolute**，模型图固定 **1920×1080**，所有动作均以这张模型图的像素为单位。原图可以有其他尺寸，官方投影负责映射回 guest。
- 可选配置：[cua-v5-relative.json](configs/cua-v5-relative.json)。预先选择官方 **relative**，使用官方图片 resize，动作每轴 **0..1000**。实际模型图尺寸仍随 frame 保存；感知 bbox 始终是模型图像素。
- 两种配置都不猜单位、不夹取非法点、不执行非法批次的合法前缀。禁止根据某次模型输出临时切换模式。
- 同一 frame 对象生成 schema、提示、模型图片、元数据和官方编译参数。TaskViews 所有角色与 actor 使用完全相同的图片。
- 历史默认使用官方 runner 的 500 轮、20 图、10 轮折叠步幅，调用官方 `folded_prefix`。native assistant reasoning、工具 ID 和实际反馈成组保留，按完整轮次裁剪；不复制 XML 历史的 success 占位。
- actor 保留官方默认的最多两次动作修复；TaskViews 分析共用另一个最多两次修复池。所有请求仍共用原整步时间/输出预算，失败与未知费用保留。分析不能消耗 actor 输出预留；分析还须提前让出 actor 的完整生成时间窗口。修复次数不保证在额度耗尽后仍可重试。
- TaskViews 的业务 JSON、角色范围在同一个有界校验修复流程中检查；控制器收到各消费者实际允许的 anchors。权限与范围检查继续生效。最终分析不可用时，原目标与同一截图继续交给 actor。
- 关闭 terminal judge、endless retry、summary LLM 和 zoom；不支持的开关明确拒绝。模型显式 terminate 或官方决策上限后，由原 runner 执行原任务评估。模型 success 与官方得分分开记录。

完整实现与取舍见 [接口优化说明](docs/cua-v5.md)。这些修改未经过新在线评测；单位合法不等于视觉目标识别正确。

## 离线验证

使用 Ubuntu-24.04、官方 `.venv/bin/python`，同一注册的 128 MiB / 零 swap scope。测试仅使用本地官方代码、模拟模型响应和模拟资源；不操作 GUI 或访问模型 API。

```bash
cd /mnt/d/cua_lty/OSWorld-K3-TaskViews
PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope \
  --property=MemoryMax=128M --property=MemorySwapMax=0 \
  /home/dawei/osworld2/OSWorld-V2/.venv/bin/python scripts/validate_cua.py \
  --dev-site-packages /mnt/d/cua_lty/UI-KOBE-TaskViews/.venv/lib/python3.12/site-packages \
  --ruff /mnt/d/cua_lty/UI-KOBE-TaskViews/.venv/bin/ruff \
  --output validation/offline.json
```

`--dev-site-packages` 仅指定已有测试依赖位置，不读取旧实验；在新环境安装开发依赖后可以省略。测试文件按顺序运行，每个文件完成后以 `exec` 替换当前解释器；始终是同一个 PID、同一个 scope，不保留额外 Python 报告进程。

本次 [离线验证](validation/offline.json)：**554 项通过，0 失败，Ruff 通过**；官方和项目运行源码在验证前后保持一致。128 MiB / 零 swap，`oom=0`、`oom_kill=0`。覆盖范围与开发中间失败见 [验证说明](docs/validation.md)。新环境使用同一 checkout 的开发依赖，并在准备计划前重新生成与当前源码对应的验证记录。

## 新实验入口

只支持 v5 的新冻结计划。上一批 v4 的计划、证据、源码与分数保持原样，不能让新代码继续旧目录，也不自动重跑旧实验。

完成离线验证后，准备计划时通过 `--cua-config` 冻结共同契约；两臂只能使用这一个计划中的配置。例如以下命令只准备计划，不创建 VM：

```bash
PYTHONDONTWRITEBYTECODE=1 systemd-run --user --scope \
  --property=MemoryMax=128M --property=MemorySwapMax=0 \
  /home/dawei/osworld2/OSWorld-V2/.venv/bin/python scripts/osworld_native_experiment.py prepare \
  --root /mnt/d/cua_lty/OSWorld-K3-TaskViews/runs/new-task059-plan \
  --task 059 --profile max-32k --validation validation/offline.json \
  --cua-config configs/cua-v5-absolute.json
```

实际启动由 `osworld_native_experiment.py launch --root <新计划> --arm baseline|taskviews` 完成，必须继续放在 128 MiB 辅助 scope 中。保留串行运行、VM 3 GiB、service 2 GiB、网站合计 0.75 GiB、单个辅助 128 MiB、禁止 swap、启动 adjusted 5 / 运行 4 GiB 和磁盘保护。Task046 另需当前源码对应的官方 setup/网站部署准入证明；此仓库没有把旧证明冒充为新版本已验证。不要手工调用内部 runner 绕过准入。

本次仅交付源码和离线验证，没有创建新实验计划或启动服务。

`ui_kobe`、`kobe_views` 与部分旧集成/测试工具保留上游来源；旧 GLM/Qwen/Task035 入口不属于本次共同 native CUA 路径。不要据其旧单动作策略推断当前 native 行为。项目是本地新 Git 仓库，尚未建立 GitHub 远程或推送。
