# TaskViews Mini：v7 之后的实验与版本总账

整理日期：2026-10-29（北京时间）。依据本线程请求、冻结计划、source-snapshots、原 outcome、结果汇总及后续审计。本次只提交当前代码和生成派生报告，没有新模型请求、GUI 评估或评分重跑。

**当前代码已提交：`3800520e4f1ae68c97fe5896076c24746145d825`**，标题为 Add cross-view Mini modes and applicability-first guidance。这次提交收拢 v7 之后积累的 Graph、送达、阶段指导、阅读支持及适用性改动；最新候选尚无线上分数。此前 674 项相关离线测试、Ruff、差异与冻结来源校验通过，提交前源码哈希再次匹配。

**两个重要的版本边界：** 历史 Mini v7 是 `ae27018`；后来的 capability_guidance_v3/v7 是指导模块版本。legacy、flat 是 View 表示方式，随公共 actor 和指导代码一起变化，不能当作固定代码版本。历史 Mini v3 的 22 决策记录来自 `0a5b6f2`，不是 `5a839d9`。

**早期 Graph 的 commit 限制：** G00–G03 的计划只记录 `6d9e0d76527ef7d6b6b46e4eee984dc7b498ccc9` 基线，加各自 `project_source` 冻结哈希。当时的 Graph/纠错修改没有独立 commit，因此不能声称原样运行此基线就能复现实验。逐格 manifest 哈希保存在配套 JSON；从 delivery-v2 起的实验另有真实冻结快照 commit，已核对快照 HEAD、全部 manifest 文件和关键运行模块的 commit blob。

**统计口径：** 输出 tokens 包含推理 tokens；≥ 为缺失部分请求 usage 的已知下界，不是总量。GUI 包括显式截图回执，派发还可包括 DONE/WAIT；没有记录的字段留未知。正常 0 分是有效结果；异常未评分、未启动及预检不计入有效分数。发票/GIMP 保留官方 0/1，VLC 保留原连续分数。各格通常仅一次、不同日期模型别名后端未固定，不给出显著性或单模块因果结论。

## 版本和修改措施

