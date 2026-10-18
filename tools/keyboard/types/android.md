# Android 系统按键与触控（资料）

目录 ID：`type.android`。类型：`mobile`。平台：`android`。

状态：分类说明；无可启用配方。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Android。

AndroidWorld/AndroidLab 采用触控及系统导航。Back/Home/Recents 是 Android 系统动作，不是 PyAutoGUI key token；本库不生成伪造的 action:key 指令。原生适配器应使用 KeyEvent KEYCODE_BACK=4、KEYCODE_HOME=3、KEYCODE_APP_SWITCH=187，并单独验证系统导航策略。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

本层没有已确认可共享的业务组合键；按当前画面控件操作，或读取具体软件目录。
