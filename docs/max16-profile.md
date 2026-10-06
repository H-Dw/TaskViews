# max/16K 新实验配置

2026-10-07 用户授权基于 v6 新代码重新运行 baseline 与 TaskViews，沿用此前 Task059/046 两任务的独立串行方式。`max-16k` 在现有注册表和准备、兼容探针入口增加一个配置；actor 与分析的接口、提示、历史、执行、评分及资源保护未改。

按此前 16K 口径固定 reasoning_effort=max、actor max_completion_tokens=16000、整步输出32000、actor保留16000、每个分析请求最多4000。这里16K指16000，不改为16384；与low/16K具有相同额度，仅思考强度不同。所有 reasoning、失败、修复及重试输出计入原整步账本，输入/输出/总usage实测记录。judge/usersim继续沿用此前K3 max/16000条件。

本次配置登记的 [定向验证](../validation/v6-max16-20261007-offline.json) 为54 passed / 0 failed / Ruff通过，固定官方源码与运行源码在测试前后未变。此前 v6 的575项完整回归原件保留；本次不冒充又执行了一次全量回归。

[真实兼容检查](../validation/k3-xml-max16-20261007.json) 使用当前源码、max/16000及预声明absolute/1920×1080；两个合成截图回合 compatible=true，实际原assistant历史和同图核对通过，输入10486+输出562=11048 token，未知费用0。动作未执行、没有VM或任务评分，不能用它代替正式评测成绩。

正式评测单独冻结新计划/源码/素材，在 ignored docs/experiments/official-qwen-v6-max16-20261007/campaign.json 管理顺序。两臂共用官方XML Agent路径和被动转换记录；TaskViews仅增加可选上下文，native作为另一协议比较保留但本轮不混入。Task046只复用未改网站/setup的既有部署证明，每个新正式组仍运行原官方reset并保存新状态导入、guest来源与真实runner共享cgroup证据。

启动adjusted5/运行4GiB、磁盘45/12与35/10GiB、硬组件总5.875GiB/零swap保持。官方result定义成绩；没有result是无有效成绩。每组原始SSE、错误、usage、截图/轨迹/转换库、模块、源码/资源与清理记录独立保存；已封存旧实验不改写、不重跑。
