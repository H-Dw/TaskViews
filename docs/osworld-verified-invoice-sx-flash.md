# 随想 Qwen 3.8 Flash：发票与流水核对

最终结果：2026-10-15 22:20审计确认v5两组各35轮完成，官方得分均0.0；没有内存保护中断，容器已清理，源码校验一致，巡检已暂停。分数、用量与内存证据见 [最终报告](osworld-verified-invoice-sx-flash-results-20261015.md)。下文保留接入和启动历史。

2026-10-15 21:55，按用户明确要求改为真实空闲内存>2GiB，并单独记录排除本项目占用后的预算余量。当前源码重新通过56项相关回归、六例离线集成、三项真实接口检查、镜像/依赖与实测计数预检；v5独立计划已启动，原模型/推理/35轮/两组机制保持一致。内存逻辑和证据见 [2GiB规则说明](osworld-verified-memory-policy-20261015.md)，实时进度见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。下方均为历史接入和启动记录。

**2026-10-15 21:41巡检更新：v4已于21:22在9轮后触发内存保护，Windows可用RAM=3.821GiB低于4GiB阈值。9次完整模型响应、7个GUI命令和2次WAIT，0已记录API错误或重试；未发出DONE/FAIL终止动作，未进入评分，official_score=null，Mini未启动。容器已清理，源码校验一致。巡检已通过应用工具暂停并获得确认，没有自动重跑。总usage=73702（prompt71842、completion1860，reasoning1293为completion子集）。证据：v4目录内monitor-audit-20261015T1341Z.json。需要先排查运行期间内存下降，再安排后续运行。下方21:16、21:20等为启动时记录。**

2026-10-15 21:16，按用户“重新运行评测”的明确指令，新建并启动 `runs/verified-invoice-sx-flash-low35-20261015-v4`。模型、URL选择、推理、两组配置、35轮上限、资源阈值和源码均与v3一致；启动前可用RAM约11.6GiB、零swap，镜像与运行依赖重新核验。v3及此前证据保留，新actor不读取旧轨迹或journal。新服务为 `osworld-verified-invoice-sx-flash-low35-20261015-v4.service`，检查脚本为 `D:/cua_lty/osworld_verified_setup/inspect-sx-low35-v4.py`。授权和证据复用校验记录在新目录的 `rerun-authorization.json`。21:19首次真实模型响应与动作回执均已完成；21:20:16有3个完整模型响应和3个有效决策。启用证据为新目录 `monitor-activation.json`，应用已确认20分钟巡检恢复ACTIVE。最新状态见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)，下文保留初次接入及历史运行记录。

本次按用户最新指令切换到随想接口、`qwen3.8-flash`。凭据只从 WSL 的 `SX_QWEN_API_KEY` 读取，URL 从 `SX_URL` 或 `SX_URL_SB` 读取。裸站点地址会规范为 `/v1`；已有 `/v1` 不重复添加。禁止在 URL 内嵌密钥或查询参数。

## 已验证的入口

2026-10-15 北京时间19:08起，两条环境配置分别测试：

| 环境变量 | 规范后的入口 | 实测 |
| --- | --- | --- |
| SX_URL | https://sui-xiang.com/v1 | 连接错误，未收到模型返回 |
| SX_URL_SB | https://www.sui-xiang.net/v1 | HTTP200，qwen3.8-flash正常回答，finish_reason=stop |

本次冻结 `SX_URL_SB`。运行中不自动跨入口切换。密钥没有写进源码、计划或报告；它也不进入评测guest。

基础请求携带 `reasoning_effort=low`，响应usage包含reasoning_tokens。随后通过正式传输层完成三项真实检查：文本、1920×1080合成截图定位及native computer_use、带原工具ID的回执后继续回答，均得到完整SSE和真实DONE。该检查未执行GUI操作，也未读取发票或参考答案。它验证接口可用性，不属于正式任务成绩。