|阶段|实验代码 commit／身份|代码修改措施|
|---|---|---|
|历史 Mini v7 参照|`ae27018a99f67329c1d3547f66017e55bf3cd03b`|辅助报告与原生错误分流、短纠错、同轮重新准入；累计包含产物来源校验、主动动作证据和分层 keyboard。|
|主线／AutoDL（工程交付）|`5a839d9` → `6d9e0d7`|扩充 general、软件目录匹配、可选任务研究；新增 AutoDL 默认模型。后续正式表仍显式使用 SX qwen3.8-max，没有 AutoDL 任务成绩。|
|G00 Graph 初版／两次中断|`6d9e0d7` + 未提交冻结 manifest（修订见行名）|Graph 三模式、统一 ID 和显式来源关系；此处记录资源保护和服务流超时中断。|
|G01 Graph r003-resume02|`6d9e0d7` + 未提交冻结 manifest（修订见行名）|legacy/flat/linked × high/low；新增稳定实体、跨 View 引用及来源 links，仍为 3000 bytes，无图检索／路径规划。|
|G02 Graph r005|`6d9e0d7` + 未提交冻结 manifest（修订见行名）|增强复核引用纠错和实际投递统计；第 2 格暴露观察 ID 模板字符串／整数冲突。|
|G03 Graph r007|`6d9e0d7` + 未提交冻结 manifest（修订见行名）|OBS_SEQ 改为无引号正整数；保留严格校验、两次纠错及原预算。三任务 18 格重新冻结。|
|D02 送达优化 delivery-v2|`ae27018a99f67329c1d3547f66017e55bf3cd03b`<br>`ec4827d7a009381b86b85b79a7ceb6de80a486c9`|压缩 ID、重复状态与来源字段，恢复 keyboard/lookup 和最近动作的预算优先级；仍存在单条配方前缀选择。|
|K01 能力指导 v1／四版本 low|`5a66b7ec8487193b1c93b8ff84902743e5abbb16`<br>`ae27018a99f67329c1d3547f66017e55bf3cd03b`<br>`b8c13ab5382f850008f90a5722923875826195e3`|能力与辅助目录冻结、确定性自动指导、剪贴板阶段、依赖与替代组；另测 v3 宿主＋新 keyboard 和原 v7。|
|K01-oldkeys-blocked 原 v3 keyboard／三任务计划|`729b8163512594154621de7867cf84ae17d9cda6`<br>`f361af5f1c160f019536c991853424b4a8dd0ca0`|为 v7 和当前 legacy 安装原 v3 目录、选题及同 episode 记忆；资源不足，正式任务 0/6。|
|K02 能力指导 v2|`2dccd24923c09c643b7a24cfb8b262e8c906c9a6`|区分动作／状态及 cut off、open menu、zoom in；补文件转移与阅读能力，短完整阶段卡，明确原 v3 整轮历史策略。|
|K02-oldkeys 原 v3 keyboard／两任务|`068d28fc08a45a2f3a6972a146c795c4993b07b7`<br>`8933b1f9e8bfd0954a8159d2027c265701936964`|当前宿主仅恢复原 v3 按键目录、选题和记忆；保留宿主复核、公共提示和打包。原 v7 适配为另一个快照。|
|K03 能力指导 v3／full–compact|`216a14edc2f3dc45c44ab72a9a97221e832044ac`|统一完整组、拖动／缩放／修饰键反馈、短阅读 proposal 与通用收尾；full/compact 同完整成本选事实，压缩后不回填。|
|K04 能力指导 v4／always–stage|`f277ea78f78ccdf72d5c7eb43c4110d30be07e71`|待确认效果、阅读保留和最小上下文；legacy/low 仅比较复核展示时机，均为 full 措辞、fixed_reference 预算。|
|A01 原 v3 工作流／clipboard 两格|`2a9dbd0d59eed5ebbcbde1f2c7fba82d2f155622`<br>`4dd4f2b3564dc8a14d7cc18ab14e44435cb16802`|均为原 v3 核心；只把 file_transfer.scope 的完整流程连接说明改为独立 clipboard 参考。运行源码不含同期新指导 v5。|
|R01 历史 22 决策提交单次复现|`0a5b6f2a8824008dc3bba01803b1b43369016627`|完整历史 0a5b6f2 冻结源码，仅一次发票/low；作为 v3 参照复现，不是当前版本测评。|
|B01 GIMP LLM baseline low 补测|`f277ea78f78ccdf72d5c7eb43c4110d30be07e71`|仅 baseline，关闭 TaskViews；使用与指导 v4 相同冻结代码，单次 low 对照。|
|当前代码|`3800520e4f1ae68c97fe5896076c24746145d825`|收拢上述底座和指导 v5/v6/v7；最新适用性门禁无线上测评。|

快照的宿主基础提交、键盘适配及逐文件哈希见配套 JSON。`5a66b7e` 是 `4dd4f2b` 宿主加新 keyboard；`8933b1f` 是 `2dccd249` 宿主加原 v3 keyboard；`068d28f` 是 `ae27018` 加原 v3 keyboard。`729b816`/`f361af5` 对应另一轮资源阻塞而未运行的适配计划。

## 历史参考（不计入后续实验的完成数量）

|历史条件|commit|分数|决策|GUI／派发|API尝试／完整|输出|其中推理|
|---|---|---:|---:|---|---|---:|---:|
|invoice-baseline-high|`0eff2324d79171f3609a49a94b4a0310546b8c42`|1.0|40|40/42|41/41|13302|10306|
|gimp-baseline-high|`4dd4f2b3564dc8a14d7cc18ab14e44435cb16802`|1.0|28|46/49|29/28|26450|23297|
|vlc-baseline-high|`4dd4f2b3564dc8a14d7cc18ab14e44435cb16802`|1.0|13|30/31|13/13|6143|4424|
|supplied-invoice-low_baseline|`0a5b6f2a8824008dc3bba01803b1b43369016627`|1.0|28|27/28|28/28|7803|4723|
|supplied-invoice-low_mini|`0a5b6f2a8824008dc3bba01803b1b43369016627`|1.0|22|22/23|22/22|6095|3865|
|supplied-invoice-high_mini|`e5451c8f53b80c83e9a18da7fca3ac6ee44f4c8e`|1.0|26|25/26|26/26|9952|7604|
|supplied-gimp-historical_mini_v3|`4dd4f2b3564dc8a14d7cc18ab14e44435cb16802`|1.0|28|27/28|28/28|12688|10490|
|supplied-vlc-historical_mini_v3|`4dd4f2b3564dc8a14d7cc18ab14e44435cb16802`|0.08199028328542753|25|56/73|25/25|28556|24818|
|supplied-vlc-historical_mini_v7|`ae27018a99f67329c1d3547f66017e55bf3cd03b`|1.0|9|19/20|9/9|6807|5505|

