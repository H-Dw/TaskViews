# Safari (macOS 资料)

目录 ID：`app.safari`。类型：`browser`。平台：`macos`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Safari。

任务说明中的匹配别名：`Apple Safari`、`Safari`。匹配规则与平台过滤见 [使用说明](../../README.md)。

macOS 专用资料；当前 Linux/X11 Mini 不得启用 command 组合键。Option 记为 alt；移植时须验证原生适配器。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.safari.navigation

适用范围：Safari browser UI。

同调用查询格式：`<key_lookup>app.safari.navigation</key_lookup>`。

```json
[
  {"intent": "address bar", "tool": {"action":"key","keys":["command","l"]}},
  {"intent": "new tab", "tool": {"action":"key","keys":["command","t"]}},
  {"intent": "reload page", "tool": {"action":"key","keys":["command","r"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Safari keyboard shortcuts](https://support.apple.com/guide/safari/cpsh003/mac)。
