# 浏览器共性

目录 ID：`type.browser`。类型：`browser`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Chrome、Firefox、Edge。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.browser.navigation

适用范围：Chrome/Firefox/Edge browser chrome; page scripts can intercept keys。

同调用查询格式：`<key_lookup>type.browser.navigation</key_lookup>`。

```json
[
  {"intent": "focus address bar", "tool": {"action":"key","keys":["ctrl","l"]}},
  {"intent": "back in history", "tool": {"action":"key","keys":["alt","left"]}},
  {"intent": "forward in history", "tool": {"action":"key","keys":["alt","right"]}},
  {"intent": "reload page", "tool": {"action":"key","keys":["ctrl","r"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Chrome keyboard shortcuts](https://support.google.com/chrome/answer/157179?hl=en-PG)，[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)，[Edge keyboard shortcuts](https://support.microsoft.com/en-us/edge/keyboard-shortcuts-in-microsoft-edge)。

## type.browser.tabs

适用范围：Chrome/Firefox/Edge tab controls。

同调用查询格式：`<key_lookup>type.browser.tabs</key_lookup>`。

```json
[
  {"intent": "new tab", "tool": {"action":"key","keys":["ctrl","t"]}},
  {"intent": "close current tab", "tool": {"action":"key","keys":["ctrl","w"]}},
  {"intent": "restore closed tab", "tool": {"action":"key","keys":["ctrl","shift","t"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Chrome keyboard shortcuts](https://support.google.com/chrome/answer/157179?hl=en-PG)，[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)，[Edge keyboard shortcuts](https://support.microsoft.com/en-us/edge/keyboard-shortcuts-in-microsoft-edge)。

## type.browser.zoom

适用范围：Chrome/Firefox/Edge page zoom, not embedded application zoom。

同调用查询格式：`<key_lookup>type.browser.zoom</key_lookup>`。

```json
[
  {"intent": "zoom page out", "tool": {"action":"key","keys":["ctrl","-"]}},
  {"intent": "zoom page in", "tool": {"action":"key","keys":["ctrl","+"]}},
  {"intent": "reset page zoom", "tool": {"action":"key","keys":["ctrl","0"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Chrome keyboard shortcuts](https://support.google.com/chrome/answer/157179?hl=en-PG)，[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)，[Edge keyboard shortcuts](https://support.microsoft.com/en-us/edge/keyboard-shortcuts-in-microsoft-edge)。
