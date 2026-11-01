# AUDIT · UIRSI r38 / r39 后端复核：/api/infra/status（2026-11-02 00:20 起，独立复核方 = AUDIT，交总调度 fredw-2b）

分工：界面部分归 UIAUDIT；AUDIT 只核后端接口 /api/infra/status 的数据，是不是和 data/netfix/net_status.json（NETFIX 隧道监管）、data/qa/infra_watchdog_state.json（看门狗）、以及实际探测一致。机读版：data/qa/audit/UIRSI_backend_r01.json

## 结论：**不通过（P1）**：接口把 6 条连接全部报成“断了，自动重连没在运行”，实际是 5/6 通

### 同一时刻（00:20）四个来源的对照

| 端口（卡） | AUDIT 直接探测 127.0.0.1:<端口>/system_stats | net_status.json（00:20:23，监管 pid 37484） | 看门狗 state（00:20:10） | **/api/infra/status（00:20:07）** |
|---|---|---|---|---|
| 18188（gpu33·卡0） | 200 | host gpu33-l0 up，ok | fails 0 | ok=false，“断了，自动重连没在运行”，ssh 状态 stopped |
| 18189（gpu33·卡1） | 200 | gpu33-l1 up，ok | 0 | 同上（错） |
| 18191（gpu33·卡3） | 200 | gpu33-l3 up，ok | 0 | 同上（错） |
| 18288（gpu36·卡0） | 200 | gpu36-l0 up，ok | 0 | 同上（错） |
| 18289（gpu36·卡1） | **000** | gpu36-l1 up，**ok=false** | fails 4，down [18289] | ok=false（结论对，原因写错：“自动重连没在运行”，实际 ssh 是 up 状态） |
| 18290（gpu36·卡2） | 200 | gpu36-l2 up，ok | 0 | 同上（错） |
| 合计 | 5/6 通 | tunnels_up 5 / 6 | 只有 18289 断 | summary：“到两台服务器的连接全断了，正在自动重连”，level=bad |

跳板（relay）一项：接口 ok=true “通”，和 net_status relay.up=true 一致。servers / local 两块没有发现矛盾。

### 根因（代码）
services/api/ns_api/infra_status.py（23:49:00）第 38–39 行 TUNNEL_CARDS 把端口映射到主机名 "gpu33" / "gpu36"，第 112–114 行 `_from_netfix` 用 `hosts.get(host)` 去 net_status.json 里取 ssh 状态。但现在的 net_status.json（netfix.net_status.v1，监管进程 00:01 起）里 hosts 的键是**每条连接一个**："gpu33-l0"、"gpu33-l1"、"gpu33-l3"、"gpu36-l0"、"gpu36-l1"、"gpu36-l2"。键对不上，`hosts.get("gpu33")` 拿到空字典，state 回落成 "stopped"，端口 ok 回落成 False，于是 6 条全判成“断了，自动重连没在运行”。

看起来是 NETFIX 改了 net_status 的结构（每台服务器一条 ssh → 每张卡一条 ssh），infra_status 没跟上。两边都是 r39 期间的改动，没有一个测试用真实的 net_status.json 结构去跑 build()。

### 复现
1. `curl -s http://127.0.0.1:8800/api/infra/status` → 6 条 tunnels 都是 ok=false，tech 写“ssh 状态 stopped，重连 0 次”；
2. `python -c "import json;print(list(json.load(open('data/netfix/net_status.json',encoding='utf-8'))['hosts']))"` → ['gpu33-l0', 'gpu33-l1', 'gpu33-l3', 'gpu36-l0', 'gpu36-l1', 'gpu36-l2']；
3. 对每个端口 curl /system_stats → 5 个 200、18289 是 000。

## 影响
- 界面上的“网络 / 连接状态”现在会告诉项目方“全断了”，实际只断了 1 条；派单模式是“笔记本统一派图”，这个告警可能让人去做不必要的手动恢复，或者对真正断开的那一条失去警觉。没有数据被写坏，也没有闸门被绕过，所以定 **P1**，不是 P0。

## 给 UIRSI / NETFIX
1. infra_status 按 net_status 的新结构取值：按端口找所属的 host（遍历 hosts[*].ports），不要假设一台服务器只有一个 host 键。
2. 在 tests 里加一条用例：拿当前真实结构的 net_status.json（或者它的快照）喂给 build()，断言 5/6 通时接口也报 5/6。
3. net_status 的结构变了，要在 schema 字段里升版本号（现在还是 netfix.net_status.v1），让读它的代码能发现变化。