原 v3 GIMP 是 high，不能与后续 low 直接作同档成本比较。原 v7 VLC high 的 1 分／9 决策不等于后续 low 的固定预期；后续原 v7 的三任务 low 测试见 K01。历史来源：[纠正后的历史审计](/D:/cua_lty/OSWorld-K3-TaskViews/outputs/mini-5a839d9-comparison-20261024/supplied-paths-report.md)。

## 各轮正式结果

以下覆盖所有已识别的后续实验与未完成计划，共 120 个计划／尝试记录，83 个有效评分格、5 个异常未评分尝试、32 个未开始／启动前阻塞计划；不混合不同方法版本求整体增益。commit 后的 † 表示基线＋未提交冻结 manifest，不是该 commit 原样运行。未开始行的 commit 只表示计划版本。

### G00 Graph 初版／两次中断

Graph 三模式、统一 ID 和显式来源关系；此处记录资源保护和服务流超时中断。

有效评分 0；已进入决策 2；本表列示 2。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`6d9e0d76`†|high|异常未评分|27|27/—|27/—|13851|未知|
|invoice/legacy|`6d9e0d76`†|high|异常未评分|7|6/—|15/—|≥2674|未知|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1/retry-costs.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1)。

只使用该文件的原请求／用量；旧版 packet delivery 统计已被后续诊断纠正，不沿用它判定包遗漏。

### G01 Graph r003-resume02

legacy/flat/linked × high/low；新增稳定实体、跨 View 引用及来源 links，仍为 3000 bytes，无图检索／路径规划。

有效评分 14；已进入决策 15；本表列示 18。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`6d9e0d76`†|high|0.0|40|40/—|40/—|18081|未知|
|invoice/legacy|`6d9e0d76`†|low|0.0|40|40/—|41/—|≥29013|未知|
|invoice/flat|`6d9e0d76`†|low|1.0|30|30/—|30/—|8140|未知|
|invoice/flat|`6d9e0d76`†|high|0.0|40|40/—|40/—|18754|未知|
|invoice/linked|`6d9e0d76`†|high|0.0|40|47/—|41/—|34595|未知|
|invoice/linked|`6d9e0d76`†|low|1.0|33|36/—|37/—|≥11980|未知|
|gimp/flat|`6d9e0d76`†|high|1.0|32|29/—|32/—|20931|未知|
|gimp/flat|`6d9e0d76`†|low|0.0|37|46/—|38/—|12053|未知|
|gimp/linked|`6d9e0d76`†|low|1.0|28|27/—|29/—|5581|未知|
|gimp/linked|`6d9e0d76`†|high|1.0|29|58/—|29/—|38805|未知|
|gimp/legacy|`6d9e0d76`†|low|0.0|25|24/—|26/—|6438|未知|
|gimp/legacy|`6d9e0d76`†|high|1.0|26|74/—|27/—|40544|未知|
|vlc/linked|`6d9e0d76`†|high|0.8510417343321308|37|49/—|37/—|27981|未知|
|vlc/linked|`6d9e0d76`†|low|0.906492567397591|19|18/—|20/—|4227|未知|
|vlc/legacy|`6d9e0d76`†|low|异常未评分|13|12/—|15/—|2934|未知|
|vlc/legacy|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|vlc/flat|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|vlc/flat|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1/revisions/r003-resume02/report-before-r005/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1)。

### G02 Graph r005

增强复核引用纠错和实际投递统计；第 2 格暴露观察 ID 模板字符串／整数冲突。

