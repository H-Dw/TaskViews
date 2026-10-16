# Qwen Max medium/low：baseline 与 Mini 四组测评

用户于2026-10-16授权对同一发票与流水核对任务分别使用medium和low评测LLM baseline与TaskViews-mini，每组最多40轮。本批沿用随想`qwen3.8-max`、SX_QWEN_API_KEY、SX_URL_SB，四组均显式开启`enable_thinking=true`，只改变`reasoning_effort`。

冻结顺序为：medium/baseline → medium/taskviews → low/baseline → low/taskviews。每组使用新进程、新官方Docker guest、新actor/journal；上一组原官方评分和精确所有权容器清理完成后才接续。任何异常停止整个矩阵，不自动重跑、恢复旧episode或切换模型/接口。此次每格一次评测，无额外种子重复。

任务仍为OSWorld-Verified（OSWorld-1）`multi_apps/337d318b-aa07-4f4f-b763-89d9a2dd013f`。Mini保持`130d207`实现的`mini_keyboard_memory_v3`，baseline保持原生风格历史和共同native compiler、没有扩展视图/提示。旧high结果和轨迹保留，不能作为四组新actor的记忆输入。

共同预算保持relative每轴0–1000、1920×1080、history20/image1/fold1、text32000/reserve10000、消息上限12M字符、Mini四视图3000 UTF-8 bytes、请求输出16000/单步32000及两次语义修复。40轮按actor.predict计，含空动作；API、修复和GUI数量另计。baseline没有Mini四视图；两档之间仅推理字段不同。

VM3GiB、actor2GiB、启动器/巡检128MiB，零swap；Windows真实空闲RAM>2GiB，排除项目实测占用后的预算余量仅审计，C/D空闲45/12GiB。运行前与每轮/评分前检查。官方任务、输入PDF、compiler和评分器不改。

新增`SX` Max medium/low profile与`experiment=sx-max-medium40/sx-max-low40`，防止沿用Flash/low。矩阵入口为`scripts/verified_invoice_matrix.py`；不可变manifest保存两份计划哈希及共同源码、任务和预算，每份计划仍由原串行launcher执行。

启动前核验两档的实际请求字段、原运行器baseline/Mini×上限/显式终止/空动作共12例离线集成，以及每档真实文本/大图/native/tool-reply和Mini四位置诊断。定位误差单列，不以反复采样抹除；正式成绩只认原官方result。当前批次计划目录为`runs/verified-invoice-sx-max-medium-low40-20261016-v1`，实时状态见[运行状态](D:/cua_lty/osworld_verified_setup/运行状态.md)。

真实guest首次有效模型返回和动作回执后恢复原20分钟巡检；无实质变化保持安静，只通知完成/失败/需处理。四组完成后流式汇总完整usage、动作、终止声明与官方分数，核验源码、资源和清理并暂停巡检。单任务每格一次，结果用于本任务对照，不作为总体成功率或独立因果结论。