初次完整接口证据：`D:/cua_lty/osworld_verified_setup/sx-native-probe-20261015-v2/`。大图检查证据为 `sx-native-probe-20261015-v4/`：4,387,662字节PNG、5,850,238字符图片URL，三项检查均取得完整响应。最终验证修订后的源码再次运行同一检查，使用新目录 `sx-native-probe-20261015-v5/`，该证明绑定v3计划。画面是固定随机纹理背景和红色矩形，不含任务文件。每版检查均保留原始SSE、JSON、阶段trace与usage。接口改动157项相关单元回归通过；基础设施修复后相关30项（含新增4项）通过，Ruff通过，重叠测试不累加。

## 实现与冻结配置

`ui_kobe/api/sx_native.py` 只定义随想模型、环境地址和请求字段，共用现有有界SSE传输。`ui_kobe/osworld/sx_native.py` 将它接到既有两组actor。使用 `--provider sx --sx-url-env SX_URL_SB` 准备计划；后续命令以计划内的provider和URL环境变量为准，并校验环境地址仍一致。

随想网关的SSE `created` 会随分片改变，响应ID和模型保持一致。专属 `SXSSE` 将首个时间戳作为规范响应的created，同时保存首尾时间与变化次数，原始流保持原字节。响应ID、模型、工具ID和参数、finish_reason、完整DONE仍严格校验；该兼容仅对随想生效，不放宽旧Pinggy/Tinker/OpenRouter解析。

| 设置 | 值 |
| --- | --- |
| 模型 | qwen3.8-flash |
| 推理请求 | reasoning_effort=low；不发送Pinggy专用thinking字段 |
| 采样与输出 | temperature=0、top_p=0.9；max_tokens=16000；每决策输出池32000 |
| 输入传输 | 图片/消息序列化上限12,000,000字符；文本上限32000字符、粗略文本token预算12000、保留区10000字符、当前图片1张不变 |
| 顺序 | UI-KOBE-like → TaskViews-mini，各最多35次predict |
| 环境 | WSL Ubuntu-24.04、原OSWorld-1官方Docker guest与任务 |
| 评分 | 原compare_pdfs；基础设施异常不伪造0分 |
| 隔离 | 每组独立进程、guest可写层、actor和journal |
| 资源 | guest2GiB、VM容器3GiB、actor2GiB、零swap；同一时刻一个guest |
| Mini | mini_fixed_v1；current、attempts、lessons；controls关闭，无额外模型角色 |

Mini与UI-KOBE-like的检索实现、截图、坐标、35轮定义均沿用原比较。Mini从真实journal按固定规则生成三个只读视图，再将有界包附给共同actor；没有另起模型生成视图。

| Mini视图 | 固定selector | 内容来源 |
| --- | --- | --- |
| current | current_frame | 当前观察帧及其状态 |
| attempts | recent_execution_edges | 最近执行记录，检索窗口4条 |
| lessons | recorded_errors_and_model_proposals | 已记录错误与明确标为模型建议的记录 |

本次通过`UI_KOBE_TASKVIEWS_PROFILE=mini_fixed_v1`固定选择上述三类，通过`UI_KOBE_MINI_CONTROLS_VIEW=disabled`关闭controls扩展。视图包总计最多3000字节，attempts先分配1200字节、lessons先分配1000字节，余量共享；保留完整记录及源事件引用，装不下时记录省略数量，不截断字段。UI-KOBE-like使用最近8条执行边检索。设置冻结在计划的`arm_profiles`与源码中，运行中不动态改选视图；新视图或配额需要单独声明profile并重新验证。详细机制见 [原搭建说明](osworld-verified-invoice-low35-setup.md)。

## 运行与巡检

首次基础设施尝试：`runs/verified-invoice-sx-flash-low35-20261015-v1`，完整保留。
第二次基础设施尝试：`runs/verified-invoice-sx-flash-low35-20261015-v2`，完整保留。
最终计划：`runs/verified-invoice-sx-flash-low35-20261015-v3`。
对应离线证据：`outputs/verified-invoice-sx-flash-validation-20261015-v4`。离线v3发现模拟首帧挂在reset返回值上，但原runner从`_get_obs`获取首帧，因此大图断言正确失败；已修正fixture入口并重新执行全部六例，保留旧记录。
日志：新计划目录内的 `console.log`、每组 `telemetry`、`outcome.json` 和 `state.json`。