有效评分 1；已进入决策 2；本表列示 18。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`6d9e0d76`†|high|0.0|40|40/—|40/—|25728|未知|
|invoice/legacy|`6d9e0d76`†|low|异常未评分|34|36/—|36/—|15988|未知|
|invoice/flat|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|
|invoice/flat|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|invoice/linked|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|invoice/linked|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|
|gimp/flat|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|gimp/flat|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|
|gimp/linked|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|
|gimp/linked|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|gimp/legacy|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|
|gimp/legacy|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|vlc/linked|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|vlc/linked|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|
|vlc/legacy|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|
|vlc/legacy|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|vlc/flat|`6d9e0d76`†|high|未开始／启动前阻塞|—|—|—|—|—|
|vlc/flat|`6d9e0d76`†|low|未开始／启动前阻塞|—|—|—|—|—|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1/revisions/r005/report-before-r007/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1)。

### G03 Graph r007

OBS_SEQ 改为无引号正整数；保留严格校验、两次纠错及原预算。三任务 18 格重新冻结。

有效评分 18；已进入决策 18；本表列示 18。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`6d9e0d76`†|high|0.0|40|39/40|40/40|19416|16144|
|invoice/legacy|`6d9e0d76`†|low|1.0|40|48/48|40/40|11597|7534|
|invoice/flat|`6d9e0d76`†|low|1.0|36|35/36|37/37|30010|25848|
|invoice/flat|`6d9e0d76`†|high|1.0|39|38/39|40/40|17283|14213|
|invoice/linked|`6d9e0d76`†|high|0.0|40|40/40|41/41|16232|13073|
|invoice/linked|`6d9e0d76`†|low|0.0|40|40/40|41/41|15768|12390|
|gimp/flat|`6d9e0d76`†|high|1.0|19|38/39|19/19|16786|14470|
|gimp/flat|`6d9e0d76`†|low|1.0|20|19/20|21/21|3964|2127|
|gimp/linked|`6d9e0d76`†|low|0.0|40|40/40|40/40|8026|4867|
|gimp/linked|`6d9e0d76`†|high|1.0|34|35/36|34/34|29657|26952|
|gimp/legacy|`6d9e0d76`†|low|0.0|40|40/40|40/40|7319|5342|
|gimp/legacy|`6d9e0d76`†|high|1.0|19|18/19|20/20|13253|11488|
|vlc/linked|`6d9e0d76`†|high|1.0|16|16/17|16/16|34106|32732|
|vlc/linked|`6d9e0d76`†|low|1.0|14|13/14|15/15|2981|1629|
|vlc/legacy|`6d9e0d76`†|low|1.0|16|15/16|19/19|3431|1688|
|vlc/legacy|`6d9e0d76`†|high|1.0|10|11/12|10/10|5550|4640|
|vlc/flat|`6d9e0d76`†|high|1.0|32|38/40|33/33|35636|32719|
|vlc/flat|`6d9e0d76`†|low|1.0|15|14/15|16/16|3388|2061|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-graph-sx-high-low40-20261023-v1)。

### D02 送达优化 delivery-v2

压缩 ID、重复状态与来源字段，恢复 keyboard/lookup 和最近动作的预算优先级；仍存在单条配方前缀选择。

