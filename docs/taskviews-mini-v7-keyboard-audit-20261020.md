# TaskViews-mini v7 键盘知识来源与通用控制补充

核对日期：2026-10-20（Asia/Shanghai）。本文区分历史实验实际使用的内容与本次新增内容。范围为本地可核验的 2026-10-19 VLC / TaskViews-mini v7 正式 episode；没有将其他名为 v7 的实验混入。

后续变更：同日按追加需求实现了[任务软件名自动选择目录](taskviews-keyboard-auto-selection-20261020.md)。本文对 v7 历史记录及 general 扩充时点的描述保留；当前新计划的默认目录选择方式以该说明和 [keyboard README](../tools/keyboard/README.md) 为准。

## 1. 实验的 keyboard 来自哪个文件

**运行时的外部按键知识源是 [`kobe_views/key_tools/catalog.json`](../kobe_views/key_tools/catalog.json)，具体为 `toolsets.general.topics`。** [`tools/keyboard/general.md`](../tools/keyboard/general.md) 是该数据的可读文档，由 [`scripts/render_keyboard_tools.py`](../scripts/render_keyboard_tools.py) 生成。只修改 Markdown 不会改变运行时检索结果，而且会被再次生成覆盖。

加载链路如下：

1. [`kobe_views/keyboard_view.py`](../kobe_views/keyboard_view.py) 在模块加载时读取 JSON，取出来源链接、全部目录和默认 `general` 主题。
2. [`mini_taskviews_native.py`](../ui_kobe/osworld/mini_taskviews_native.py) 读取本轮启用的目录配置。
3. [`mini_taskviews_context.py`](../ui_kobe/osworld/mini_taskviews_context.py) 根据最新一轮模型正文选择一个主题。可以使用精确的 `<key_lookup>topic</key_lookup>`；少量旧通用主题也能由预设意图规则匹配。
4. `record()` 形成包含 `scope`、`source`、`recipes`、`check`、`memory` 的 keyboard 记录；`memory` 只能引用本 episode 中匹配组合键的原始事件。
5. [`fixed_views.py`](../kobe_views/fixed_views.py) 将其与 current、attempts、lessons 一起装入最多 3000 UTF-8 bytes 的四视图。预算不足时会省略记忆或整个参考记录。

这是事先整理的结构化知识库和按意图检索机制；运行时没有实时访问 GNOME/Microsoft 网站，也没有整本注入 `general.md`。`source` 输出主题的第一条来源链接，完整来源列表保存在 JSON 和生成文档中。控件类型、当前软件、焦点及操作结果仍需模型依据当前画面判断，主题匹配本身不构成视觉识别。

历史实验的[冻结计划](../runs/verified-vlc-mini-v7-sx-max-high40-20261019-v1/plan.json)和[源码冻结](../runs/verified-vlc-mini-v7-sx-max-high40-20261019-v1/source-freeze.json)给出的身份如下：

| 项目 | 实际冻结值 |
| --- | --- |
| 实验目录 | `verified-vlc-mini-v7-sx-max-high40-20261019-v1` |
| 代码提交 | `ae27018a99f67329c1d3547f66017e55bf3cd03b` |
| Mini 实现修订 | `mini_report_recovery_v7` |
| 运行平台 | Linux / X11 |
| 默认及实际启用目录 | `["general"]` |
| keyboard 目录协议字段 | `mini_keyboard_tools_v3` |
| general 内容 | 11 个主题，23 条配方 |
| 原目录文件 SHA256 | `00f7c7307205e282230b7a3ec31f4b4704a64dac512d2d984158cb6a40ba313e` |
| 原规范化目录 SHA256 | `bccce6d82bf85b0b8f48e3678776f271fe17043e48b03f58b3b2c1ce26c457dd` |

两个 SHA 分别针对磁盘原始字节和代码规范化序列化后的数据，不能直接互换。备份前本地目录的原始字节 SHA 与冻结值完全相同。文档中历史称呼“按键实现 v5”、Mini 整体“v7”、目录协议字段“v3”是不同层次的标识；此处以代码与冻结计划字段为准。

