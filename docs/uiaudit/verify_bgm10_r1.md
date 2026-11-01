# UIAUDIT 独立复核：BGM10 r1（声音页"配乐"候选 + 一键换用 / 撤销）

复核方：UIAUDIT。日期 2026-11-01。:8800 于 08:14:58 重启（以 `data/qa/api_restart.json` 为准），新路由已加载。界面在 :5173 上测（`NS_WEB=http://127.0.0.1:5173`）。
探针只发 GET 请求。写入路径靠读代码，再加一个进程内打桩的探针来测；打桩探针不写任何真实数据，脚本在 UIAUDIT 的 scratchpad 里：`bgm_choose_probe.py`。

**结论：不通过（P0 一条：权限 / 审计漏洞）。** 界面部分通过。

## 1. 界面（声音页 → 配乐，第 2 集）

| 项 | 实测 | 判定 |
|---|---|---|
| 只列通过的候选 | 页面写"配乐候选（3 条通过自动检查）· 另有 1 条没过检查（有人声 / 静音 / 太短），不列出"，列出 r1_c2、r1_c3、r1_c4。接口 `hidden_failed` 和页面说法一致 | ✓ |
| ▶ 播的是对应的文件 | 页面上 4 个 `<audio>` 的 src 依次是 `ep02/cands/r1_c2.flac`、`r1_c3.flac`、`r1_c4.flac`、整集 `ep02.wav`，和接口里每个候选的 url 一一对应；3 个候选文件 HEAD 都返回 200（audio/x-flac） | ✓（没点播放实测声音） |
| 当前在用的标出来 | r1_c2 有"现在在用"标记，没有"用这一版"按钮；r1_c3、r1_c4 各有一个"用这一版"，悬停提示写"整集配乐换成这一条（成片下次合成时生效，可撤销）" | ✓ |
| 截图 | `apps/web/e2e/uiaudit/bgm1_BGM_ep2_a.png` | — |

P2（界面文字）：审听模型选片理由原样上屏，里面有 `energy_r=0.439`、`clap=0.324`、`vocal_rel_db=-39.2`、`p_vocal`、`longest_gap_s`、`onset_rate` 这类内部指标名。候选行里的"提示：tempo_off（实测 21.0，brief 56–70）"也是内部用语。建议改成人话，例如"贴合度高""没有人声""速度偏慢（可能是检测误判）"，原文收进"技术细节"。

## 2. 写入路径：`POST /api/music/{ep}/choose`（services/api/ns_api/bgm_api.py 第 82–112 行）

**P0：查看者 / 未登录的人都能换配乐，记成"owner"，而且查看者那次没有审计记录。**

代码第 93–102 行：

```python
who = "owner"
try:
    from ns_api.auth import audit_line, user_of
    u = user_of(request)
    if u and u.get("role") == "viewer":
        raise HTTPException(403, "查看者不能换配乐")
    who = (u or {}).get("name") or (u or {}).get("role") or "owner"
except Exception:
    audit_line = None
```

问题有两个：
- 403 是在 `try` 里面抛的，被下面的 `except Exception` 吃掉了，接着 `audit_line = None`，换用照样执行，而且不写审计。
- 没登录时 `u` 是 None，`who` 退成"owner"，换用记在项目方名下。

进程内打桩实测（`_deliver`、`_meta`、`audit_line` 全部替换，不写任何文件）：

| 身份 | HTTP 状态 | 换用被执行 | 记成谁 | 写了审计 |
|---|---|---|---|---|
| 查看者（带 x-ns-viewer-token） | **200**（应为 403） | **是** | 界面：owner | **否** |
| 未登录 | **200** | **是** | 界面：owner | 是（但身份写成 owner） |

`tests/test_bgm.py` 24 项全部通过，但没有一项测 `choose`：权限、审计、撤销都没有覆盖。

要求：
- 把 403 判断挪到 `try` 外面；
- 未登录直接 403，或者交给 AuthMiddleware 统一拦；
- 不能默认记成 owner；
- 补测试，覆盖查看者 403、未登录 403、项目方 200 且写审计、undo 换回上一条。

撤销（undo）：代码第 88–91 行读 `chosen.previous` 再换回去，没有上一条时返回 409，逻辑没问题；没有测试覆盖。

## 3. `/api/music`

- `GET /api/music?ep=1..10`：10 集全部 200；返回的是整集配乐清单（url、时长、各镜起点）。
- `GET /api/music/{1..10}/candidates`：10 集全部 200，各集候选数 1 / 3 / 2 / 4 / 1 / 3 / 3 / 1 / 2 / 2，每集 hidden_failed 都有 1 条；状态都是 delivered。

## 4. G10

`apps/web/e2e/uiaudit/r14g_detect.json`，判定文件 `r14g_regress.md`：P0 = 0，P1 = 1（F19，检测采集问题）。

第一次跑的 r13g 作废：精修页出现 G0 白屏，页面 53 s 都没出来。重跑一遍就正常了。