有效评分 12；已进入决策 12；本表列示 18。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`ec4827d7`|high|0.0|40|40/40|41/40|≥19589|≥16561|
|invoice/legacy|`ec4827d7`|low|1.0|34|33/34|36/36|15617|11260|
|gimp/legacy|`ec4827d7`|high|1.0|33|73/76|34/34|34379|29755|
|gimp/legacy|`ec4827d7`|low|0.0|38|37/38|39/39|16080|12687|
|vlc/legacy|`ec4827d7`|high|0.906492567397591|15|14/15|16/16|14146|12873|
|vlc/legacy|`ec4827d7`|low|1.0|20|19/20|21/21|4296|2402|
|invoice/flat|`ec4827d7`|high|0.0|40|39/41|42/40|≥24245|≥21183|
|invoice/flat|`ec4827d7`|low|1.0|40|39/40|41/41|25588|21513|
|gimp/flat|`ec4827d7`|high|1.0|40|42/44|40/40|36628|33670|
|gimp/flat|`ec4827d7`|low|1.0|24|23/24|26/25|≥4184|≥2327|
|vlc/flat|`ec4827d7`|high|1.0|22|40/41|22/22|15472|13250|
|vlc/flat|`ec4827d7`|low|0.906492567397591|15|14/15|16/16|2859|1404|
|invoice/mini-v7|`ae27018a`|high|未开始／启动前阻塞|—|—|—|—|—|
|invoice/mini-v7|`ae27018a`|low|未开始／启动前阻塞|—|—|—|—|—|
|gimp/mini-v7|`ae27018a`|high|未开始／启动前阻塞|—|—|—|—|—|
|gimp/mini-v7|`ae27018a`|low|未开始／启动前阻塞|—|—|—|—|—|
|vlc/mini-v7|`ae27018a`|high|未开始／启动前阻塞|—|—|—|—|—|
|vlc/mini-v7|`ae27018a`|low|未开始／启动前阻塞|—|—|—|—|—|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-legacy-flat-v7-high-low40-20261024-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-legacy-flat-v7-high-low40-20261024-v1)。

只完成 legacy/flat 的 12 格；v7 在外部派发层导入旧版本不存在的 verified_serial 时阻塞，没有获得 v7 正式成绩。用户随后终止剩余推进；live provider／定位预检按授权豁免，不写成通过。

### K01 能力指导 v1／四版本 low

能力与辅助目录冻结、确定性自动指导、剪贴板阶段、依赖与替代组；另测 v3 宿主＋新 keyboard 和原 v7。

有效评分 12；已进入决策 12；本表列示 12。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`b8c13ab5`|low|1.0|29|31/32|32/32|8981|4864|
|gimp/legacy|`b8c13ab5`|low|1.0|32|31/32|33/33|5609|3662|
|vlc/legacy|`b8c13ab5`|low|0.8876506679495421|16|15/16|18/18|3767|1976|
|invoice/flat|`b8c13ab5`|low|1.0|26|25/26|27/27|16259|13043|
|gimp/flat|`b8c13ab5`|low|0.0|40|40/40|40/40|10790|8744|
|vlc/flat|`b8c13ab5`|low|0.906492567397591|12|11/12|13/13|3030|1795|
|invoice/v3-keyboard|`5a66b7ec`|low|1.0|35|38/39|36/35|≥34134|≥29868|
|gimp/v3-keyboard|`5a66b7ec`|low|1.0|40|40/40|40/40|29539|26320|
|vlc/v3-keyboard|`5a66b7ec`|low|0.906492567397591|15|14/15|15/15|2624|1320|
|invoice/mini-v7|`ae27018a`|low|1.0|35|35/36|36/36|15330|10848|
|gimp/mini-v7|`ae27018a`|low|1.0|40|40/40|40/40|8354|5318|
|vlc/mini-v7|`ae27018a`|low|0.8795539066596272|13|12/13|14/14|2972|1644|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-low40-20261026-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-low40-20261026-v1)。

### K01-oldkeys-blocked 原 v3 keyboard／三任务计划

为 v7 和当前 legacy 安装原 v3 目录、选题及同 episode 记忆；资源不足，正式任务 0/6。

有效评分 0；已进入决策 0；本表列示 6。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/mini-v7|`729b8163`|low|未开始／启动前阻塞|—|—|—|—|—|
|gimp/mini-v7|`729b8163`|low|未开始／启动前阻塞|—|—|—|—|—|
|vlc/mini-v7|`729b8163`|low|未开始／启动前阻塞|—|—|—|—|—|
|invoice/legacy|`f361af5f`|low|未开始／启动前阻塞|—|—|—|—|—|
|gimp/legacy|`f361af5f`|low|未开始／启动前阻塞|—|—|—|—|—|
|vlc/legacy|`f361af5f`|low|未开始／启动前阻塞|—|—|—|—|—|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-v3keyboard-low40-20261026-v1/state.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-v3keyboard-low40-20261026-v1)。

冻结阶段真实空闲 RAM 1.837 GiB，低于 >2 GiB 准入要求。0/6 正式运行，全部无成绩。

### K02 能力指导 v2

