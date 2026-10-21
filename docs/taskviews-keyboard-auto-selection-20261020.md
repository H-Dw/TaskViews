# TaskViews 按任务软件名选择按键目录

实现日期：2026-10-20。此功能接在 TaskViews 的实验准备和运行入口中，版本为 `mini_keyboard_task_names_v1`。它不依赖搜索 skill 被调用，也不增加模型请求。按键配方仍从 [`catalog.json`](../kobe_views/key_tools/catalog.json) 读取。

## 默认行为与例子

新 Mini TaskViews 计划默认使用 `--keyboard-mode task_names`，始终保留 `general`，再匹配公开任务的 `instruction` 和 `related_apps`。一个任务可以同时启用多个软件目录。

| 公开任务中的信息 | 当前 Linux/X11 启用结果 |
| --- | --- |
| `Use VLC` 或 `用VLC播放` | `general`、`app.vlc` |
| `VS Code`、`VSCode`、`Visual Studio Code` | `general`、`app.vscode` |
| `Use Chrome and VS Code`，另有 `related_apps: ["vlc"]` | `general`、`app.chrome`、`app.vlc`、`app.vscode` |
| `related_apps: ["libreoffice_calc"]` | `general`、`app.libreoffice_calc` |
| `GNOME Terminal` | `general`、`type.terminal` |
| `Microsoft Word` 或 `Apple Safari` | `general`；记录对应目录因平台不兼容而跳过 |
| `Write a word; preview files, mail and notes` | `general`；这些普通词不单独触发软件目录 |
| 只有 `LibreOffice`，没有组件名 | `general`；不猜测 Writer、Calc 或 Impress |

实际 v7 VLC 任务 `fba2c100-79e8-42df-ae74-b592418d54f4` 的正文要求截取视频画面并保存到桌面，未直接写出 VLC；公开字段 `related_apps` 为 `["vlc"]`。新选择器会因此启用 `app.vlc`。2026-10-19 的历史 v7 计划仍记录仅启用 general，本次没有改写或重跑历史实验。

catalog 登记了 34 个软件目录及 1 个 GNOME Terminal 类型目录，共 79 个文本别名。按现有 Linux/X11 兼容性可自动启用 18 个软件目录及 `type.terminal`；另外 16 个软件目录属于其他平台或参考资料，匹配后只保留跳过记录。完整别名可在各软件的[生成文档](../tools/keyboard/index.md)中查看。

## 匹配和检索分别处理

1. 在准备新计划时，读取公开任务字段，进行 Unicode NFKC 规范化、大小写归一和空白合并。
2. `related_apps` 使用精确匹配，支持登记别名、完整目录 ID，以及 `app.` 后的软件 ID。任务正文使用带 ASCII 单词边界保护的别名匹配；`用VLC播放` 可以命中，`my_vlc_player` 不会命中。
3. 合并任务匹配目录与用户显式添加的目录，去重、排序，过滤自动匹配到的不可用目录。
4. 将选择依据及目录内容指纹写入实验计划，运行前重新核对。此后目录集合保持固定。
5. 模型从 current View 的检索提示中看到已启用的主题，仍通过精确名称请求一个主题，例如 `<key_lookup>app.vlc.playback</key_lookup>`。下一次 View 返回该主题的配方。

自动启用使目录可以被检索，不会立即执行快捷键，也不会把所有软件文档放入模型上下文。四个 View、3000 UTF-8 bytes 总预算、每次最多一个按键主题和额外角色请求数 0 均保持原约束；预算不足仍遵循既有省略规则。

匹配只读取 `instruction` 和 `related_apps`，不读取 evaluator、setup 命令、截图或模型后续回复来扩大目录集合。软件名匹配也不判断否定语义：一句“不要使用 VLC”仍可能启用其参考资料。是否应该操作该软件、当前窗口、焦点、编辑模式和快捷键效果仍需依据用户要求及当前截图判断。

