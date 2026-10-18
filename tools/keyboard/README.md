# TaskViews-Mini 按键 tools

默认仅使用[通用控制](general.md)。完整列表见[分类索引](index.md)，评测软件的选择依据、覆盖情况和缺口见[检索记录](survey.md)。

## 分类规则

| 层级 | 判断依据 | 默认状态 | 例子 |
| --- | --- | --- | --- |
| general | 多类传统 GUI 软件共享、且能说明控件前提的导航或编辑操作 | 启用 | Tab、Escape、Ctrl+C/V、PageDown |
| type | 一组已核对的软件共享同一动作及组合键；适用成员列在文档中 | 关闭 | 浏览器地址栏 Ctrl+L；Calc/Excel 编辑单元格 F2 |
| platform | 操作系统或窗口管理器提供的绑定 | 关闭 | GNOME Alt+F10；Windows Win+Up；macOS Command+M |
| app | 特定软件、版本、工作区或 keymap 才成立的绑定 | 关闭 | Evince Ctrl+PageDown；GIMP 裸 `-`；VS Code Ctrl+P |

“通用”表示在文档限定的平台和传统控件中可迁移。它不表示所有画布、游戏、终端、表格和自定义控件都遵循这些语义。当前 Mini 的平台为 Linux/X11；Windows、macOS 和 Android 的资料不会被发送为当前后端可用指令。相同快捷键可能对应不同动作：F2 在文件管理器重命名、Calc 编辑单元格、Blender 重命名对象；Ctrl+L 在浏览器聚焦地址栏，在 Word 对齐文本。

## 指令与检索

每条配方继续使用当前按键 View 格式：

```json
{"intent":"copy selection","tool":{"action":"key","keys":["ctrl","c"]}}
```

`keys` 表示一次同时按下的组合键。`pagedown`、`pageup`、`return`、`escape`、`-` 和 `+` 是后端 token，不写作 `page_down`、`Page Down` 或 `minus`。GNOME Super 在当前 X11 后端写为 `win`。macOS `command` 只保留在参考文档中。

连续按键应拆成独立原生调用。例如 GitLab 的 `g` 后按 `i` 不能写作 `{"action":"key","keys":["g","i"]}`；PyCharm 双击 Shift 也不能编码为同时按下两个 Shift。本批目录只收录能表达为一次组合键的配方。输入命令或文字继续使用原生 `type`，不把命令字符串塞进 `keys`。

模型可在同一次回复的正文中附加 `<key_lookup>page_navigation</key_lookup>`，下一次 View 读取最新意图并返回对应配方。没有匹配意图时省略键盘参考。默认允许的主题见 general 文档；缩放、重命名、最大化/最小化不会从普通文案猜测软件。

按软件扩展需要在新冻结计划的 prepare 参数中明确选择，例如：

```text
--taskviews-profile mini_fixed_v1 --qwen-arm taskviews
--keyboard-toolset type.browser --keyboard-toolset app.evince
```

这些参数附加到既有 prepare 命令；不指定 `--keyboard-toolset` 时只启用 general。目录 ID 必须来自索引，Linux/X11 不兼容的目录会在准备时拒绝。启用 `app.evince` 不会自动启用 `type.browser`、GNOME 或其他应用。

启用后仍需精确查询，例如 `<key_lookup>app.evince.zoom</key_lookup>` 或 `<key_lookup>type.browser.zoom</key_lookup>`。选用目录是配置事实，实际软件、焦点和快捷键是否可用仍由当前截图确认。软件名称出现在任务中不会自行启用目录。没有全局“加载所有软件”的隐式路径。

计划和 manifest 冻结 `mini_keyboard_tools` 的完整 policy；runner 核对后设置内部 `UI_KOBE_MINI_KEYBOARD_TOOLS` JSON 数组，并清除未声明的环境选择。检查点保存本次启用目录及目录 SHA，恢复时要求完全一致。开发直连 actor 可使用该内部变量；正式实验以冻结计划为准。

上述可选参数由 `osworld_native_experiment.py prepare` 提供。当前 `verified_invoice.py` / `verified_media.py` 的 OSWorld-Verified 比较入口固定使用 general，并主动清除继承的专用目录选择。旧的显式 controls-only 扩展不会同时发送 keyboard View，因此不能与专用按键目录组合启用。

## 资料与运行边界

唯一维护源是 [`catalog.json`](../../kobe_views/key_tools/catalog.json)。`python scripts/render_keyboard_tools.py` 从该源生成本目录的分类文档和索引；`--check` 检查文档是否同步。研究软件清单与绑定证据分别保存，评测集覆盖某软件不能证明该快捷键在该评测镜像中有效。

View 保持 `current/keyboard/attempts/lessons` 四项、3000 UTF-8 bytes 总预算和额外模型角色请求数 0。只按需发送一个主题，不整包注入文档。历史按键仅按选中主题的精确组合键匹配，保留本 episode 的原始事件与前后图；旧按键来自其他软件的可能性仍然存在，回执和图像变化均不证明语义成功。

本修订为 `mini_keyboard_tools_v5`。旧实现的计划、manifest 和检查点不能被静默续跑为本版本。

2026-10-17 最终全仓验证：60 套、1481 项通过，失败 0、跳过 0，Ruff 0；包含 500 步模拟轨迹和第 250 步检查点恢复。注册的 128 MiB / Swap 0 验证 scope 中 OOM / OOM kill 均为 0，官方底座和项目源码在验证前后保持一致。原始结果见 [final-validation-r2.json](../../outputs/keyboard-tools-20261017/final-validation-r2.json)。先前失败记录保留在同目录，未与最终通过数相加。

文档默认值经过来源核对；本次验证为离线工程验证，未逐项驱动真实软件，也未生成新的 OSWorld 任务成绩。