区分动作／状态及 cut off、open menu、zoom in；补文件转移与阅读能力，短完整阶段卡，明确原 v3 整轮历史策略。

有效评分 6；已进入决策 6；本表列示 6。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`2dccd249`|low|1.0|28|27/28|30/29|≥10339|≥6978|
|gimp/legacy|`2dccd249`|low|1.0|29|27/29|32/31|≥6878|≥3880|
|vlc/legacy|`2dccd249`|low|0.8876506679495421|15|14/15|16/16|2868|1403|
|invoice/flat|`2dccd249`|low|1.0|27|26/27|28/28|12798|9214|
|gimp/flat|`2dccd249`|low|0.0|25|24/25|26/26|5293|3660|
|vlc/flat|`2dccd249`|low|1.0|16|15/16|18/17|≥3189|≥1606|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-v2-low40-20261026-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-v2-low40-20261026-v1)。

### K02-oldkeys 原 v3 keyboard／两任务

当前宿主仅恢复原 v3 按键目录、选题和记忆；保留宿主复核、公共提示和打包。原 v7 适配为另一个快照。

有效评分 4；已进入决策 5；本表列示 6。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy|`8933b1f9`|low|1.0|25|24/25|30/28|≥11899|≥8249|
|gimp/legacy|`8933b1f9`|low|0.0|40|40/40|42/40|≥5742|≥3749|
|invoice/flat|`8933b1f9`|low|1.0|28|27/28|33/30|≥11739|≥8246|
|gimp/flat|`8933b1f9`|low|1.0|40|40/40|42/40|≥4956|≥3023|
|invoice/mini-v7|`068d28fc`|low|异常未评分|2|0/0|2/1|1729|298|
|gimp/mini-v7|`068d28fc`|low|未开始／启动前阻塞|—|—|—|—|—|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-original-v3keys-2tasks-low40-20261026-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-original-v3keys-2tasks-low40-20261026-v1)。

第五格原 outcome 已覆盖较早 results.json 的“未开始”陈旧状态：第二次 predict 出现 Delta after finish，有 2 次 API 尝试／1 次完整返回，未派发 GUI、未评分。第六格未开始。[流协议异常证据](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-original-v3keys-2tasks-low40-20261026-v1/failure-analysis.md)。

### K03 能力指导 v3／full–compact

统一完整组、拖动／缩放／修饰键反馈、短阅读 proposal 与通用收尾；full/compact 同完整成本选事实，压缩后不回填。

有效评分 8；已进入决策 8；本表列示 8。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy/full|`216a14ed`|low|1.0|33|32/33|34/34|23312|19367|
|gimp/legacy/full|`216a14ed`|low|1.0|24|22/23|26/26|7655|5037|
|invoice/flat/full|`216a14ed`|low|1.0|36|37/38|39/37|≥11645|≥7320|
|gimp/flat/full|`216a14ed`|low|1.0|27|26/27|29/28|≥5206|≥2940|
|invoice/legacy/compact|`216a14ed`|low|1.0|37|39/40|40/38|≥17799|≥13325|
|gimp/legacy/compact|`216a14ed`|low|1.0|22|21/22|24/23|≥5440|≥3278|
|invoice/flat/compact|`216a14ed`|low|1.0|28|27/28|30/30|12765|8745|
|gimp/flat/compact|`216a14ed`|low|0.0|23|22/23|24/24|4216|2159|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-v3-review-2tasks-low40-20261026-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-v3-review-2tasks-low40-20261026-v1)。

### K04 能力指导 v4／always–stage

待确认效果、阅读保留和最小上下文；legacy/low 仅比较复核展示时机，均为 full 措辞、fixed_reference 预算。

有效评分 4；已进入决策 4；本表列示 4。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/legacy/always|`f277ea78`|low|0.0|40|43/43|40/40|13296|10531|
|gimp/legacy/always|`f277ea78`|low|0.0|21|19/21|22/22|5398|3388|
|invoice/legacy/stage|`f277ea78`|low|1.0|29|28/29|30/30|11729|7969|
|gimp/legacy/stage|`f277ea78`|low|1.0|28|27/28|29/29|5344|3608|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-v4-legacy-low40-20261027-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-v4-legacy-low40-20261027-v1)。

