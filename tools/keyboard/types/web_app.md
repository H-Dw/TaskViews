# 网页应用控件

目录 ID：`type.web_app`。类型：`web_app`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

站点业务动作无统一快捷键；先观察标签、输入框和站点帮助。浏览器历史/标签页只属于 type.browser。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.web_app.focus

适用范围：standard HTML controls in web applications; custom widgets may differ。

同调用查询格式：`<key_lookup>type.web_app.focus</key_lookup>`。

```json
[
  {"intent": "next focusable control", "tool": {"action":"key","keys":["tab"]}},
  {"intent": "previous focusable control", "tool": {"action":"key","keys":["shift","tab"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Chrome keyboard shortcuts](https://support.google.com/chrome/answer/157179?hl=en-PG)，[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)。
