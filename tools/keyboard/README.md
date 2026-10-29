# TaskViews-Mini 按键 tools

新 Mini 计划默认保留[通用控制](general.md)，并根据原始任务说明和 `related_apps` 中的软件名称启用兼容目录。完整列表见[分类索引](index.md)，评测软件的选择依据、覆盖情况和缺口见[检索记录](survey.md)。

2026-10-20：general 已由 11 个主题、23 条配方扩充到 34 个主题、86 条配方，补全文本编辑和常见 GUI 控件操作。运行时 catalog 与生成文档同步更新；[原版备份](backups/general.2026-10-20.pre-expansion.md)、[实验来源与调研](../../docs/taskviews-mini-v7-keyboard-audit-20261020.md)保留了 v7 的冻结内容和实际派送情况。其他目录沿用各自原有核对日期。

同日增加了[任务名自动选择](../../docs/taskviews-keyboard-auto-selection-20261020.md)：匹配别名、同时启用多个软件、过滤当前 Linux/X11 不支持的目录，并将匹配依据写入新计划。它作用于 TaskViews 的准备与运行逻辑，搜索 skill 继续用于资料调研。

另有默认关闭的[任务级联网调研](../../docs/task-keyboard-web-research-20261020.md)：`--keyboard-research` 在 CUA 前提取明确/推测软件，通过 API 搜索并先保存 Markdown，再整理为本任务的 `task.*` 临时目录。结果保存在新计划自己的 `keyboard-research/` 中，不加入本共享分类库；可使用用户 skill `task-keyboard-research` 单独生成。

## 分类规则

| 层级 | 判断依据 | 默认状态 | 例子 |
| --- | --- | --- | --- |
| general | 多类传统 GUI 共享且有控件前提的导航、编辑、控件操作及菜单已确认的内容命令 | 启用 | Tab、Escape、Ctrl+C/V、下拉框选择 |
| type | 一组已核对的软件共享同一动作及组合键；适用成员列在文档中 | 关闭 | 浏览器地址栏 Ctrl+L；Calc/Excel 编辑单元格 F2 |
| platform | 操作系统或窗口管理器提供的绑定 | 关闭 | GNOME Alt+F10；Windows Win+Up；macOS Command+M |
| app | 特定软件、版本、工作区或 keymap 才成立的绑定 | 名称匹配且平台兼容时启用 | Evince Ctrl+PageDown；GIMP 裸 `-`；VS Code Ctrl+P |

“通用”表示在文档限定的平台和传统控件中可迁移。它不表示所有画布、游戏、终端、表格和自定义控件都遵循这些语义。当前 Mini 的平台为 Linux/X11；Windows、macOS 和 Android 的资料不会被发送为当前后端可用指令。相同快捷键可能对应不同动作：F2 在文件管理器重命名、Calc 编辑单元格、Blender 重命名对象；Ctrl+L 在浏览器聚焦地址栏，在 Word 对齐文本。

## 当前能力指导路径（2026-10-28）

当前新建 Mini 计划使用 `--keyboard-mode task_capabilities`。`guidance.json` 定义完整操作卡，
`guidance_semantics.py` 区分动作、对象和状态，`guidance_eligibility.py` 先检查能力、动作、软件对象及阶段，
仅在通过检查的候选之间排序。软件目录已启用不表示窗口或焦点已确认。

`<key_lookup>` 是补充请求，不能自行启用能力或软件，也不能仅凭主题名取得其中全部按键。
例如查询 `app.evince.zoom` 还需要当前有明确的 Evince 缩放需求；“Zoom out in Evince”只返回缩小绑定。
没有动作契约的旧目录绑定保留为参考，当前能力路径记录 `no_audited_operation_contract`，不会猜测适用性。
目录文档中的查询标签是地址，不是执行许可。逐卡、逐目录的映射和限制见
[本轮核验表](../../docs/taskviews-keyboard-eligibility-v7-audit.md)。

旧 `task_names` / `manual` 路径的 topic 正则、显式查阅行为仍保留用于历史复现；下面有关这些模式的说明
只适用于旧路径。当前策略版本为 `capability_guidance_v7`，与历史 Mini v7 的版本名称不同。
变更后的冻结计划和 checkpoint 不可混用；历史计划须使用对应冻结源码运行。

## 指令与检索（旧目录路径）

每条配方继续使用当前按键 View 格式：

```json
{"intent":"copy selection","tool":{"action":"key","keys":["ctrl","c"]}}
```

`keys` 表示一次同时按下的组合键。`pagedown`、`pageup`、`return`、`escape`、`-` 和 `+` 是后端 token，不写作 `page_down`、`Page Down` 或 `minus`。GNOME Super 在当前 X11 后端写为 `win`。macOS `command` 只保留在参考文档中。

连续按键应拆成独立原生调用。例如 GitLab 的 `g` 后按 `i` 不能写作 `{"action":"key","keys":["g","i"]}`；PyCharm 双击 Shift 也不能编码为同时按下两个 Shift。本批目录只收录能表达为一次组合键的配方。输入命令或文字继续使用原生 `type`，不把命令字符串塞进 `keys`。

模型可在同一次回复的正文中附加 `<key_lookup>page_navigation</key_lookup>`，下一次 View 读取最新意图并返回对应配方。没有匹配意图时省略键盘参考。默认允许的主题见 general 文档；缩放、重命名、最大化/最小化不会从普通文案猜测软件。

