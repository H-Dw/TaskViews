# Mini 独立 controls view

本次用户明确要求检索前沿 CUA 的按键信息获取策略、实现独立 view 并用新代码继续测试。它授权在当前 M0 主干上显式加入只读 `mini_controls_v1` 扩展，取代旧巡检提示里“不得加入新 view”的限制。它没有授权叠入完整版角色链或 M1 严格焦点 gate。

## 检索结果与取舍

| 实现 | 获取控件/操作信息的方法 | 本次采用的部分 |
| --- | --- | --- |
| [Microsoft UFO 混合检测](https://microsoft.github.io/UFO/ufo2/core_features/control_detection/hybrid_detection/) | UIA 提供标准控件；OmniParser 补充视觉控件，合并去重 | 控件信息独立于动作，保留来源和当前帧边界；后续可以接入可访问性源 |
| [OmniParser](https://github.com/microsoft/OmniParser) | 将截图解析成结构化控件及可交互性信息 | 同一次现有 actor 调用可输出少量可见控件侧记录，作为视觉 proposal；本次不安装额外模型 |
| [UFO Knowledge Substrate](https://microsoft.github.io/UFO/ufo2/core_features/knowledge_substrate/overview/) | 检索帮助文档、网上资料及执行经验，提供给执行者 | 使用有来源的小型快捷键目录，避免每一步依靠模型回忆或猜终端命令 |
| [Claude computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) | screenshot → action → result/screenshot 循环；对困难控件可提示键盘操作并检查结果 | 将目标焦点、下一帧可见效果和按键知识一起提供给 actor，不把 returned 当成功 |

UIA 是 Windows 接口，当前正式环境是 Linux/GNOME。不能把 UFO 的 UIA 能力写成当前环境已经可用。本次没有采集 accessibility tree、DOM 或部署 OmniParser；当前控件标签仍由原 actor 根据它实际收到的当前截图读取，可能判断错误。

## 目录与运行契约

`kobe_views/controls_view.py` 声明 GNOME 官方文档来源、按键目录和同调用控件侧记录格式。来源是 [窗口最大化](https://help.gnome.org/gnome-help/shell-windows-maximize.html)、[窗口移动/尺寸](https://help.gnome.org/gnome-help/shell-windows-states.html)、[键盘导航](https://help.gnome.org/gnome-help/keyboard-nav.html) 与 [快捷键总览](https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html)。目录覆盖窗口切换、最大化、移动、尺寸调整、菜单、焦点遍历、控件激活与弹窗退出。

这些是 GNOME 默认知识，不是已实测的 guest 绑定或目标焦点。Super 在本地 PyAutoGUI X11 接口中的声明键名是 `win`；目录使用该键名，不在运行时转换模型参数。没有导入图像、文件路径、数学答案或旧成功坐标。

`--controls-view` 是恢复器的显式开关。修复 plan 与 manifest 同时冻结完整扩展 policy，runner 比对后设置环境开关。关闭时仍是原 `current/attempts/lessons` 三-view 路径；开启后同一可选包内增加 `controls`，总上限仍为 3000 UTF-8 bytes。`controls` 和 `current` 优先整体准入，历史投影利用剩余空间；整个必需外壳不适合当前可选额度时显式整包省略，不挤掉原任务、当前图或 native history。

actor 收到指引后，应从当前图识别目标和 enabled/focus 状态，适用时使用匹配的目录操作。焦点不确定时先建立焦点并读取下一帧，再做依赖输入或提交。窗口变化、菜单出现、键盘操作 returned 均不能证明目标操作成功；后图仍是检查依据。

可选 `<controls>...</controls>` 侧记录最多四个控件，只有 label/role/shortcut/enabled/focused、所选 binding 和期望变化。原 native response/tool IDs/参数/命令完整保留。格式错误或超限只使该可选记录不可用，不触发额外模型请求、修复或自动改写 native 动作。历史侧记录带原 decision/observation/完整 SHA，下一帧明确要求重新观察，不把它升为当前 focus。长记录整段省略，原件仍在 journal。

`mini_controls_candidate` 记录当前帧的原侧记录、与目录逐值匹配的原 native key 参数和该次 view 是否送达。模型声称 selected_binding、真实匹配按键、后图效果是三个不同指标；匹配不证明因果或任务产物成功。

## 检查点兼容与边界

扩展不增加持久语义事实，不改变原 native actor/累计 steps/journal；控件历史从不可变原 decision 重建。用户授权后可从原 Mini 安全 CP 显式开启此只读扩展，不迁移到 full/UI-KOBE-like profile，也不重放已完成命令。新 CP 冻结 controls policy；其后关闭扩展或 policy 不同会严格拒绝恢复。

本扩展没有独立 planner/perception/verifier，正常额外角色请求仍为 0。它不是完整 M1：尚无当前焦点的独立测量或严格依赖 gate，actor 仍可能错误识别控件、忽略指引或选择无效操作。需要真实新请求、原命令、后图和官方产物验证收益。

后续可按原 roadmap 加入同一观察中的可信 accessibility 信息、目标级事实和依赖检查。每一步都应先验证来源、帧一致性、enabled/focus 语义和预算；不能用全局快捷键目录冒充已获取全部应用按钮。

首次 controls 扩展的有界离线验证为 148 项通过、Ruff 0，包含控件来源/帧绑定、可选侧记录失败、原 native 修复池、默认模式隔离、旧 CP 只读扩展、500 步历史及原恢复/准备路径。OSWorld 官方源码保持原样。正式恢复后的指引送达、按键采用与画面变化需另存真实证据；这些离线通过数不代表任务成绩。

## 持续重复动作的原记录反馈

正式第 134–145 步的记录显示，目录真实送达后 actor 仍反复发出相同点击与 prose；部分连续操作的前后原图 SHA 完全相同。其短包中的 attempts/lessons 均整条省略，完整 native history 仍保留。仅发送静态按键知识没有保证策略采用，不能把点击停滞归因为已经证明的比例或图像传输错误。

controls 开启时，current 额外提供一个有界 `recent_repetition` 原记录比较：最近最多四条连续、已回执且 native 参数和原 command 完全相等的交互操作，至少两条才形成提示。包含原 event.seq、最新不可变 event ID/完整 SHA、原 command、重复数与前后原图 SHA 相等次数。不同工具调用 ID仍保留在原件；更换参数、被动 WAIT/screenshot 或不完整转换不会被当成连续交互。

该字段的 grade 为 `literal_journal_comparison`，effect 继续 unknown。图像不同也不证明操作成功，图像相同也不证明隐藏状态没变化、目标焦点或任务失败；它只让 actor 能把近期原记录与当前图和现有按键指引结合。没有新增依赖 gate、自动选择按键、动作黑名单、角色模型请求或语义事实。

该短反馈复用原 3000-byte 包，并保持来源与整条省略：无法兼容时明确 `recent_repetition_omitted`，原动作、原图、完整历史和目录不被偷偷截断。M0关闭 controls 时不增加该字段或查询。现有 controls catalog/policy 没有改变，检查点送达游标和原 native 状态保持原恢复契约。
