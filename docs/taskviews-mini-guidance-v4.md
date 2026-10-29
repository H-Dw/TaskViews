# 指导 v4：待确认效果、阅读保留与阶段复核

本次正式评测仅 legacy、reasoning=low、发票/GIMP。按用户缩减要求共四格，顺序为 always 发票、always GIMP、stage 发票、stage GIMP。两个条件只改变复核展示时机，均使用 full 措辞、fixed_reference 预算选择；两组共享本次其他优化。每格一次，不按分数重跑。旧 v3 作为冻结参照，GIMP 原结果为 high，不能当作同条件 low 对照。

阅读保留使用公开结论及原观察来源，不读取模型隐藏推理。只有已确认派发、且由对应 decision 的公开缩放意图支持的数字输入才按视图调整处理，焦点仍未确认；其他内容编辑、撤销、公开纠正、任务边界及有效期会使旧结论失效。失败/未派发输入不会抹掉已读记录。结论仍是 proposal，只能在相同未改变内容上复用，不保存过时坐标。

缩放输入后记录执行来源、输入值、未确认效果、有效期和失效原因；后续点击或截图不会把状态改回泛化定位。Enter 派发后转向观察实际比例，不表示缩放成功。窗口切换、取消、内容编辑、未知派发和过期会清理作用域；公开后续观察只能将效果标记为模型报告，不能认证成功。短循环覆盖 triple_click；窗口循环给出核对实际窗口的约束。具体当前指导不会被泛化 focus 卡覆盖，只有原任务宽泛意图时仍保留循环定位建议。

当前观察与真实错误、最新执行证据、当前阶段完整卡、简短已读结论优先。完整依赖组不截前缀，已读结论逐条完整打包。重复检查状态引用 current，来源 URL/完整哈希/评分/候选/失效审计保存在本地。四 View 补充包继续最多 3000 UTF-8 bytes；完整内容无法容纳时明示省略，不截事实。原生 v3 整轮历史裁剪、工具配对、官方编译与截图坐标协议不变。

三个独立冻结配置：

- `--mini-review-timing always|stage`：stage 执行中短提醒，在公开收尾/保存导出意图或剩余不超过六次决策时展示完整格式；当前观察编号始终为 current.ref。突然结束但缺报告时仍受原严格校验及同预算纠错约束。
- `--mini-review-prompt full|compact`：只控制措辞；不改变终态结构、来源验证、unknown 等级、两次再生成或时间/token 限制。
- `--mini-review-budget fixed_reference|refill`：fixed_reference 按始终完整提示成本选取事实，节省空间不回填；refill 才可用实际空间补充。离线同输入分别验证三因素；本轮在线只比较 timing，另两项固定。

本轮唯一根目录 `D:/cua_lty/OSWorld-K3-TaskViews/runs/verified-mini-guidance-v4-legacy-low40-20261027-v1`；WSL 同目录 `/mnt/d/...`。入口 `control/campaign.py`，每条命令必须 `--root` 本根目录。configure 后唯一 start --execute-approved-plan，后台先串行完成12个原runner模拟和2套GIMP评分接入、本地源码/镜像/资源核验，冻结四份计划后执行。用户先前豁免联网provider/定位预检，本轮不新增探针；离线证明不等于任务成绩。

SX_URL_SB / qwen3.8-max，thinking=true、low、temperature0，最多40次 actor.predict 含空动作，每请求16000/单步32000输出 tokens；1920×1080、relative每轴0–1000、history20/image1/fold1。无 high/flat/linked、临时 web、controls、额外规划模型。官方 benchmark/compiler/资产/评分不变，不读 gold。每格新guest/actor/journal，评分存证并精确清理后才能下一格。

WSL Ubuntu-24.04，Python `/home/dawei/osworld2/OSWorld-V2/.venv/bin/python`；PYTHONPATH `/mnt/d/cua_lty/UI-KOBE-TaskViews/.venv/lib/python3.12/site-packages`，PYTHONDONTWRITEBYTECODE=1。既有 `media-review-runtime-20261016.py` 进程内加载SX，不显示/存档凭据。辅助128MiB，实际actor/runner2GiB，VM3GiB/guest2GiB，零swap。Windows真实空闲RAM>2GiB，C/D空闲至少45/12GiB。全局执行锁 `/mnt/d/cua_lty/osworld_verified_setup/osworld1-eval.lock`。

每小时独立 inspect 一次，检查源码/queue/state/回执PID、start_ticks、boot_id/原outcome/有界日志/阶段时限/所属容器；健康即退出，重叠跳过，不持续对话或等待评测。异常保存证据并暂停定时任务；不热改冻结代码、自动整任务重启或重放旧episode，不泛化kill/prune。正常0分和模型错误不是代码修改或挑分重跑理由。主分支不切换，评测使用单独冻结快照，restore-check不覆盖人工编辑。

终态且launcher退出后 report、restore-check，并独立分析得分/有效性/决策/GUI回执与派发/API尝试与完整/输出及其中推理tokens/未知用量金额/耗时/复核再生成/实际指导及阅读送达。需要结合 delivered 和实际请求，prepared 不等于已送达；配方参数匹配不证明模型采纳。只读本轮PNG产物统计alpha，不读gold。按任务、时机分列，单次试验不宣称因果或显著收益；报告完成暂停巡检。原v3源码和结果见 frozen-v3-reference.json，不改写或挑分复跑。仅本地，不自动推送GitHub。