新计划默认使用 `--keyboard-mode task_names`。例如任务包含 `VLC`，或 `related_apps` 包含 `vlc`，会启用 `general + app.vlc`；`VS Code`、`VSCode`、`Visual Studio Code` 归并为 `app.vscode`。同时出现 Chrome 和 VS Code 会启用两个软件目录。只出现 `LibreOffice` 无法确定组件，不会猜测 Writer/Calc/Impress；普通文案中的 `word`、`files`、`mail`、`notes`、`preview` 也不会单独触发。

只读取原始公开任务的 `instruction`、`related_apps`；不读取 evaluator、setup 命令、截图内容或模型后续正文进行自动扩容。别名定义在 catalog 的 `task_aliases` 中。`related_apps` 还接受完整目录 ID 和软件 ID，例如 `app.libreoffice_calc` / `libreoffice_calc`。匹配一个应用不会连带加载其类型目录；唯一当前类型别名是 GNOME Terminal → `type.terminal`。

可以在既有 prepare 命令上附加目录，例如：

```text
--taskviews-profile mini_fixed_v1 --qwen-arm taskviews
--keyboard-toolset type.browser --keyboard-toolset app.evince
```

`--keyboard-toolset` 是对自动匹配结果的补充。目录 ID 必须来自索引；手动指定 Linux/X11 不兼容的目录会在准备时拒绝，自动识别到这类目录则记录跳过原因。启用 `app.evince` 不会自动启用 `type.browser`、GNOME 或其他应用。

需要完全手动配置时使用 `--keyboard-mode manual`；不附加目录时只启用 general。这个开关恢复手动选择方式，但不会恢复旧 general 内容；旧版内容保存在备份和历史实验冻结文件中。

启用后仍需精确查询，例如 `<key_lookup>app.evince.zoom</key_lookup>` 或 `<key_lookup>type.browser.zoom</key_lookup>`。选择结果表明哪些参考资料可检索；实际软件、焦点和快捷键是否可用仍由当前截图确认。名称匹配不判断否定句，也不证明已安装、已打开或在前台。

计划冻结 `mini_keyboard_tools` 的完整 policy 和 `mini_keyboard_selection` 的输入摘要、模式、手动目录、匹配别名、跳过原因及最终目录；原生入口也将两者复制到 manifest。runner 核对后设置内部 `UI_KOBE_MINI_KEYBOARD_TOOLS` JSON 数组，并清除未声明的环境选择。检查点保存本次启用目录及目录 SHA，恢复时要求完全一致。开发直连 actor 可使用该内部变量；正式实验以冻结计划为准。

自动选择参数由 `osworld_native_experiment.py prepare`（Mini TaskViews arm）和 `verified_invoice.py prepare`（包括 `--task vlc/gimp`）提供。`validate_verified_invoice.py` 使用相同参数，离线证据必须与准备计划的选择一致；baseline/UI-KOBE arm 不接收专用 keyboard View。`verified_media.py` 矩阵包装器沿用其旧修订冻结约束，不能直接拿历史矩阵运行当前代码。旧的显式 controls-only 扩展不会同时发送 keyboard View，因此不能与专用按键目录组合启用。

只预览匹配结果可运行：

```text
python -m kobe_views.keyboard_selection --instruction "Use Chrome and VS Code" --related-app vlc
```

## 资料与运行边界

唯一维护源是 [`catalog.json`](../../kobe_views/key_tools/catalog.json)。`python scripts/render_keyboard_tools.py` 从该源生成本目录的分类文档和索引；`--check` 检查文档是否同步。研究软件清单与绑定证据分别保存，评测集覆盖某软件不能证明该快捷键在该评测镜像中有效。

View 保持 `current/keyboard/attempts/lessons` 四项、3000 UTF-8 bytes 总预算和额外模型角色请求数 0。只按需发送一个主题，不整包注入文档。历史按键仅按选中主题的精确组合键匹配，保留本 episode 的原始事件与前后图；旧按键来自其他软件的可能性仍然存在，回执和图像变化均不证明语义成功。

此前实现修订在文档中称为 `mini_keyboard_tools_v5`；运行时 catalog 的协议字段和 v7 冻结计划实际记录为 `mini_keyboard_tools_v3`，与整体实现 `mini_report_recovery_v7` 分别标识不同层次。2026-10-20 扩充目录内容并新增 `mini_keyboard_task_names_v1` 选择机制；配方协议不变，内容与别名由 catalog SHA 冻结。旧实现或旧目录的计划、manifest 和检查点不能被静默续跑为新内容。

2026-10-17 最终全仓验证：60 套、1481 项通过，失败 0、跳过 0，Ruff 0；包含 500 步模拟轨迹和第 250 步检查点恢复。注册的 128 MiB / Swap 0 验证 scope 中 OOM / OOM kill 均为 0，官方底座和项目源码在验证前后保持一致。原始结果见 [final-validation-r2.json](../../outputs/keyboard-tools-20261017/final-validation-r2.json)。先前失败记录保留在同目录，未与最终通过数相加。

文档默认值经过来源核对；本次验证为离线工程验证，未逐项驱动真实软件，也未生成新的 OSWorld 任务成绩。
