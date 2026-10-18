# CUA 评测软件与按键资料检索

核对日期：2026-10-17。本次从桌面任务、网页任务、Android 任务和控件定位四类评测中选择软件，再用软件官方手册或官方 keymap 核对绑定。以下列的是与按键目录有关的代表软件，属于检索样本，不是每个评测集的完整应用枚举；一个软件文档也不代表覆盖其全部功能。

## 评测集与软件

| 评测集 | 评测对象与代表软件 | 对应 tools / 处理方式 | 一手资料与版本范围 |
| --- | --- | --- | --- |
| OSWorld / OSWorld-Verified | Ubuntu 桌面及跨应用任务；Chrome、LibreOffice Writer/Calc/Impress、GIMP、VLC、Thunderbird、VS Code、OS 文件操作 | 对应 app 文档；文件操作另分 type.file_manager，GNOME 窗口控制另分 platform.gnome | [官方仓库](https://github.com/xlang-ai/OSWorld)、[论文](https://arxiv.org/abs/2404.07972)；区分原版任务与 2025-07 发布的 Verified 更新 |
| Windows Agent Arena | Windows 桌面；LibreOffice Calc/Writer、Chrome、Edge、Explorer、Settings、VS Code、VLC、Notepad、Clock、Paint | 共用软件与 Windows 软件分别建档；Windows 绑定不在 Linux actor 启用 | [项目页的软件清单](https://microsoft.github.io/WindowsAgentArena/)、[官方仓库](https://github.com/microsoft/WindowsAgentArena)；原始 154 项任务，不把 LibreOffice 误写成 Microsoft Office |
| macOSWorld | Finder、Safari、Notes、Mail、Preview；以及 Pages、Numbers、Keynote、Calendar、Music、QuickTime、Xcode 等 Apple 软件 | 已收录的 macOS 软件均作参考目录；其余保留在扩充清单 | [论文及应用版本表](https://arxiv.org/html/2506.04135v1)、[官方仓库](https://github.com/showlab/macosworld)；202 项任务、30 个应用 |
| MacArena | macOS 原生任务，加 OSWorld 与 macOSWorld 迁移任务；包含 Chrome、GIMP、LibreOffice、Thunderbird、VS Code 等 | 按软件识别资料，但 Linux/Windows 配方不能直接用于 macOS 迁移任务 | [2026 论文](https://arxiv.org/html/2606.06560v1)、[官方仓库](https://github.com/MacPaw/MacArena)；421 项任务、50 个应用 |
| AssistGUI | Windows 生产力与创作软件；Word、PowerPoint、Premiere Pro、After Effects，及系统/文件任务 | Office、video、desktop、file_manager 分类；不共享画布或时间轴按键语义 | [论文](https://arxiv.org/html/2312.13108v2)、[官方仓库](https://github.com/showlab/assistgui)；100 项任务、9 个应用 |
| WorldGUI | PowerPoint、Word、Excel、Acrobat、Settings、文件管理、YouTube/网页、VS Code、VLC；改变初始状态的桌面/网页任务 | 已有软件目录；Acrobat、YouTube 见后续扩充；键盘指令必须重新确认当前工作区 | [论文 v3](https://arxiv.org/html/2502.08047v3)、[官方仓库](https://github.com/showlab/WorldGUI)；以更新后的 611 项任务为范围，未沿用旧版 315 项 |
| WebArena | 自托管 GitLab、Reddit 风格论坛、Magento 商城/后台、OpenStreetMap；Wikipedia 辅助站点 | type.browser / type.web_app；GitLab 单独建档。不能从商业网站最新版手册假定自托管站点支持同一快捷键 | [官方仓库及站点变量](https://github.com/web-arena-x/webarena)、[论文](https://arxiv.org/abs/2307.13854) |
| VisualWebArena | Shopping、Reddit、Classifieds，要求处理图像内容的网页任务 | 浏览器快捷键与站点控件分层；没有核验的站点业务快捷键不编造配方 | [官方仓库](https://github.com/web-arena-x/visualwebarena)、[论文](https://arxiv.org/abs/2401.13649) |
| WorkArena / WorkArena++ | ServiceNow 的列表、表单、知识库和工作流操作 | type.web_app 控件导航；没有把 ServiceNow 的版本/实例绑定当作通用快捷键 | [官方仓库](https://github.com/ServiceNow/WorkArena)；浏览器与业务系统是两层软件 |
| Mind2Web | 多领域真实网站上的人工操作序列 | 以 general 与 type.web_app 为基础；网站名称不会触发专用目录 | [项目页](https://osu-nlp-group.github.io/Mind2Web/)、[官方仓库](https://github.com/OSU-NLP-Group/Mind2Web)；原版为离线操作数据，不能当作全部网站的在线快捷键验证 |
| MiniWoB++ | 按钮、表单、文本输入、菜单和其他合成网页控件 | 用于确定 focus/activate/dismiss 等通用控件层；不对应某个商业软件 | [官方文档](https://miniwob.farama.org/)、[官方仓库](https://github.com/Farama-Foundation/miniwob-plusplus) |
| AndroidWorld | 系统 Contacts/Clock 等与离线第三方 Android 应用；任务包含文件、短信、笔记等 | type.android；系统导航是 Android 动作，未伪装成当前 Linux 的按键 token | [官方项目](https://google-research.github.io/android_world/)、[官方仓库](https://github.com/google-research/android_world)；116 项参数化任务、20 个应用 |
| AndroidLab | Bluecoins、Calendar、Cantook、Clock、Contacts、Maps.me、PiMusic、Settings、Zoom | 全部归 Android 平台资料；桌面上同名 Clock/Zoom 不继承手机绑定 | [官方应用清单](https://github.com/THUDM/Android-Lab)；138 项任务、9 个应用 |
| ScreenSpot-Pro | 专业软件的高分辨率控件定位；PyCharm、VS Code、Photoshop、Premiere、Blender、AutoCAD、MATLAB，另含 CAD/科学软件与 Office | 扩充 text_editor、graphics、video、cad、scientific 资料；定位标注不会证明按键或任务执行成功 | [论文 Table 1 软件与版本](https://arxiv.org/html/2504.07981v1)；23 个应用、3 类 OS，属于 grounding 评测 |

## 已建档范围

精确软件清单、配方数量及运行状态由[分类索引](index.md)从机器目录生成。每个软件的配方引用自己的官方手册；一般编辑、网页控件和 OS 窗口控制分别保留证据来源。

Inkscape、Audacity、GitHub、Outlook classic 和 TextEdit 是按软件类型进行的调研补充，不据此声称上述选定评测集全部使用它们。Evince 用于补全当前 Mini 文档阅读场景，其专用翻页与缩放指令从旧通用目录中移出。

## 覆盖限制与扩充顺序

| 范围 | 当前处理 | 扩充时需要的证据 |
| --- | --- | --- |
| WAA 的 Paint / Notepad / Clock / Settings | 已识别为调研对象；当前仅使用对应控件可适用的 general，未声称已有专用配方 | 对应版本的官方应用快捷键页或实际菜单；原“Windows apps shortcuts”旧链接现重定向为系统快捷键，不能继续充当这些应用的专用证据 |
| macOSWorld 的 Pages / Numbers / Keynote / Calendar / Music / QuickTime / Xcode 等 | 已识别软件类型，当前没有完整专用配方；当前后端也不执行 macOS 资料 | 每个应用的官方快捷键页、版本及可用的 macOS 原生适配器 |
| ScreenSpot-Pro 的 Android Studio / Quartus / VMware / Illustrator / FL Studio / Unreal / DaVinci / SolidWorks / Inventor / Vivado / Origin / Stata / EViews | 保留为后续软件扩充对象；不得从同类型工具推导业务快捷键 | 对应版本、默认 keymap、工作区和官方来源。Word/Excel 在该基准的 macOS 版本不能套用本库 Windows 配方 |
| Acrobat / YouTube / Magento / Reddit / Classifieds / ServiceNow / 地图 | 当前提供浏览器和标准网页控件层；站点/产品专用快捷键未全面收录 | 与基准部署版本相符的页面、设置或帮助面板；避免第三方扩展快捷键混入 |
| Android 各 app | 记录软件范围和 Android 系统动作边界；没有硬件快捷键的功能继续通过当前触控界面操作 | Android 适配器动作定义、版本及设备导航策略；不能假设 Back 等于 Escape |

这份资料库收录的是公开文档中的默认绑定。重映射、语言布局、插件、自定义画布、焦点和弹窗均可能改变效果。离线测试验证分类、格式、检索隔离、后端 token、预算和冻结契约，不代表已在所有评测镜像中逐项执行成功。
