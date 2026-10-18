# GNOME 窗口管理

目录 ID：`platform.gnome`。类型：`desktop`。平台：`linux`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：GNOME Shell。

仅 GNOME 默认键位；Super 对应当前 PyAutoGUI X11 的 win。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## platform.gnome.window_maximize

适用范围：GNOME active window; maximize/restore toggle。

同调用查询格式：`<key_lookup>platform.gnome.window_maximize</key_lookup>`。

```json
[
  {"intent": "toggle maximize", "tool": {"action":"key","keys":["alt","f10"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME maximize and restore](https://help.gnome.org/gnome-help/shell-windows-maximize.html)。

## platform.gnome.window_minimize

适用范围：GNOME active window。

同调用查询格式：`<key_lookup>platform.gnome.window_minimize</key_lookup>`。

```json
[
  {"intent": "minimize active window", "tool": {"action":"key","keys":["win","h"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)。

## platform.gnome.window_geometry

适用范围：GNOME active window; arrows then Return/Escape。

同调用查询格式：`<key_lookup>platform.gnome.window_geometry</key_lookup>`。

```json
[
  {"intent": "begin moving window", "tool": {"action":"key","keys":["alt","f7"]}},
  {"intent": "begin resizing window", "tool": {"action":"key","keys":["alt","f8"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME window states](https://help.gnome.org/gnome-help/shell-windows-states.html)。