冻结计划前，两组各运行35轮上限、7轮显式终止、35轮空动作三种离线集成检查，六例全部通过；镜像、Docker依赖及运行时导入预检通过。HTTP、GUI和评分为明确fixture，禁止真实联网/VM构造；哨兵0.125不是成绩。线上三项接口检查证明与冻结源码绑定，缺少完整证明时禁止启动VM。

用户已授权正式运行。当前启动入口为 `D:/cua_lty/osworld_verified_setup/launch-approved-sx-flash-low35-v3.sh`，由WSL user systemd service在交互shell中读取已有环境凭据；不把密钥放入命令行或项目文件。第一组官方评分和清理均完成后才自动启动Mini，任何组异常则停止，不自动重放。

北京时间19:19启动的v1服务在19:21首次模型请求前触发资源保护，已停止并清理容器。该次为0个模型请求、0个GUI动作、0个决策，`official_score=null`；Mini没有启动。磁盘检查余量C约68GiB、D约46GiB；资源错误当时未保存具体RAM读数，因此不能报告精确失败值。

后续定向释放本实验不可变qcow2的读取缓存，Linux Cached从约4.30GiB降至1.47GiB，Windows可用RAM随后回升至约9GiB。这支持缓存压力是影响因素，但不能证明它是唯一原因。镜像SHA256校验现在对已读的1MiB范围发出`POSIX_FADV_DONTNEED`提示，不修改文件、校验内容或资源阈值，也不清除全系统缓存；资源保护异常附带实际RAM和磁盘数值。新实现相关29项测试通过（包含新增3项），Ruff通过；再次执行六例离线验证和三项在线检查后才冻结v2。v1不恢复、不覆盖，不作为任务失败成绩。

v2于北京时间19:30启动并通过首次决策前资源检查，取得真实1920×1080任务截图，但本地上下文准入在发送API前拒绝：原PNG 1,692,804字节、无损压缩后1,537,115字节、图片URL 2,049,510字符，超过原2,000,000字符消息上限。1次predict尝试、0模型请求、0GUI动作、无评分，容器已清理。没有查看任务截图内容或人工提供解题信息。

v3仅将随想比较两组共同的消息序列化上限提高到12,000,000字符，足以容纳既有8MiB PNG传输上限及文本。文本、历史、图片张数、视图包、推理、输出token与35轮上限不变；保持无损像素、1920×1080及原坐标体系。两组terminate离线场景增加大于旧2M上限的合成首帧，并验证实际请求大小；线上检查也使用大图，不再只验证纯色小图。所有更改在新计划冻结前完成，旧计划不覆盖或续跑。

v3服务为 `osworld-verified-invoice-sx-flash-low35-20261015-v3.service`，有界状态读取工具为 `D:/cua_lty/osworld_verified_setup/inspect-sx-low35-v3.py`。最新启动与资源检查状态见下方运行状态链接。

2026-10-15 19:46:54，UI-KOBE-like在真实官方Docker环境中取得首个完整`qwen3.8-flash`响应（finish_reason=tool_calls，1个工具调用），19:46:58取得首个GUI动作回执。19:47:23已有2个完整模型响应、2个有效决策，无已记录错误，源码与冻结计划一致，尚无官方分数。证明保存在 `runs/verified-invoice-sx-flash-low35-20261015-v3/monitor-activation.json`。

20分钟巡检复用 `osworld-20`，19:47满足条件后启用。20:08首次巡检发现运行已于19:51触发内存保护：Windows可用RAM=3.736GiB，低于4GiB阈值；C/D空间合格。UI-KOBE-like完成14轮、14次完整模型响应（0已记录API错误/重试）、13个GUI命令和1次WAIT。未进入评分，official_score=null；Mini未启动。容器已清理，项目与上游源码校验一致。巡检暂停请求尚待应用确认；没有重跑或续跑。

总usage为prompt119227、completion3588（含reasoning2568）、total122815。证据位于 `runs/verified-invoice-sx-flash-low35-20261015-v3/monitor-audit-20261015T1208Z.json`。20:28检查状态无变化；20:30在应用接口仍无响应时，备份并将本地巡检配置设为PAUSED，其余设置保留。调度层尚未返回确认。需要解决持续内存余量后再确认后续运行安排。实时状态见 [运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。