另记 P1：r14g 这一轮里有 8 个页面首屏要 10–14 s，包括剧本页、剧本 A/B、设置、写作对话、声音、人物、成片、精修。重启后前几分钟可能还在预热，请 DATAALIGN 看一下是不是又变慢了。

## 5. 冷启动（守候自动测）

08:14:58 重启，08:14:58.267 并发 3 个 `/api/episodes`：180 / 155 / 154 ms，都带快照头（`restart_watch.log`）。✓

---

## 复测（:8800 于 08:29:08 带 P0 修复重启后）——**通过**

**写入路径**（进程内打桩，替换了写入函数、读取函数和审计，不写任何真实数据；探针脚本 `bgm_choose_probe2.py` 在 UIAUDIT 的 scratchpad 里）：

| 身份 | 换用 | 撤销（undo） | 换用是否被执行 | 记成谁 / 审计里的用户 |
|---|---|---|---|---|
| 未登录 | **401** | **401** | 否 | — |
| 查看者 | **403** | **403** | 否 | — |
| 项目方（fredw） | 200 | 200 | 是 | `界面：fredw（owner）`，审计 user=fredw |

- 代码改动：`require_owner()` 在第 95 行先执行，没有包在 try 里，也不再默认记成 owner（bgm_api.py 第 82–90 行）。
- `tests/test_bgm.py` 现在有 32 项，全部通过。新增的 `test_choose_rejects_anonymous_and_viewer`、`test_choose_owner_writes_audit_with_real_user`、`test_choose_owner_undo` 分别覆盖：未登录和查看者被拒绝、项目方写审计时记真实用户、撤销。
- 总调度另外在线上测过一次：未登录 POST 返回 401。UIAUDIT 没有对线上发写请求。

**界面文字**（:5173，声音页 → 配乐，第 2、4、7 集，结果文件 `bgm2_detect.json`）：energy_r、clap、vocal_rel_db、p_vocal、longest_gap_s、onset_rate、tempo_off、brief、tags 这些内部名都不见了，换成了"起伏走向贴合度""听感贴合度""配乐说明""约 60 拍/分""听出来有 …""提示：起伏贴合偏弱"。✓

剩下的小问题（P2，不挡本轮）：
- 提示后面多了一个"（r）"；
- 理由里还有"target 66"这个英文词；
- 括号里的原始相关系数（0.087 / -0.119 / 0.141）还在上屏；
- 第 7 集的理由里出现"BPM"。

建议把系数收进"技术细节"，"target"改成"目标"。

---

## 复测 v2 文案（前端改动，:5173 已生效）

- `node --experimental-strip-types tools/bgm/check_plain.mts`：**remaining leftovers: 0**。
- 第 1、2、4、7、9 集配乐页（`bgm3_detect.json`）：energy_r / clap / tempo_off / brief / tags / BPM / target、"（r）"、0.xxx 这类小数，全部 0 处。✓
- **新 P2（这次改动带出来的）**：数字被删掉之后，句子留下了空位，读不通。例如：
  - "听感贴合度与最高值 相当"
  - "r1_c2 的 是 60 的 倍"
  - "速度 落在 60–74"
  - "最长空白 远好于 r1_c2 的，"
  - "由 缓升到 再回落"

  建议：要么数字整句一起删，要么把数字换成人话（"差不多""高出一截""约 1.8 倍"），不要只删数字留下空位。
- G10：`apps/web/e2e/uiaudit/r15g_detect.json`，**P0 = 0**（P1 只有 F19）。这一轮同时覆盖了 UIRSI 第 3 批和 UIPIXEL 的 UM-0508/0511。

---

## 复测 v3（:8800 于 08:50:26 重启；改为 reason_plain / flags_plain，残句整句丢掉）——**通过**

- `check_plain.mts`：问题 0。有 3 条老记录的理由回退成空，页面上显示"理由见悬停原文"。
- 配乐页抽查第 1、2、4、6、7、10 集（`bgm4_detect.json`）：

| 检查 | 结果 |
|---|---|
| 句子完整（"现在用…"理由里，没有"X 的 ，""与最高值 相当"这类数字删掉后留下的空位） | 6 集里空位命中都是 0；逐条读过，句子都通顺。例："速度每分钟约六十五拍，和说明里的六十八拍接近" |
| 内部指标名 / 小数 | 6 集全部 0 处（energy_r、clap、tempo_off、brief、BPM、target、"（r）"、0.xx 都没有） |
| 候选提示 | 都是整句人话，例如"提示：强弱起伏和说明里的走向贴得不紧""提示：测出来的速度和说明对不上（慢铺底常被测成倍速或半速，不一定真偏）" |
| 悬停原文 + "依据" | 每集都有 1 个带"依据"的悬停提示，里面是审听模型的原文（energy_r=…、clap=… 等原始数值），按设计放在悬停里，不在正文 |

- G10：`apps/web/e2e/uiaudit/r16g_detect.json`，**P0 = 0**（P1 只有 F19）。
- 上一版记的 P2（删数字留下空位）**已修**。BGM10 r1 全部检查项都通过。