## 2. 原版包含哪些按键指引

下表完整列出原版 23 条配方。同一组合键可能在不同主题重复出现，因此配方数不等于不同组合键数。运行时 Enter 使用 `return`，Esc 使用 `escape`，PageUp/PageDown 使用 `pageup`/`pagedown`。

| 原主题 | 按键 | 指引用途与限制 |
| --- | --- | --- |
| `editing` | Ctrl+A；Enter；Esc | 当前文本框全选；确认字段/对话框；关闭弹层。Enter 在多行文本中可能换行，也可能触发默认提交按钮。 |
| `clipboard` | Ctrl+C；Ctrl+X；Ctrl+V | 复制、剪切、粘贴当前文本或支持该操作的选中项；粘贴可能替换已有选区。 |
| `undo` | Ctrl+Z | 支持撤销的 GUI 编辑操作。没有把终端的 Ctrl+Z 当作撤销。 |
| `focus_navigation` | Tab；Shift+Tab | 在可聚焦控件之间前进/后退；控件内部可能自行处理 Tab。 |
| `control_activation` | Enter；Space | 激活按钮、切换复选框等；Space 在文本框中输入空格，在播放器中可能控制播放。 |
| `popup_dismiss` | Esc | 退出菜单、弹层或可取消对话框。 |
| `context_menu` | Shift+F10 | 打开当前焦点项的上下文菜单。 |
| `page_navigation` | PageDown；PageUp | 在文本/文档区域按视口翻动；不能保证正好换一个 PDF 页面，编辑区也可能移动光标。 |
| `cursor_navigation` | Left；Right；Home；End | 单行文本字段中移动字符或到达字段/行边界。 |
| `text_selection` | Shift+Right；Shift+End；Shift+Home | 扩展字符选区，或选择到行尾/行首。旧版没有 Shift+Left 配方。 |
| `window_switch` | Alt+Tab | 切换窗口/应用；GNOME 可能按应用分组。旧版没有反向切换配方。 |