### A01 原 v3 工作流／clipboard 两格

均为原 v3 核心；只把 file_transfer.scope 的完整流程连接说明改为独立 clipboard 参考。运行源码不含同期新指导 v5。

有效评分 2；已进入决策 2；本表列示 2。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/workflow|`4dd4f2b3`|low|1.0|26|26/27|26/26|7010|4227|
|invoice/clipboard|`2a9dbd0d`|low|1.0|32|32/33|32/32|13632|10292|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-clipboard-flow-invoice-low40-20261027-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-clipboard-flow-invoice-low40-20261027-v1)。

clipboard 比 workflow 多 6 决策、6,622 输出，其中推理增量 6,065，占输出增量 91.59%。首次差异指引投递前已经出现阅读轨迹分歧，因此不能把全部差异归因于该一句 scope。[逐请求成本审计](/D:/cua_lty/OSWorld-K3-TaskViews/outputs/clipboard-cost-audit-20261027/report.md)。

### R01 历史 22 决策提交单次复现

完整历史 0a5b6f2 冻结源码，仅一次发票/low；作为 v3 参照复现，不是当前版本测评。

有效评分 1；已进入决策 1；本表列示 1。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|invoice/v3exact|`0a5b6f2a`|low|1.0|22|21/22|22/22|6973|4150|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-v3-exact-invoice-low40-20261027-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-v3-exact-invoice-low40-20261027-v1)。

### B01 GIMP LLM baseline low 补测

仅 baseline，关闭 TaskViews；使用与指导 v4 相同冻结代码，单次 low 对照。

有效评分 1；已进入决策 1；本表列示 1。

|任务／组／条件|commit|reasoning|分数／状态|决策|GUI／派发|API尝试／完整|输出 tokens|其中推理|
|---|---|---|---|---:|---|---|---:|---:|
|gimp/baseline|`f277ea78`|low|1.0|40|40/40|40/40|8061|5655|

来源：[原始结果／状态](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-gimp-llm-baseline-low40-20261027-v1/results.json)；[实验目录](/D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-gimp-llm-baseline-low40-20261027-v1)。

## 只做离线验证、尚无正式成绩的最新候选

|候选|commit／来源身份|通过测试|修改及验证边界|
|---|---|---:|---|
|指导 v5|当时未单独 commit；validation 源码哈希 `5d3aff731f73fff0…`|481|最小上下文、相对／精确缩放分卡、已输入／已确认阶段、混合循环、仅保留阶段复核。同期两格使用历史 v3，不测试此候选的线上表现。 [证明](/D:/cua_lty/OSWorld-K3-TaskViews/outputs/mini-guidance-v5-20261027/validation.json)|
|阅读 v6|当时未单独 commit；validation 源码哈希 `9f6d2927ca1e9f1e…`|502|来源多样的公开阅读报告、Current 指向 Lessons、Attempts 有界导航召回、同阅读目标下不同视图调整链；80 日志前缀×3 模式离线投影。 [证明](/D:/cua_lty/OSWorld-K3-TaskViews/outputs/mini-reading-v6-20261027/validation.json)|
|适用性指导 v7／当前|`3800520e4f1ae68c97fe5896076c24746145d825`|674|43 操作卡的动作契约；先核能力、对象、软件和阶段，再排序；lookup 同门禁，旧意图退役，Save As 分卡。 [证明](/D:/cua_lty/OSWorld-K3-TaskViews/validation/keyboard-eligibility-v7-20261028.json)|

v5/v6 的完整 SHA-256 清单收入配套 JSON；它们的文件内容不同于当前提交。当前提交通过 674 测试，不能把历史两格 26／32 决策或 v4 的 29 决策赋给当前代码。

当前目录核验覆盖 43 张完整卡、99 主题／253 绑定。旧目录中 47 绑定有明确动作映射，143 条 Linux 参考绑定仍待动作契约，63 条为其他平台参考；未建立契约的绑定不能仅凭 lookup 进入新操作卡。软件名称与目录启用也不证明当前焦点。[逐条核验表](/D:/cua_lty/OSWorld-K3-TaskViews/docs/taskviews-keyboard-eligibility-v7-audit.md)。

