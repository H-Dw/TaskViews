# Graph v1 实现验证（2026-10-22）

当前实现完成统一身份、共享实体、跨 View 关系与 legacy/flat/linked 三模式。

## 回归与源码审计

- 23 个测试文件，545 项通过，0 失败、0 跳过。
- 静态检查通过；官方执行、编译与评分源码审计通过。
- legacy 的三轮 packet 与 actor 请求哈希匹配改造前 6d9e0d7 基准。
- flat/linked 同一输入下除模式与新增关系外保持一致，补充包不超过 3000 UTF-8 bytes。
- 完整证据：[回归 JSON](../validation/mini-graph-v1-20261022-verified.json)。

## 原运行器离线矩阵

| 模式 | 上限：请求数 | 显式结束：请求数 | 空动作：请求数 | 最大包字节 |
|---|---:|---:|---:|---:|
| legacy | 40 | 7 | 40 | 3000 |
| flat | 40 | 7 | 40 | 2747 |
| linked | 40 | 7 | 40 | 2986 |

九种组合全部通过；每次 actor.predict 对应一次模拟响应，无额外角色调用。
原运行器、动作编译和工具 ID 配对参与验证；HTTP、GUI 与 evaluator 返回使用模拟数据。0.125 是测试 sentinel，不是 benchmark 成绩。
矩阵证据：[汇总 JSON](../validation/mini-graph-integration-summary-20261022.json)。

## 同输入消融与限制

报告：[Markdown](../outputs/mini-graph-v1-20261022-final/report.md)、[JSON](../outputs/mini-graph-v1-20261022-final/report.json)。
三个日志快照上 flat/linked 的事实与遗漏完全一致。关系、必要端点与来源占用预算，可能减少历史记录和目录信息；样本第 1 帧的新包省略了按键主题索引，不能把更小字节数解释为无损压缩收益。
这些结果证明结构、兼容、预算和执行接入，不证明真实任务成功率、token 或耗时改善。本次未调用真实模型 API、启动 VM 或执行 GUI。
