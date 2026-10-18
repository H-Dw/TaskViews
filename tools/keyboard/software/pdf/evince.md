# Evince

目录 ID：`app.evince`。类型：`pdf`。平台：`linux`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Evince。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.evince.page_navigation

适用范围：Evince PDF document pane。

同调用查询格式：`<key_lookup>app.evince.page_navigation</key_lookup>`。

```json
[
  {"intent": "next PDF page", "tool": {"action":"key","keys":["ctrl","pagedown"]}},
  {"intent": "previous PDF page", "tool": {"action":"key","keys":["ctrl","pageup"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Evince document navigation](https://help.gnome.org/evince/movingaround.html)。

## app.evince.zoom

适用范围：Evince PDF document。

同调用查询格式：`<key_lookup>app.evince.zoom</key_lookup>`。

```json
[
  {"intent": "zoom out", "tool": {"action":"key","keys":["ctrl","-"]}},
  {"intent": "zoom in", "tool": {"action":"key","keys":["ctrl","+"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Evince zoom](https://help.gnome.org/evince/movingaround.html)。