## 结果反映的改进与未解决问题

1. **Graph 结构没有证明下一动作收益。** r007 的 flat 高／低三任务均为 1，但发票 low 36 决策／30,010 输出，仍远高于原 v3 的 22／6,095；linked 发票高低均 0、GIMP low 也 0。flat/linked 共 345 帧无 keyboard/lookup 实投，共享引用累计为 0；表示开销挤掉指导是可核验实现问题。delivery-v2 恢复了部分信息，但不等于正确指引或模型采纳。

2. **找回旧 keyboard 仍未整体找回 v3 效率。** K02-oldkeys 的 legacy 发票 25 决策／≥11,899 输出、flat 28／≥11,739；还有 GIMP 失败和独立服务异常。新 keyboard、宿主提示、打包和复核共同影响轨迹，不能仅靠目录替换解释差异。

3. **复核展示效果不单调。** K03 的 compact 让 flat 发票从 36 降到 28 决策，却使 flat GIMP 从 1 变 0；legacy 发票由 33 增到 37。K04 stage 两格均 1、always 两格均 0，但 stage 正常执行中完整格式触发为 0，实际依靠终态纠错补全。后续 v5 才补实际保存／导出触发，不能用前轮分数证明该补丁有效。

4. **阅读与界面调整是主要剩余成本之一。** K04 发票 stage 比原 v3 多 7 决策，阅读／比较阶段多 9、后续少 2；阅读输出增量占总增量约 78.5%。直接报告再生成仅 986 输出，占该格 8.4%；扣除后仍高于 v3 约 76.3%。原 v3 没有当前强制 artifact_review，但也有原生校验与结果观察。不能把全部额外 tokens 归给复核。

5. **22 决策可以复现，但不是每次运行的保证。** R01 用完整 `0a5b6f2` 得到 22／6,973；A01 的 `4dd4f2b` 为 26／7,010。核心 CUA 文件比较未定位出导致多四步的确定性阅读代码差异；模型轨迹在指引差异投递前即可分叉，现有单次证据不支持一个模块的唯一因果归属。

6. **当前版本的正确说法是“完成工程修正，线上效果待测”。** 最新代码将能力、当前动作、对象、软件和阶段变成排序前门槛，保存短阅读报告和执行状态；离线验证不能替代新的冻结正式评测。

## 中断、修复、预检与成本

Graph campaign 累计 7/10 次候选修复，3 次失败也计数：登记／探针资源、复核反馈、整数模板及测试选择器。r003、r005、r007 是不同方法版本，表中独立保留，不挑高分拼成一组。两次资源／服务中断及预检成本也单列。

|Graph 成本类别|API请求|已知输入|已知输出|缺 usage 请求|
|---|---:|---:|---:|---:|
|r007 正式|522|4557504|274403|0|
|被替代 r003-resume02|482|4202537|280057|3|
|被替代 r005|76|721390|41716|0|
|两次中断|42|280989|16525|9|
|六批真实资格探针|130|486741|179518|1|

金额均未知，不填零；这些类别不混作当前代码的正式性能。后续 campaign 的用量逐格保存在 CSV/JSON，不因 token 较少就把零分当作效率提升。GIMP 的 alpha 辅助审查不替代官方评分。

## 可复核产物

- [完整结构化总账与来源哈希](/D:/cua_lty/OSWorld-K3-TaskViews/validation/taskviews-post-v7-experiments-20261029.json)
- [逐格 CSV（含输入、输出、推理、用量缺失、耗时、commit 和 manifest）](/D:/cua_lty/OSWorld-K3-TaskViews/validation/taskviews-post-v7-experiments-20261029.csv)
- [历史行动总账（截至 10 月 27 日的旧分析）](/D:/cua_lty/OSWorld-K3-TaskViews/outputs/project-action-history-20261027/report.md)
- [当前代码离线验证](/D:/cua_lty/OSWorld-K3-TaskViews/validation/keyboard-eligibility-v7-20261028.json)

本表以原 outcome 修正派生汇总的陈旧状态，不修改原实验文件。历史参考与后续正式实验分开，public content 和 usage 用于审计，没有读取私有推理正文、gold 或账户凭据。
