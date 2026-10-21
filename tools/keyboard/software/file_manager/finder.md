# Finder (macOS 资料)

目录 ID：`app.finder`。类型：`file_manager`。平台：`macos`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Finder。

任务说明中的匹配别名：`Apple Finder`、`macOS Finder`。匹配规则与平台过滤见 [使用说明](../../README.md)。

macOS 专用资料；当前 Linux/X11 Mini 不得启用 command 组合键。Option 记为 alt；移植时须验证原生适配器。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.finder.files

适用范围：Finder file selection。

同调用查询格式：`<key_lookup>app.finder.files</key_lookup>`。

```json
[
  {"intent": "rename selected item", "tool": {"action":"key","keys":["return"]}},
  {"intent": "new folder", "tool": {"action":"key","keys":["command","shift","n"]}},
  {"intent": "Go to Folder dialog", "tool": {"action":"key","keys":["command","shift","g"]}},
  {"intent": "Quick Look selection", "tool": {"action":"key","keys":["space"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Mac keyboard shortcuts](https://support.apple.com/en-us/102650)。
