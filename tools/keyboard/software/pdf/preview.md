# Preview (macOS 资料)

目录 ID：`app.preview`。类型：`pdf`。平台：`macos`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Preview。

任务说明中的匹配别名：`Apple Preview`、`macOS Preview`、`Preview.app`。匹配规则与平台过滤见 [使用说明](../../README.md)。

macOS 专用资料；当前 Linux/X11 Mini 不得启用 command 组合键。Option 记为 alt；移植时须验证原生适配器。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.preview.navigation

适用范围：Preview PDF/image viewer。

同调用查询格式：`<key_lookup>app.preview.navigation</key_lookup>`。

```json
[
  {"intent": "next page", "tool": {"action":"key","keys":["alt","down"]}},
  {"intent": "previous page", "tool": {"action":"key","keys":["alt","up"]}},
  {"intent": "full screen toggle", "tool": {"action":"key","keys":["ctrl","command","f"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Preview keyboard shortcuts](https://support.apple.com/guide/preview/cpprvw0003/mac)。
