# Mail (macOS 资料)

目录 ID：`app.mail`。类型：`email`。平台：`macos`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Mail。

macOS 专用资料；当前 Linux/X11 Mini 不得启用 command 组合键。Option 记为 alt；移植时须验证原生适配器。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.mail.drafts

适用范围：Mail compose UI。

同调用查询格式：`<key_lookup>app.mail.drafts</key_lookup>`。

```json
[
  {"intent": "new draft", "tool": {"action":"key","keys":["command","n"]}},
  {"intent": "attach file dialog", "tool": {"action":"key","keys":["command","shift","a"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Mail keyboard shortcuts](https://support.apple.com/guide/mail/mlhlb94f262b/mac)。
