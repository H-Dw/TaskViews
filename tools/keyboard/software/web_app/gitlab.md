# GitLab

目录 ID：`app.gitlab`。类型：`web_app`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：GitLab。

GitLab 版本、用户快捷键设置和当前输入焦点会改变绑定。连续键必须分次调用。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.gitlab.help

适用范围：GitLab page outside editable fields; shortcuts enabled。

同调用查询格式：`<key_lookup>app.gitlab.help</key_lookup>`。

```json
[
  {"intent": "show keyboard help", "tool": {"action":"key","keys":["shift","/"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GitLab keyboard shortcuts](https://docs.gitlab.com/user/shortcuts/)。
