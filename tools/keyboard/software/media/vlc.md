# VLC

目录 ID：`app.vlc`。类型：`media`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：VLC。

任务说明中的匹配别名：`VLC`、`VideoLAN`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.vlc.playback

适用范围：VLC player; not preferences text fields。

同调用查询格式：`<key_lookup>app.vlc.playback</key_lookup>`。

```json
[
  {"intent": "toggle playback", "tool": {"action":"key","keys":["space"]}},
  {"intent": "stop playback", "tool": {"action":"key","keys":["s"]}},
  {"intent": "toggle full screen", "tool": {"action":"key","keys":["f"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[VLC desktop hotkeys](https://docs.videolan.me/vlc-user/desktop/3.0/en/basic/hotkeys.html)。

## app.vlc.seeking

适用范围：VLC focused player。

同调用查询格式：`<key_lookup>app.vlc.seeking</key_lookup>`。

```json
[
  {"intent": "short seek backward", "tool": {"action":"key","keys":["shift","left"]}},
  {"intent": "short seek forward", "tool": {"action":"key","keys":["shift","right"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[VLC desktop hotkeys](https://docs.videolan.me/vlc-user/desktop/3.0/en/basic/hotkeys.html)。