原版来源包括 [GNOME 键盘导航](https://help.gnome.org/gnome-help/keyboard-nav.html)、[GNOME 常用快捷键](https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html)、[GTK Entry 光标绑定](https://docs.gtk.org/gtk3/signal.Entry.move-cursor.html)、[GTK TextView 光标绑定](https://docs.gtk.org/gtk3/signal.TextView.move-cursor.html)、[Windows 键盘快捷键](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)、[Firefox 快捷键](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)以及 GNOME 默认窗口 keymap。它们是操作知识的证据来源，不是已在实验镜像中逐项成功执行的证明。

## 3. 对应哪些软件，通用还是软件专属

**v7 实际启用的是有控件前提的通用指引。** 它没有一张“这些软件全部支持全部按键”的白名单。判断单位是当前控件及操作模式，而非应用名称。

| 软件/场景 | general 可迁移的部分 | 不能由 general 推导的部分 |
| --- | --- | --- |
| Chrome、Firefox、网页应用 | 标准输入框、按钮、表单、菜单等 | 浏览器地址栏、标签页管理、站点自定义业务快捷键 |
| LibreOffice Writer/Calc/Impress、文本编辑器 | 输入框、编辑态文本、按钮、对话框等 | 表格浏览态、幻灯片放映、编辑器命令面板、Vim keymap |
| 文件管理器 | 焦点遍历、支持剪贴板的选中项、菜单 | F2 重命名、显示隐藏文件等专门文件操作 |
| VLC、GIMP、Audacity 等 | 设置对话框、文件名字段及其他标准控件 | 播放/暂停、音量、截图、画布缩放、时间轴剪辑 |
| 终端、3D/CAD、游戏及自定义画布 | 只有明确符合标准约定的外围控件 | 命令输入、工具切换和画布中的按键含义 |

整个旧知识库其实已有 **51 份分类目录：general 1 份、类型 13 份、平台 3 份、软件 34 份，共 190 条配方**。它们均存放在同一个 catalog JSON 中，但只有启用目录的主题可以被检索。文件被读取不等于其中所有配方都进入模型输入。

现有专门软件目录覆盖：

- 浏览器：Chrome、Firefox、Edge；文档/办公：LibreOffice Writer、Calc、Impress，Microsoft Word、Excel、PowerPoint。
- 文件/阅读：GNOME Files、Windows File Explorer、Evince；开发/科学/CAD：VS Code、PyCharm、MATLAB、AutoCAD。
- 图形/影音：GIMP、VLC、Audacity、Inkscape、Photoshop、After Effects、Premiere、Blender。
- 邮件/网站：Thunderbird、Outlook classic、GitLab、GitHub；macOS 参考：Finder、Safari、Notes、Mail、Preview、TextEdit。

完整对应关系见[分类索引](../tools/keyboard/index.md)。类型和软件目录需显式选择；Windows/macOS 等不兼容资料不能启用到当前 Linux actor。特别是 [`app.vlc`](../tools/keyboard/software/media/vlc.md) 虽然存在，**此次 VLC 实验并未启用它**。`verified_invoice.py` 所用比较入口固定 general，并清除继承的专用目录配置。

## 4. 这次 v7 实际给模型发送了什么

读取[原始 9 次请求](../runs/verified-vlc-mini-v7-sx-max-high40-20261019-v1/taskviews/telemetry/events-7168.jsonl)中的 `api_request.payload.messages`，逐次解析实际四视图包，得到：

| 决策轮次 | 实际 keyboard 内容 |
| --- | --- |
| 1 | 没有配方记录；current 中提供了 11 个主题的查询说明。 |
| 2–5 | keyboard 无配方；查询说明也未装入预算。 |
| 6 | 发送 `clipboard`：Ctrl+C、Ctrl+X、Ctrl+V。来源是 GNOME 常用快捷键，选择理由为最新模型意图匹配。 |
| 7–9 | keyboard 无配方；查询说明未装入预算。 |

第 6 轮 keyboard 的 `memory=[]`、`memory_omitted=2`：两条候选按键记忆未装入最终请求，不能描述为模型收到了这两条记忆。

原始响应中共 4 次 `action:key`：第 5 轮 Ctrl+X、Ctrl+V；第 6 轮 F2、Enter。第 5 轮的剪切/粘贴发生在第 6 轮收到剪贴板参考之前；F2 又不属于启用的 general。因此这些动作不能全部归因于外部键盘库，也不能据此认定 VLC 专用知识库起了作用。TaskViews 提供参考，模型仍可根据原生能力生成参考之外的合法动作。

## 5. 调研方法与场景依据

本次按用户指定的 multi-search-engine 技能，用英文检索词查询国际引擎，单次间隔 1.5 秒；检索词为 `GNOME keyboard navigation text boxes menus sliders official`。搜索阶段只使用公开通用控件问题，没有查询本次任务的参考答案。

| 引擎 | 实际结果 |
| --- | --- |
| Google | HTTP 页面获取成功，但本次结果解析没有得到可用的目标文档链接；不计作有效证据。 |
| DuckDuckGo | 得到 GNOME keyboard navigation、HIG controls、keyboard guidelines 等官方入口。 |
| Brave | HTTP 429；尝试首页获取会话后，间隔 2 秒重试一次，仍为 429，停止使用。 |

Cookie 仅在内存中管理，结束时清空，没有读取浏览器 Cookie 或写入配置文件。工具内直接打开搜索页不可用后，使用本地 HTTP 获取执行上述引擎检索；随后通过联网检索/打开官方文档核对内容。证据结论采用官方资料，不采用搜索摘要或社区经验作为绑定依据。

选取通用操作的场景依据：

| 一手场景来源 | 观察到的操作类别 | 本次补充方向 |
| --- | --- | --- |
| [OSWorld 官方仓库](https://github.com/xlang-ai/OSWorld)、[原始论文](https://arxiv.org/abs/2404.07972) | 桌面/网页、文件操作、跨应用任务 | 内容查找、文件对话框、窗口与文本操作 |
| [MiniWoB++ 环境清单](https://miniwob.farama.org/environments/list/) | 文本输入、选中、复制粘贴、菜单、列表、选项、标签、折叠控件等 | 按控件类型补全键盘操作 |
| [ScreenSpot-Pro 论文](https://arxiv.org/abs/2504.07981) | 专业软件中的 GUI 元素定位 | 强调先识别控件和模式，再选择按键；定位标注不能证明键盘绑定 |
| [W3C APG 键盘交互](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/) | 控件间焦点、复合控件内部移动、焦点与选中状态区分 | 为每个控件主题写明前提和效果检查 |

这些场景来源用于判断“值得覆盖什么”；具体组合键另用 GNOME/GTK、Microsoft、LibreOffice、GIMP、Firefox 和 W3C 控件文档核对。网页 APG 是交互设计约定，ARIA 属性不会自动赋予网页快捷键，实现缺失时必须回到当前可操作界面。

## 6. 已加入 general 的内容

本次保留原 11 个主题，补全其中 2 条配方，新增 23 个主题、61 条配方。合计 **34 个主题、86 条配方，比原版增加 63 条**。整个目录变为 253 条，其他类型、平台和软件目录内容保持原样。

| 新主题/扩充项 | 按键概览 | 使用前提/检查重点 |
| --- | --- | --- |
| `text_selection`、`window_switch` 扩充 | Shift+Left；Alt+Shift+Tab | 补齐反向选字与反向窗口切换 |
| `word_navigation`、`word_selection` | Ctrl+Left/Right；Ctrl+Shift+Left/Right | 普通文本编辑态；词边界受语言、标点影响 |
| `text_delete`、`word_delete` | Backspace/Delete；Ctrl+Backspace/Delete | 删除文本；不能在文件列表、画布直接套用 |
| `multiline_navigation`、`multiline_selection` | Up/Down；Ctrl+Home/End；相应 Shift 选区 | 多行文本光标/选区，区分换行、折行和视口 |
| `find_text` | Ctrl+F | 确认打开的是目标内容范围的查找 |
| `document_file` | Ctrl+O/S/Shift+S/P | 当前内容窗口菜单确实支持相应打开/保存/另存/打印命令 |
| `menu_open`、`menu_navigation`、`submenu_navigation` | F10；Up/Down/Enter/Esc；Right/Left | 区分桌面菜单、开放菜单和子菜单；确认命令文字 |
| `list_navigation`、`list_selection`、`list_focus` | Up/Down/Home/End；Shift+Up/Down、Ctrl+Space；Ctrl+Up/Down | 区分焦点、选中和多选模式；Ctrl+Space 可能被输入法占用 |
| `combobox_open`、`combobox_selection` | Alt+Down；Up/Down/Enter/Esc | Alt+Down 在部分网页为可选支持；检查最终字段值 |
| `radio_group` | Left/Right/Space | 标准单选组；方向键可能立即改变选择；排除工具栏特殊模式 |
| `slider_adjust` | Left/Right/Home/End | 已聚焦、方向正常的水平滑块；检查实际值和单位 |
| `spinbutton_adjust` | Up/Down | 数值步进框；区分纯文本框，检查步长和边界 |
| `tablist_navigation` | Left/Right/Enter/Space | 焦点在横向标签本身；区分自动激活与手动激活 |
| `tree_navigation` | Up/Down/Right/Left | 采用裸箭头展开约定的树；GNOME 文档还列有 Shift+箭头变体 |
| `window_close`、`window_menu` | Alt+F4；Alt+Space | 已聚焦应用窗口；关闭后处理保存提示，窗口菜单按可见标签选择 |

上述快捷键与细分限制的原始资料已逐主题附在 [general.md](../tools/keyboard/general.md)。例如，[GNOME HIG](https://developer.gnome.org/hig/reference/keyboard.html) 提供常见文件/内容命令，[GTK 删除绑定](https://docs.gtk.org/gtk3/signal.TextView.delete-from-cursor.html)提供文本删除依据；[W3C 列表](https://www.w3.org/WAI/ARIA/apg/patterns/listbox/)、[下拉框](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/)、[单选组](https://www.w3.org/WAI/ARIA/apg/patterns/radio/)、[滑块](https://www.w3.org/WAI/ARIA/apg/patterns/slider/)、[步进框](https://www.w3.org/WAI/ARIA/apg/patterns/spinbutton/)、[标签](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/)、[树](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/)分别约束不同控件的按键含义。

没有把下列动作写成无条件通用配方：

| 操作 | 原因与后续补充位置 |
| --- | --- |
| 重做、纯文本粘贴 | Ctrl+Y/Ctrl+Shift+Z，以及 Ctrl+Shift+V 的含义随软件变化；应核对菜单后进入类型或软件目录。 |
| 浏览器地址栏、标签、刷新；文件重命名 | 已有部分类型/软件目录，应该按范围启用；例如 Ctrl+L 在其他软件可能变成段落对齐。 |
| 媒体播放、音量、缩放、导出 | 裸 Space、箭头、Ctrl+加减和保存/导出的含义依工作区而变。 |
| 最大化、最小化、工作区切换 | 依操作系统/窗口管理器配置，应在 platform 中维护。 |
| 拖放、悬停、绘图、框选、精确坐标定位 | 缺少跨软件等价的单组合键；继续使用原生指针动作，不能为追求键盘覆盖虚构替代。 |
| 日期选择器、复杂网格、可编辑树、富文本格式命令 | 可继续按控件模式扩充，但需要分清导航/编辑状态、可选实现和软件冲突。 |

## 7. 备份、运行边界和验证

- 原版 Markdown：[general.2026-10-20.pre-expansion.md](../tools/keyboard/backups/general.2026-10-20.pre-expansion.md)，SHA256 为 `56efe9c413001f7644d1a23f0d8cd110d4ff9657c6a4f4f80a1c31f22660dea4`。
- 原版运行时知识库：[catalog.2026-10-20.pre-expansion.json](../tools/keyboard/backups/catalog.2026-10-20.pre-expansion.json)，SHA256 与实验冻结目录一致，见第 1 节。
- 机器可读的核对记录：[general-expansion-20261020.json](../tools/keyboard/backups/general-expansion-20261020.json)。

新增内容经 catalog 生成到 general.md；生成器支持目录自己的核对日期，因此没有把其他软件旧资料标成 2026-10-20 全部重新核验。catalog 协议字段保留 `mini_keyboard_tools_v3`，内容变化由目录 SHA 区分。既有 `<key_lookup>`、动作格式、主题路由、专用目录准入和四视图预算没有变更。

新增主题可精确查询，例如 `<key_lookup>word_delete</key_lookup>`。没有为新主题加入模糊自动识别规则。运行时在模块初始化时读目录，已有进程不会热更新；新实验需要按新内容生成冻结计划。历史 v7 的冻结文件、轨迹和成绩保持原样，旧 checkpoint 不能当作新目录的合法续跑入口。

验证结果：

- 60 项既有 keyboard 与 Mini 回归通过，覆盖配方 token、真实官方编译器离线编译、生成文档一致性、目录隔离、历史引用与原有预算行为。
- 新增 34 项逐主题 actor 集成验证全部通过：第一轮能够发现各主题，精确查询后第二轮实际收到对应 keyboard 记录，四视图均不超过 3000 bytes，每例只有 2 次离线原 actor 请求。
- 文档生成 `--check`、修改文件的 Ruff 与 `git diff --check` 通过；其他 50 个 toolset 的数据未改变。

以上是 **94 项离线工程测试**，使用模拟模型传输，没有调用线上模型或启动新的 OSWorld episode。逐主题测试覆盖有一条普通前序动作的上下文；复杂历史/错误/产物报告占满预算时仍可能省略低优先级 keyboard。这些测试不等于所有快捷键在每个真实 guest 软件中均已实测，也不支持性能提升结论。
