# Adobe Photoshop (Windows)

目录 ID：`app.photoshop`。类型：`graphics`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Adobe Photoshop。

任务说明中的匹配别名：`Adobe Photoshop`、`Photoshop`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.photoshop.layers

适用范围：Photoshop default keymap, selected layer。

同调用查询格式：`<key_lookup>app.photoshop.layers</key_lookup>`。

```json
[
  {"intent": "duplicate selected layer", "tool": {"action":"key","keys":["ctrl","j"]}},
  {"intent": "new layer dialog", "tool": {"action":"key","keys":["ctrl","shift","n"]}},
  {"intent": "free transform", "tool": {"action":"key","keys":["ctrl","t"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Photoshop keyboard shortcuts](https://helpx.adobe.com/photoshop/desktop/get-started/settings-and-preferences/view-keyboard-shortcuts.html)。
