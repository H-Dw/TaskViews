# Google Chrome

目录 ID：`app.chrome`。类型：`browser`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Google Chrome。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.chrome.find

适用范围：Google Chrome page content。

同调用查询格式：`<key_lookup>app.chrome.find</key_lookup>`。

```json
[
  {"intent": "find page text", "tool": {"action":"key","keys":["ctrl","f"]}},
  {"intent": "next find match", "tool": {"action":"key","keys":["ctrl","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Chrome keyboard shortcuts](https://support.google.com/chrome/answer/157179?hl=en-PG)。

## app.chrome.bookmarks

适用范围：Chrome browser UI。

同调用查询格式：`<key_lookup>app.chrome.bookmarks</key_lookup>`。

```json
[
  {"intent": "bookmark page", "tool": {"action":"key","keys":["ctrl","d"]}},
  {"intent": "bookmark manager", "tool": {"action":"key","keys":["ctrl","shift","o"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Chrome keyboard shortcuts](https://support.google.com/chrome/answer/157179?hl=en-PG)。

## app.chrome.panels

适用范围：Chrome browser UI。

同调用查询格式：`<key_lookup>app.chrome.panels</key_lookup>`。

```json
[
  {"intent": "downloads", "tool": {"action":"key","keys":["ctrl","j"]}},
  {"intent": "history", "tool": {"action":"key","keys":["ctrl","h"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Chrome keyboard shortcuts](https://support.google.com/chrome/answer/157179?hl=en-PG)。