软件目录不会自动带出类型目录或其他软件。例如 Chrome 的专属配方在 `app.chrome`；共用地址栏、标签和缩放配方仍需显式加上 `type.browser`。GNOME Terminal 的已核对按键位于 `type.terminal`，因此为它单独登记了名称映射。

## 使用方式

以下参数附加到现有实验准备命令，不构成完整的实验启动命令：

```text
# 默认：按公开任务匹配，可省略此参数
--keyboard-mode task_names

# 自动匹配之外，再启用浏览器共用配方
--keyboard-toolset type.browser

# 完全手动，只使用 general
--keyboard-mode manual

# 完全手动，使用 general 和指定目录
--keyboard-mode manual --keyboard-toolset app.evince
```

支持入口：

- [`osworld_native_experiment.py prepare`](../scripts/osworld_native_experiment.py)：`mini_fixed_v1` 的 TaskViews arm。
- [`verified_invoice.py prepare`](../scripts/verified_invoice.py)：OSWorld-Verified 入口，包括该脚本的 `--task invoice/vlc/gimp` 任务选项和现有实验配置限制。
- [`validate_verified_invoice.py`](../scripts/validate_verified_invoice.py)：离线验证使用相同目录选择参数，证据中的选择必须与准备计划一致。

原有 `verified_media.py` 矩阵包装器还有历史代码修订门槛，本次保留该门槛；使用当前改动的单任务入口需要重新验证并准备新计划。baseline/UI-KOBE 分支不接收专用 keyboard View。

只预览选择，不运行模型或启动虚拟机：

```text
python -m kobe_views.keyboard_selection --instruction "Use Chrome and VS Code" --related-app vlc
```

自动匹配找不到的软件保持 general，可用 `--keyboard-toolset` 手动补充已存在且兼容的目录。指定不存在、不兼容、无配方或重复的手动目录会报错。`manual` 恢复的是选择方式；不会自动恢复备份里的旧 general 配方。

## 冻结记录与维护

[`keyboard_selection.py`](../kobe_views/keyboard_selection.py) 生成两项配置：

- `mini_keyboard_tools`：最终启用目录、可查询主题、catalog SHA 及按键 View 契约。
- `mini_keyboard_selection`：选择版本、模式、原始公开字段摘要、手动目录、命中的别名及字段、跳过原因、最终目录。

原生入口把两项复制进 manifest，并在启动前核对。Verified 入口将两项与离线验证证据一起核对。runner 用冻结目录覆盖进程继承的设置，检查点继续验证本次目录和 catalog SHA。任务字段、选择依据、目录配方或别名配置改变后，应重新验证和准备新计划。

新增软件时，先在 `toolsets` 中准备带官方来源、平台、作用范围和结果检查的配方，再在 catalog 的 `task_aliases` 中登记目录 ID → 别名列表。已有目录增加别名只需编辑该映射，然后运行：

```text
python scripts/render_keyboard_tools.py
python scripts/render_keyboard_tools.py --check
```

生成文档的别名列表来自同一份 JSON，避免代码与 Markdown 各维护一套规则。原 general 和 catalog 的[逐字节备份](../tools/keyboard/backups/)继续保留。

## 验证范围

新增离线测试覆盖全部登记目录的匹配或平台跳过、大小写与全角字符、常见词和子串误匹配、多软件合并、手动模式、公开字段隔离、冻结配置变更拒绝、原生计划到 manifest 的传递及 Verified 准备入口。

还通过实际 actor 构造验证所有可自动启用目录的 29 个主题能被查询并送达，在 3000 bytes 预算内完成；同时检查五软件任务的主题可共同出现在检索提示中。这些是离线工程测试，未逐项操作真实应用，也没有产生新的 OSWorld 成绩。

最终相关回归：8 个测试文件共 265 项通过，失败 0；Ruff、生成文档同步检查和本地文档链接检查通过。原 general/catalog 备份及历史 v7 的 plan、source-freeze、telemetry 文件哈希与修改前一致。
