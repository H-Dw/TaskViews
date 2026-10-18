# 媒体时间轴共性

目录 ID：`type.media`。类型：`media`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：VLC、Audacity。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.media.playback

适用范围：VLC/Audacity playback area; text input must not have focus。

同调用查询格式：`<key_lookup>type.media.playback</key_lookup>`。

```json
[
  {"intent": "toggle play or pause", "tool": {"action":"key","keys":["space"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[VLC desktop hotkeys](https://docs.videolan.me/vlc-user/desktop/3.0/en/basic/hotkeys.html)，[Audacity command and keyboard reference](https://manual.audacityteam.org/man/keyboard_shortcut_reference.html)。
