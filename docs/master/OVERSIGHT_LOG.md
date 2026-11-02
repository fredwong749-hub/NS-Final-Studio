# OVERSIGHT_LOG（Fable 独立监督；最新在上）

只审不改。每条：谁 / 说了什么 / 实际是什么 / 证据 / 严重度 / 建议。工作树基线：sv-20261102-14（a2110ad，18:07），之后无提交，148 个文件未提交。

---

## 第 11 轮 · 11-02 21:55 快照 · NAVIA v1_guard 按 data 根判断（删 active）；CUTEDIT P1-9b prev_value / restore

### 实跑
- `pytest test_v1_v2_split_navia / test_frames_index_assetux / test_cutedit_api / test_cutedit_export`：**27 passed / 0 skipped**，real-data-guard 0。

### 1）NAVIA
| 问 | 结论 | 证据 |
|---|---|---|
| 残留 patch | ✅ 无 | `grep v1_guard.active / G.active` 全仓 = 0；`tests/test_v1_v2_split_navia.py:36-44 _client` 直接挂 `ns_api.app._v1_v2_split`（生产同一个中间件函数）+ `StaticFiles(directory=tmp data)`，TestClient 真打 /files；12 条用例覆盖：V2 primary 拦 V1 布局 / 放 V2、大小写·编码·反斜杠·`..`、legacy primary 放行、沙箱无 runs.json 不拦、runs.json 坏 → fail-closed、仓库 data 缺 runs.json → fail-closed、缓存按 data 根、gpu3-media 与 cache 出口、/v1-files 只放视频、scoped 按 data 根、video_index、v1-library |
| 三个调用点都传 data 根 | ✅ | `app.py:64 deny(path, query, P.DATA)`；`frames_index.py:29`、`video_index.py:31` `scoped(rel, data_dir=_P.DATA)` |
| NS_PROJECT_ROOT 启动时守卫生不生效 | ⚠ 不生效，但不是 V1 的口 | `v1_guard.py:31-33`：data 根 ≠ 仓库 data 且旁边没有 runs.json → `v2_prefix` 返回 None → 不拦。项目目录由 `project_ctx.PROJECT_SUBDIRS:227-229` 建（有 `config/`、`data/renders`、`data/renders_gpu3`），**不建 `config/pipeline/runs.json`**，所以带 `NS_PROJECT_ROOT=projects/<slug>` 起的 API 整条守卫是关的。但那时 `/files` 发的是 `projects/<slug>/data`——那部剧**自己的** renders/epNN，不是 series10_v1 的文件（仓库 data 不在挂载目录下，`/files/../` 被 StaticFiles 挡）；本机现在也没有任何 projects 目录、没有脚本用这个变量起 API（第 10 轮已核）。结论：不是 L-126 的新口；是"非仓库根 = 沙箱 = 不拦"这个约定的边界。P2 建议：项目目录若日后有多个版本（也建 runs.json）守卫会自动生效；或在 `v2_prefix` 对"data 根下存在 `renders/ep\d+/`（V1 布局）且没有 runs.json"打一条日志，免得静默 |
| 缓存键带 mtime 是否正确 | ✅ | `_prefix_cached:58-67`：键 = `str(data 根)`，值 = `(runs.json st_mtime_ns 或 None, 前缀)`；mtime_ns 变 → 重算；`os.replace` 写 runs.json 必变 mtime；runs.json 不存在时 mt=None 也能区分"从无到有"。仓库 data 下读不到 → `v2_prefix` 抛出发生在写缓存之前 → 不会把坏结果缓存住，每次都 fail-closed。无问题 |

### 2）CUTEDIT P1-9b
| 项 | 结论 | 证据 |
|---|---|---|
| prev_value | ✅ | `cut_project.py:465-498 commit_changes`：基线之后**别的窗口**改过同一字段 → `overrode` 存 `{field, label, prev_rev, prev_by, prev_at, prev_what, prev_value(= field_value 完整旧值), text}`；字幕是整份列表、顺序是整份序列、裁切是该镜入出点 |
| POST …/cut-project/restore | ✅ | `:557-585`：按 `history_id`（history 条目新加 `id`）找 overrode，可指定 field；order 的镜集合、trim 的镜号不在当前工程里的跳过；`commit_changes(..., always_record=True, extra={"restored_from": …})` → 恢复记成新改动、被它盖掉的当前值也进新条目的 overrode（可再恢复回去）；原条目加 `restored[]`；202 |
| client 标识 | ✅ / P2 | `CutEditor.tsx:96 CLIENT = 随机 8 位（每次加载页面一个）`，PUT 和 restore 都带（:251）；服务端 `other = prev and prev.client != client`（:477）——同窗口重发 / 连改不记"覆盖"（`test_resend_with_old_base_from_same_window_is_not_an_override`）。P2：刷新页面就换 id，自己上一次会话的改动会被当成"别人的"记进 overrode（只是多一条可恢复记录，不丢数据） |
| 恢复本身记成新改动 | ✅ | `new["what"] = "恢复被覆盖的改动：…"`，`restored_from`、`always_record`；测试 `test_restore_brings_back_overridden_subtitles` |
| 边角 | P2 | restore 时若 prev_value 与当前值相同，`commit_changes` 返回 None → 不写 history、静默 202；前端看不出"没变化"。建议回 `{"restored": false, "why": "和现在一样"}` |

### 结论
两批都达标，可进下一版。P2 三条（项目根无 runs.json 时静默不拦、刷新换 client id 的假覆盖、restore 无变化静默）记录即可。

---

## 第 10 轮 · 11-02 21:40 快照 · NAVIA P1-9a 修复里的 `v1_guard.active(P.DATA)` 开关

### 事实
- `services/api/ns_api/v1_guard.py:100-103 active(data_dir)`：`Path(data_dir).resolve() == (ROOT / "data").resolve()`，ROOT = 代码仓库根。
- `app.py:64`：`if GET/HEAD and v1_guard.active(P.DATA) and v1_guard.deny(...)`；`/files` 挂的也是 `StaticFiles(directory=P.DATA)`（:2090）。
- `P` = `ns_render.pipeline`：`pipeline.py:41-42 ROOT = Path(os.environ.get("NS_PROJECT_ROOT") or <仓库根>)`，`DATA = ROOT / "data"`。
- `v1_guard.deny` 读的 runs.json 是**代码 ROOT** 下的（:14-15），不是 P.DATA 所在根的。
- 测试：`tests/test_v1_v2_split_navia.py:43` `monkeypatch.setattr(G, "active", lambda d: True)` 后再测 deny——生产的 `active()` 本身没有被任何用例跑到，中间件路径 (:64) 也只在 active 被 patch 掉的前提下测。

### 问 1：线上有没有配置 / 环境变量能让 P.DATA 指到别处、绕过拦截
- **有，一个**：环境变量 `NS_PROJECT_ROOT`（T42 多项目：`project_ctx.py:157-161 ctx.env()` 给子进程设成 `projects/<slug>`；`bible.py:27`、`looks.py:26`、`compiler.py:53`、`framing.py:61` 同样认它）。API 进程若带着它启动：P.DATA = `projects/<slug>/data` → `active()` False → 守卫整条关掉，而 `/files` 照样发 P.DATA 下的文件。
- **今天没被触发**：`ops/restart_api.ps1`、`ops/autostart/*.ps1`、config 里都不设 `NS_PROJECT_ROOT`（grep ops/config/*.ps1/*.env = 0）；只有 `qwen_mailbox.py:339/429` 给**子进程**用 `ctx.env()`，不影响 API 自己。所以线上 :8800 现在是拦着的。
- 另一个在进程内改 `P.DATA` 的只有 `tools/ab_quality.py:48`（离线工具，不是 API）。
- 结论：开关是潜在的，不是现实的；但它是根因模式 1 的又一例——"拦不拦"看代码根，"发哪个目录"看 P.DATA，两套根。

### 问 2：能不能改成测试里也拦
- **能，而且更干净**。把判据从"P.DATA 是不是仓库 data"改成"**被发的这个 data 根**旁边有没有 runs.json、primary 是不是 legacy"：
  - `deny(path, query, data_dir)` 读 `Path(data_dir).parent / "config/pipeline/runs.json"`（和 `ns_agent.run_paths._ctx` 同一口径：沙箱 / 测试临时目录没有 runs.json → 旧行为不拦；有 → 按它判）；仓库 data 下 runs.json 读不到 → 仍按拒绝（现有 fail-closed 保留）。
  - 这样 `active()` 可以删掉；中间件路径在测试里真跑：夹具 `tmp/config/pipeline/runs.json = {"primary":"v2","legacy_unprefixed_run":"v1","runs":{...}}` + `tmp/data/renders/ep01/S1/takes/a.png`（V1 布局）+ `tmp/data/renders/v2/ep01/S1/takes/b.png`，`monkeypatch.setattr(P,"DATA",tmp/"data")`，TestClient：GET `/files/renders/ep01/...` → 404、`/files/renders/v2/...` → 200、`/files/cache/gpu3_media/renders_gpu3/...` → 404、primary=legacy 时 → 200。
  - 现有几十个 `monkeypatch.setattr(P, "DATA", tmp)` 的测试没有 runs.json → 不拦，行为不变；想测拦截的写 runs.json 即可。
  - `_prefix_cached` 的缓存键要带 data_dir（现在只按仓库 runs.json 的 mtime）。
- 顺带：`frames_index.py:28` / `video_index.py:30` 的 `v1_guard.scoped(rel)` 也读代码根的 runs.json，一起改成按 data 根。

### 严重度
P2（线上未触发；测试覆盖缺口 + 双根设计）。建议 NAVIA 按问 2 改，删掉 `active()`。

### 对 sv-16 cut 前状态
无 P0 未决。第 9 轮之后仍开着的：P1-9a（本轮确认已修，待上面 P2 收口）、P1-9b CUTEDIT 被覆盖改动无法恢复（字幕尤甚）、P1-6b 的尾巴（V1 里两份 `_derived_index.json` 待你定处置）、PROMPTFIX V1 风格后缀未交。这些不是我认为必须挡 cut 的项；是否带着 P1 发版由你定。

---

## 第 9 轮 · 11-02 21:25 快照 · VQAGATE 未测口径 / HOLLYWOOD 覆盖句 / NAVIA 整段匹配 / PROMPTFIX 守卫 / CUTEDIT 三方合并 / :8800 被停

### 实跑
- 11 个测试文件：**240 passed / 0 failed / 0 skipped**，real-data-guard 0 次（test_vqagate、test_vqa_anomaly、test_owner_gate、test_v1_v2_split_navia、test_frames_index_assetux、test_promptfix_v2、test_gen_contract、test_imgfix、test_autoflow、test_cutedit_api、test_cutedit_export）。
- `arch_scan --check`：FAIL 15 处，全部是新文件未入版 / 被引用未入版（cast_table、v1_guard、v1_library、v2_assets、api_watchdog、video_hands…）；无新增实质退化。

### 1）VQAGATE
| 项 | 结论 | 证据 |
|---|---|---|
| judge 无身份参照 → untested | ✅ | `anomaly.py:394-402`：有真人脸 + refs 未就绪 + 非 refless → `untested` 列表 + verdict clean→untested；有命中仍是 hit |
| check / count_check 当阻断 | ✅ | `anomaly.check:779` status = fail / untested / pass；`accept.count_check:176-183` 四条 untested 分支（检测器没跑成 ×2、本剧无身份脸、judge 判未测）；`accept.apply:217-229` "fail / untested 都进 blocking（Q10）"，只因基础设施的标 score_infra |
| `_ids()` 按剧 | ✅ | `anomaly.py:63-80`：资产包模式读清单 characters（id + display_name）；解析失败返回空表 + stderr 报，不退回 V1；非清单剧才 NAME_ID |
| video_hands ≥3 帧、分母只算有手帧 | ✅ | `video_hands.py:51-70`：`len(ok) < MIN_TESTED(3)` → untested；`tested = 有手的帧`；全无手 → na（不是 pass） |
| DETECT-S 夹具改动有没有放过该抓的 | ⚠ P2 | `tests/test_vqa_anomaly.py:22-32`：`face()` 默认给 A_→lin_wan 0.85、B_→chen_yu 0.85，`feat()` 默认 refs_loaded = V1 四人。改前这些用例 refs 没加载、陌生人判据整段跳过，所以没有任何用例曾真正测过"陌生人"；改后 extra_head 用例（:65-75、:114-121）用第三个 emb / 显式 sims 仍在测 ✅。**但**夹具把所有 A_/B_ 都设成"认得出"，而 judge 对"认得出、却不在本镜 cast 里的脸"没有判据（`:307-309` strangers 只看 sim < stranger_cos）——这个检测缺口是原有的，不是夹具造成的，只是夹具让它永远不会被用例暴露。建议补一条用例：B_（陈宇）入画、cast 只有林晚 → 现在是 clean，应判 extra_head（需要 judge 加"已识别但不在 cast"判据）。另：夹具 autouse 设 `NS_RUN_ID=series10_v1`，依赖 `remote_score.face_project` 认这个变量 |

### 2）HOLLYWOOD
| 项 | 结论 | 证据 |
|---|---|---|
| PLACEHOLDER_OVERRIDE 进包 | ✅ | `autoflow.py:123-125` 覆盖句 + OVERRIDE_TAG；`autoflow_agent.py:44/92` 两份 CONTENT_RULES 尾部都接上；`packet():111-112` 兜底：system+user+rules 里有"标'未提供'/标未提供"且没有 TAG → 追加。P2：`hollywood_writer.md:10`"没贴出的参数写'未提供'"这个写法不在兜底匹配词里（靠覆盖句的"事实核对类字段"语义覆盖）；CONTENT_RULES(:44) 仍保留旧句再接覆盖句，同一条规则里先说"标未提供"再说"不适用"，能用但不干净 |
| 补占位空话校验 | ✅ | `fill_check:614-620`：去空白 < FILL_MIN_CHARS=6、核心字符 ∈ TRIVIAL_FILL（无 / 暂无 / 没有 / 略 / 同上 / none…）、核心 < 2 字 → 拒。纯标点 / "无" 混不过；6 个重复字这类语义空话仍能过（无法靠规则判，P2 记录） |

### 3）NAVIA v1_guard 整段匹配
| 项 | 结论 | 证据 |
|---|---|---|
| 大小写 / 编码 / 多斜杠 / `./` / 反斜杠 | ✅ 已堵 | `v1_guard.py:66-76` `_variants`（反复 URL 解码、反斜杠、合并斜杠、算掉 ./ ../、去尾点空格、去 ::$DATA、统一小写）；实测 `/files/Renders/…`、`/files/RENDERS/…`、`%2F`、`//`、`/./`、`?src=data%2Frenders…`、`/api/assets/file?path=…`、`/api/looks/ref-image?path=…` 全部 DENY |
| **P1-9a 重新打开的口：renders_gpu3 / gpu3-media** | ⚠ | 整段匹配特意把 `renders_gpu3/` 排除（:67 注释"renders_gpu3/、myrenders/ 不算"），`/api/gpu3-media/` 直接豁免（:58）。本机 **`data/cache/gpu3_media/renders_gpu3/ep01/S1/takes/image_001.png` 等 10 个 V1 首帧缓存真实存在**，实测 `/files/cache/gpu3_media/renders_gpu3/ep01/S1/takes/image_001.png` → **allow**，`/api/gpu3-media/renders_gpu3/ep01/S1/takes/image_001.png` → allow（`app.py:1751-1766` 本地有就 FileResponse，没有就 `RD.fetch_media` 去 gpu3 镜像拉，镜像里是 V1 的 renders_gpu3/epXX）。旧正则 `renders(?:_gpu3)?/` 本来挡住这两条，这次改成整段匹配反而放开了。修法：`renders_gpu3/` 也按"非当前剧目录"判（它整个目录都是 V1 时代的）；gpu3-media 路由在自己的 400 检查之后再调 `v1_guard.deny`，或直接下线（V2 不用 gpu3 镜像） |

### 4）PROMPTFIX
| 项 | 结论 | 证据 |
|---|---|---|
| 派生图写入守卫 | ✅ | `asset_refs.py:965-968 _guard_derived_write`：runs.json 状态 ∉ WRITABLE_RUN_STATUS → raise DerivedWriteRefused；读不出 runs.json → 不许写；调用点 :697、:709（sheet_crop 两个生成分支，在 `.save(out)` 之前）、:976（record_derived）、:1717（make_board 生成前）——生成分支也守住了（第 6 轮 P1-6b 的缺口已补）。V1 里 20:22:05 写进去的两份 `_derived_index.json` 仍在，待你定处置 |
| cast_table.py | ✅ | `services/agent/ns_agent/cast_table.py`：名字→id / 女性 / 女主一张表，来源 = asset_refs.NAME_ID + 清单 register_manifest_names + asset_refs.json female/lead；`current_project` 走 `run_paths.current_run`，V2 不退回 V1；被 compiler / frame_spec / metrics import（arch_scan 显示未入版） |
| edit_project | ✅ | `edits.py:674 edit_project()`，`:689` 按当前剧取、取不到 ValueError 失败关闭（第 5 轮 P1-5a 已修） |
| V1 风格后缀去掉 | ⏳ 未查 | 它正在做；`compiler.py` 里 grep "S★ / 徕卡 / leica_sstar / style_suffix" = 0 命中，等它交了再核 |

### 5）CUTEDIT 三方合并（field_rev）
| 问 | 结论 | 证据 |
|---|---|---|
| 两边都改同一字段，被覆盖方能否从 history 恢复 | ⚠ **P1-9b 只有文字、不能一键恢复，字幕根本恢复不了** | `cut_project.py:412-416 mark_field` 记 field_rev{rev, by, at, what}；`:429-434 touch` 基线之后别人改过 → `overrode.append("…覆盖了第 N 版（谁 时间）的'what'")`，写进 history.entry.overrode（:487-491）。`what` 是人话描述：裁切 = "S5 入 0.50 / 尾裁 0.20"（数值在，可手抄回）、顺序 = "镜头顺序 S3 S1 S2"（可手抄）、**字幕 = "字幕 N 条"**（只有条数，旧文本没存）、bgm = 文件名 / 数值。没有存被覆盖的旧值本体，也没有"恢复这一版"的接口。建议 overrode 里带 `prev_value`（整个字段旧值），并给 `POST …/cut-project/restore {field, rev}` |
| 保存失败自动重发会不会重复应用 | ✅ 不会重复，但会留假"覆盖"记录 | 客户端只发与 baseRef 的差异（`CutEditor.tsx:208-236`），失败后 `pending` 留着 3 s 重发（:253-258）；服务端逐字段"值相同就不动"（:413、:421、:433 等），`what` 为空不升 rev → 幂等 ✅。P2：若第一次其实已成功只是客户端没收到，重发时 base 还是旧 rev，`touch` 会判"基线之后改过"→ history 多一条"覆盖了第 N 版（owner）"的假记录（覆盖的是自己刚存的同值） |

### 6）:8800 在 20:28:13 被直接结束——CUTEDIT / NAVIA / ASSETUX 的停进程写法会不会连带
- **能查到的事实**：`ops/logs/api_8800.{out,err}.log` 最后写入 20:28:13，最后一行是正常请求（/api/infra/status 500），无 shutdown 记录；`ops/logs/infra_watchdog.log` 11-02 20:21–20:29 只有 gpu33/36 心跳告警和 20:29:44 CLEAR，没有杀本机进程的记录；`data/ops/api_lifecycle.jsonl` **不存在**——api_watchdog 包装（`restart_api.ps1:44-45`）是 20:28 之后才加的，所以 20:17 起的那个 API 没有退出码记录。三方（CUTEDIT 20:27 匹配 sbx_server / vite-sbx-cutedit / edgecdp；NAVIA、ASSETUX 按端口 / 命令行）的实际命令**不在仓库里**（grep 全仓 .ps1/.py/.mjs/.md 无这三个词），审计日志 20:16–20:30 也没有，我只能按写法推。
- **推断（按 Windows / PowerShell 语义）**：
  1. `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'sbx_server|vite-sbx-cutedit|edgecdp' } | Stop-Process`：API 两条命令行是 `python.exe -m uvicorn ns_api.app:app --port 8800 --host 127.0.0.1`（及 20:17 起的也是 Start-Process 直接起的 python），不含这三个子串；`-match` 是正则但这三个词不含通配，不会误匹配。**连带概率低（我给 ~90% 不会）**。
  2. 父子树：`restart_api.ps1:44` 用 `Start-Process -WindowStyle Hidden` 起，父进程是那次脚本的 pwsh/explorer，不在任何 agent 的 bash 会话树下；`taskkill /T` 杀 agent 自己的 bash / node 树不会到它。`.venv\Scripts\python.exe` 是真 python 不是转发器（pyvenv 直接执行），没有额外中间层。
  3. 会连带的写法：`Stop-Process -Name python`、`Get-Process python | Stop-Process`、`taskkill /IM python.exe`（K-OPS-F30 的扫描只扫仓库文件，扫不到会话里敲的命令）；或按端口 `Get-NetTCPConnection -LocalPort 8800`（只会在明确写 8800 时命中）；`-match 'edge'` 只会碰 msedge / edgecdp，不碰 API。
  4. 20:27 → 20:28:13 的时间相关性强，但没有证据链；也可能是别的会话用了上面第 3 条的写法。
- **把握**：对"给出的三个匹配词本身不会命中 API"约 90%；对"到底是谁结束的"查不出来（无留痕）。建议：① 让三方把 20:2x 实际执行过的停进程命令原样贴到 CHANGELOG（含完整 PowerShell）；② api_watchdog 已上线，下次会有 rc；③ K-OPS-F30 的检查扩到会话层：agent 守则写明"停进程只许 `Stop-Process -Id <自己记下的 pid>`，命令原文记 CHANGELOG"。

### P1 汇总
- **P1-9a** NAVIA：整段匹配把 `renders_gpu3/` 排除 + `/api/gpu3-media/` 豁免 → 本机 10 个 V1 首帧缓存可经 `/files/cache/gpu3_media/renders_gpu3/...` 和 `/api/gpu3-media/...` 取到。
- **P1-9b** CUTEDIT：被覆盖的改动只在 history 留文字，字幕只有条数，无法恢复。

### P2
DETECT-S 夹具让"已识别但不在 cast 的脸"缺口永不暴露；CONTENT_RULES 旧句 + 覆盖句同条；"写'未提供'"变体不在兜底匹配词；重发后假"覆盖"记录；V1 里两份 _derived_index.json 待处置；arch_scan 6 个新文件被引用未入版。

---

## 第 8 轮 · 11-02 21:05 快照 · HOLLYWOOD 补占位小包 P1_fill + "未提供"两处来源冲突

### 实跑
- `pytest test_owner_gate / test_autoflow`：**41 passed / 0 skipped**（含 `test_approve_triggers_placeholder_fill`、`test_fill_check_rejects_still_placeholder_and_unknown_field`）。

### 1）P1_fill 逐项（tools/script_rsi/autoflow_agent.py）
| 问 | 结论 | 证据 |
|---|---|---|
| 逐字段比对能否被绕过（整份只改空白 / 标点） | ✅ 绕不过 | `fill_check:592-615`：`{"fields":{…}}` 走 `_set_path` 只落到指定路径、路径不存在 → "字段不存在"；交整份 → `new = d`，同样 `diff_paths(sl, new)`。`diff_paths:577-590` 是**严格相等**的叶子级 diff（多 / 少键、列表长度不同、类型不同都算该路径变了）→ 其它字段改一个空格 / 标点就进 `changed`，`:608` 判"改了不许改的字段" → 整份拒收。基准 = 正式稿文件本身（:623），不是补默认值后的模型 |
| 改"允许字段"但没真补 | ⚠ P2 | "补了"的判据只是 `x in changed`（:609）+ 重跑 `check_storyline`。把"（未提供）"改成"。"或"无"：`placeholder_hits`（storyline.py:125-130，NFKC 归一）不命中，若该字段没有最短长度规则就过。建议 fill_check 加"非空且非纯标点、长度 ≥ N 字"的字段级检查 |
| prefill 留档 | ✅ | `:657` `canon.rename(... .prefill<HHMMSS>.json)` 再写新稿；STATE 记 `placeholder_fills[{old_sha,new_sha,fields,packet}]`（:665-667） |
| STATE 改指新稿会不会顺带放过别的未评审改动 | ✅ 不会 | 出包时记 `base_sha`（:625、:634）；收稿前 `pk_prev.base_sha != base_sha` 或 fields 变了 → 重新出包不收（:633-637）；`new` 要么是 canon 深拷贝只改 allowed 字段，要么整份经严格 diff 只许 allowed 不同；STATE 只在 `rounds[-1].sha == old_sha` / `owner_direction.sha == old_sha` 时改指（:661-664）。所以新 sha 对应的内容 = 评审过的那稿 + 仅占位字段。唯一没覆盖的是上一行的"伪补" |
| 最多 3 次 → p1_fill_failed | ✅ | `FILL_MAX = 3`（:543）；第 k 稿不过且 `k >= FILL_MAX`（:645-648）→ stage escalated、`verdict="p1_fill_failed"`、`awaiting=None`、live_note 转总调度。即第 1、2 稿不过再出包，第 3 稿不过转总调度 |
| 不进三评委 | ✅ 符合设计 | 只补 SL-12 字段、评审 sha 跟着换（:661-664），不再出评审包；前提是上面"严格 diff"成立 |

### 2）"缺信息标'未提供'"两处来源冲突——实际下发的包以哪句为准
- **事实**：V2 已发的 4 份 P1 包（`writer_tasks/P1_a1…a4.json`，最新 a4 = 20:00:20）`system` 里"未提供"各出现 **4 次**，`content_rules` 里 **1 次**，`"不留占位词"` **0 次**——即新规则（`autoflow_agent.py:92 CONTENT_RULES_CLEAN` 改写）至今没进任何一份真实包；a4 的 content_rules 仍是旧句"缺信息标'未提供'"。
- **来源**（同一份 system 里）：① `autoflow.py:127` 包头原文"【项目方 11-01 好莱坞模板（原文；红线：…缺信息标"未提供"…）】"（位置 2342/15591，靠前）；② `config/prompts/hollywood_writer.md:10`"没贴出的参数写'未提供'"；③ `hollywood_writer.md:14` 红线"缺信息标'未提供'"；④ 包尾【内容边界】= CONTENT_RULES（非 clean run，`autoflow_agent.py:44` 仍是"缺信息标'未提供'"）或 CONTENT_RULES_CLEAN（clean run，现已改成"不留占位词…写成具体内容"，位置 15363，最后）。另 `autoflow.py:751` 还有一份同句。
- **以哪句为准**：没有任何机制裁决——两句同时下发，写手模型自己猜。按权重，模板那句出现 3 次、在前、还冠以"项目方原文 / 红线"；新句 1 次、在最后。实践里只能预期写手继续写"未提供"，然后被 SL-12（storyline.py:157 block）打回 → 返修循环（第 4 轮 r4-fable 就是这么发现的）。对非 clean run（第二季）更糟：CONTENT_RULES 本身还教写"未提供"，SL-12 却对所有剧生效。
- **严重度 P1**：根因模式 1"同一事实两个入口"。建议：hollywood_writer.md 是项目方原文，改不改原文由你定；系统层至少在 `autoflow.py:127` 包头加一句明确的覆盖（"本系统里缺信息不写'未提供'，按 P0/P1 写成具体内容；原文红线里的'标未提供'不适用"），并把 CONTENT_RULES（非 clean）与 `autoflow.py:751` 一起改；加一条测试：任何新出的写作包 system+content_rules 不得同时含"标'未提供'"与"不留占位词"。

### P1 汇总
- **P1-8a** 写手包里"标'未提供'"（×4，含项目方模板原文）与"不留占位词"（×1）并存，真实包尚无新句；SL-12 会把按模板写的稿一律打回。

### P2
fill_check 对"伪补"（改成标点 / 单字）无最短内容检查。

---

## 第 7 轮 · 11-02 20:50 快照 · NAVIA v1_guard / V1 库 / LoadImg；CUTEDIT 202 合并 / 重编号导出 / srt；HOLLYWOOD W-38 / W-37 / 证据核验 / SL-12 / owner_hold

### 实跑
- `pytest test_cutedit_export / test_cutedit_assemble / test_frames_index_assetux / test_v1_v2_split_navia / test_v2_assets_assetux / test_owner_gate / test_judge_agent / test_autoflow`：**70 passed / 0 failed / 0 skipped**，real-data-guard 写真实数据 0 次。W-37 两条上轮红的用例现在绿 ✅。

### 1）NAVIA
| 项 | 结论 | 证据 |
|---|---|---|
| 拦截收进统一出口 | ✅ 但有绕过 | `app.py:60-66` HTTP 中间件：GET/HEAD 且 `v1_guard.deny(path, query)` → 404；覆盖 /files、/api/thumb?src、任何查询串（`v1_guard.py:53-67` 两次 unquote、反斜杠归一）；runs.json 读不到 → 拒绝（fail-closed）。`/v1-files` 单独挂 `_V1VideoFiles`，只放 `renders/ep*/S*/takes/*.mp4|webm`（:2080-2089） |
| **P1-7a 大小写绕过** | ⚠ | `deny` 的正则区分大小写；实测 `/files/Renders/ep01/S1/takes/a.png` → allow、`/files/RENDERS/ep01/x.png` → allow、`/files/renders/ep01/...` → DENY。笔记本是 NTFS，StaticFiles 按大小写不敏感找到文件 → V1 图经改大小写的 URL 照样发出。修法：`text.lower()` 再匹配，或 `re.I` |
| /api/v1-library 只读 | ✅ | `v1_library.py` 只有一个 `@router.get`（:41）；`V1Library.tsx` 只有刷新 / 播放 / 关闭三个按钮（:30/:50/:72），无 POST、无"用这版 / 修改 / 重出"（:2 注释亦声明） |
| LoadImg.tsx | ✅ | 0.3 s 后显示"原图传输中"，失败重试 4 次（3/6/9/12 s），仍失败"文件不在"；重试用 `?r=n` 破缓存；不改任何数据 |

### 2）CUTEDIT
| 项 | 结论 | 证据 |
|---|---|---|
| 保存 202 | ✅ | `cut_project.py:400 @router.put(... status_code=202)`；原来的 409（"工程已更新到第 N 版"）已删，改为 history 里记"基于第 x 版的改动，已合并到第 y 版"（:121-122 diff） |
| **P1-7b 旧版本合并会默默覆盖别处的新改动** | ⚠ | 服务端"合并" = 只应用这次发来的字段（:405-435），不是对比客户端基线的三方合并。而网页每次保存都发**全部**视频段的入出点 + **完整**顺序 + 字幕（`CutEditor.tsx:208-213`）。场景：A 窗口（rev 3）改了 S5 的裁切 → 服务端 rev 4；B 窗口还在 rev 3，只拖了顺序，保存时把 S5 的旧裁切、旧字幕一起发回 → :413 判"值不同"→ 覆盖回旧值，202 收下，只在 history 留一句。项目方在 A 的改动就这样丢了。修法：客户端带基线 rev 的快照、服务端只应用"与基线不同"的字段；或网页只发改动字段 |
| 导出重编号 → 还原镜号 | ✅ | `cut_export.py:142 renumber_for_order`（按 order 把 index 重排成 1..n，trims / sources 按 fwd 重挂；order 与剧本镜集合不符 → ValueError）→ 合成 → `:147 relabel_timeline`（shots[].index/shot 还原剧本号，`cut_position` = 成片位置；speech 同步改 shot 与 key）→ `:155 srt_cues` 在还原之后按剧本镜号查 `start_s` ✅ 顺序正确。测试 `test_cutedit_export.py:77` 断言 `[(3,1),(1,2),(2,3)]` |
| 字幕外挂 | ✅ | `:155-157` 写 `_final/<base>.srt`，manifest 记 `"subtitles": "sidecar .srt（不烧录，L-002）"`；cut_export.py 无 drawtext / burn |
| 路径 run_paths | ✅ | `cut_export.py:113-114, 140 RP.script_path(ROOT)`；`cut_project.py:21, 47 _RP.renders_for_data` |
| 镜号还原会不会错位 | ✅ 未发现 | back 由 renumber 生成（新号→剧本号），relabel 只查 back；speech 的 key 用 `-S{pos}#`→`-S{orig}#` 字符串替换，仅当 key 为 str。潜在边角：`episode2.shots[*]` 里的 `id` 字段（"ep01-S5"）没随重编号改，若 assemble 用 id 而非 index 定位源文件会错——当前 assemble 用 index（测试通过），记为 P2 观察 |

### 3）HOLLYWOOD 第三批
| 项 | 结论 | 证据 |
|---|---|---|
| W-38 escalate_and_advance | ✅ | `autoflow.py:628-650`：先拿推进锁（最多等 60 s，拿不到报错、不写任何状态）→ 同一把锁内 `review_escalate_owner`（令牌）→ 立即 `AG.run`（source=escalate）→ finally 放锁；verdict 只由推进写，不双写 |
| W-37 _refuse_closed | ✅ 绿 | `script_autoflow.py:56-61` CLOSED = archived/frozen/paused → 409 大白话；`_spawn:65` 和 `/brief:252` 都调。P2：`/gate` 先 `act()` 落盘再 `_spawn` → 已关闭的剧 gate 记录仍会被写一次才 409 |
| p1_collect 证据核验 | ✅ | `judge_agent.py:297-300` NFKC + 引号统一 + 去空白后查子串；`:378` 不合格封顶 `EVIDENCE_FAIL_CAP=2`；`:385-388` 超过 `EVIDENCE_FAIL_MAX=3` 条整份无效、不计均分、要求重交；无证据仍记 1 分 |
| SL-12 占位词阻断 | ✅ 单一来源 | `ns_schema/storyline.py:124-157` block 级；`looks_table.py:22-33` 复用 `placeholder_hits`；judge_agent:337 只记录 |
| _p1_owner_hold 会不会成口子 | ✅ 范围收紧 | `autoflow_agent.py:539-553`：只在 P1 已 owner_direction 或 approved 时生效；`validate` 后若 **任何** block 的 rule 不在 `OWNER_HOLD_RULES={"SL-12"}` → 返回 None 走正常返修（:547）；只有"全部阻断都是 SL-12"才沿用并把问题挂进 `st.p1_owner_hold`。扩大口子只能改这个常量。风险仅剩：被 hold 的稿带着"（未提供）"进 P2——即待做的"补占位小包 + 逐字段 diff"，在它落地前 P2 包里会有占位词（P2 跟踪） |

### P1 汇总
- **P1-7a** v1_guard.deny 大小写绕过（Windows）。
- **P1-7b** cut-project 旧版本合并 = 整包覆盖，会默默丢别处的新改动。

---

## 第 6 轮 · 11-02 20:40 快照 · VQAGATE 三件 + asset_refs 20:16 改动 + FACTORY 一批

### 实跑
- `pytest tests/test_gen_contract.py`：20:3x 快照 **6 failed / 35 passed**，real-data-guard 拦下 7 次 `mkstemp → data/pipeline/runs/series10_v1/images/refboards`；20:4x FACTORY 加 `_archived()` 后复跑 **41 passed，写真实数据 0 次**。
- `pytest test_factory / test_system_version / test_vqagate / test_promptfix_v2 / test_story_runs_uirsi`：**175 passed / 0 skipped**。
- `arch_scan --check`：FAIL，**asset_refs.py silent_read 7→8**（新 `_archived()` 的 try/except）+ 未入版新文件（cast_table.py、v1_guard.py、v1_library.py、v2_assets.py、post_verify.py、golden_v2.py hard_run/nonatomic_json）。

### 1）VQAGATE
| 项 | 结论 | 证据 |
|---|---|---|
| anomaly_server 只听 127.0.0.1 | ✅ | `anomaly_server.py:136 ThreadingHTTPServer(("127.0.0.1", PORT))`；内网经 lan_proxy 只放 gpu33（文档 :12/:19） |
| 与 anomaly.py 共用一份代码 | ✅ | `:74-75` 从 `anomaly.REMOTE_SRC` 按 `"\nrefs = {}\n"` 拆成加载段 / 每请求段，拆不到 / 缺 @@RES@@ 启动即报错（:49-59）；/health 带 code_sha |
| 服务不可用 = 未测，不当通过 | ✅ | `anomaly.py _measure_http`：异常 → 每张 `{"error": …}`；`contract_check:746-747` error → status untested；`contract.py:301/309/322`：untested 进 blocking；`config/vqa.json gate.enforce=true、untested_blocks=true`。Q1d 本身按总调度决定是"只记录 na"（contract.py:707） |
| 图片是否出自有机器 | ✅ | 帧 / 图 b64 只 POST 到 host 参数（gpu36 :8893 内网）或 rssh gpu36；无外部 URL |
| Q1 per_face / wrong_faces | ✅ | `postflight.per_face_rows:79-91` 每脸 {bbox, h_ratio, as, sim, best, verdict}；`accept.identity:40-42` wrong_faces = verdict ∉ {过, 可放行, 小脸不判, 未判} |
| video_hands 8 帧 / ≥2 帧同类才不过 | ✅ | `video_hands.py:27-48` 均匀抽 n=8（跳首尾 5%）；`judge_frames:51-66` 同 code ≥ min_hits=2 → fail，1 帧只记；0 帧测成 → untested。P2：`tested` 把"没检到手"的帧也算进分母（文档说"测不到手的帧不算"），且只要 1 帧测成就能 pass——8 帧里 7 帧 error、1 帧 clean = pass，建议 tested < 3 也算 untested |
| **"没加载身份参照但画面有脸 → 未测"** | **⚠ P1-6a 没实现** | `anomaly.judge:287-289`：`refs_ready` 为 False 时 `strangers=[]`——陌生人判据**静默跳过**；`contract_check:748-751` 只看 defects，不看 `r["refs_loaded"]` → 有脸、无身份参照照样返回 **pass**。这是一条"未测当通过"。修法：`if faces and not refs_ready → status untested, reason "身份参照未加载"` |
| V1 耦合 | P2 | `anomaly.run_files:787 want = set(NAME_ID.values())`（V1 四个 id）；`accept.look_texts` 用 `RS.FACE_PROJECT`（已改按当前剧解析 ✅） |

### 2）asset_refs.py 20:16 改动（谁、是否违规）
- **谁**：工作树注释 `asset_refs.py:918 "PROMPTFIX 11-02 20:3x（总调度 20:10 ②）：派生参考图的 sha 账本"`；CHANGELOG_AGENTS.md 里 **没有** PROMPTFIX 对应条目（grep "sha 账本 / _derived_index" = 0），只有 FACTORY 20:4x 的修补说明。与 FACTORY 的说法一致：是 PROMPTFIX 加 sha 账本时带进来的。
- **做了什么**：`sheet_crop` / `make_board` 在笔记本上遇到"已有缓存但账本没登记"的派生图就 `record_derived()` 补写 `_derived_index.json`（diff :680-681、:1663-1664）；服务器侧 `_derived_on_server` 先返回 / 抛错，不会写 ✅（"服务器禁止重新生成派生参考图"这条没破）。
- **违规点**：补登记不分剧——测试解析 V1 镜头时往 **已归档的 V1 树** 写了 `data/pipeline/runs/series10_v1/images/refcrops/_derived_index.json` 和 `refboards/_derived_index.json`（两文件 mtime 20:22:05，仍在）。L-126 V1 只读冻结 → **违反**；同时让 test_gen_contract 6 条红。FACTORY 20:24 加 `_archived(project)` 守卫后不再写 ✅，但：① 只守了"缓存补登记"分支，新生成分支（sheet_crop 新裁 / make_board 新板）仍无守卫——对归档剧新生成本身就是写 V1，应在 `sheet_crop/make_board` 入口对 `_archived` 直接拒绝；② 20:22:05 写进 V1 的两个账本文件没处理（按"不删只隔离"由总调度定：移到 V1 清单的 `_quarantine/` 或保留并登记）；③ `_archived` 的 try/except 让 arch_scan silent_read 7→8。
- 严重度：**P1**（已修一半；规矩被破过一次、留下文件）。不是 P0 的原因：没有写进出图作业，服务器侧没生成。

### 3）FACTORY 一批
| 项 | 结论 | 证据 |
|---|---|---|
| export_tag 用版本库原字节 | ✅ | `system_version.py:729 git archive --format=tar <sv>`；注释 :733-734 说明 CRLF 根因 |
| .gitattributes eol=lf | ✅ | `* text=auto eol=lf`、`*.py text eol=lf`、`*.sh/.service/.env eol=lf`；.cmd/.bat/.ps1 crlf |
| post_verify 自动核对 | ✅ | `tools/factory/post_verify.py`（当前剧 face_of + sha 对清单 + 版本号）；`system_version.py:881 r["post_verify"] = post_verify(rs, h)`；测试 `test_deploy_records_post_verify`。未入版（arch_scan untracked） |
| 131 包清 advance_cmd | ✅ | 全部 writer_tasks：键 `advance_cmd` = **0** 份，`advance_cmd_removed` = 125 份（另 void 目录 2 份保留原字段作存档）；文件未删 |
| T-SR-01 事件同步 | ✅ | `tests/test_story_runs_uirsi.py:315 test_tsr01_wait_uses_completion_event`、`SR.wait(rid)` 改用完成事件；TODO_BOARD:209 仍标 ⏳ 需更新 |
| compose 按剧取剧本 | ✅ | `assemble_series.py:200 RUNS.script_path(run or RUN_ID, ROOT)` |
| runs 加载器收口两个入口 | ✅ | `spec_from_file_location(runs.py)` 只剩 `ns_agent/run_paths.py` + `tools/autopilot/runs.py` 自身（arch_scan 是扫描器）；40 处改为 `from ns_agent.run_paths import` / `ns_api.run_paths` 转调 |
| K-OPS-F30 只停自己的 pid | ✅ | 规则 `ops_factory.yaml:348-351`；`test_factory.py:849 test_k_ops_f30_no_mass_kill_by_name_or_port` 全仓扫 taskkill /IM、pkill -f、killall、Stop-Process -Name、fuser -k，只放行 ops/restart_*.ps1 |
| asset_refs `_archived()` | ✅/⚠ | 见第 2 节 |

### P1 汇总
- **P1-6a** VQAGATE："无身份参照 + 有脸 → 未测"没实现，`contract_check` 会 pass。
- **P1-6b** PROMPTFIX asset_refs 账本补登记写进归档 V1（L-126）；FACTORY 已守一半，新生成分支未守、两份已写文件待处置。

### P2
video_hands 1 帧即可 pass、tested 分母含无手帧；anomaly.run_files `want=NAME_ID`（V1）；arch_scan asset_refs silent_read +1；TODO_BOARD T-SR-01 状态未更新；/gate 对已关闭剧先写 gate 再 409。

---

## 第 5 轮 · 11-02 20:25 快照 · HOLLYWOOD P1-4a/4b/W-35/W-37 + V1→V2 带入口全面扫

### 实跑
- `pytest test_owner_gate / test_autoflow / test_judge_agent / test_story_runs_uirsi / test_script_library / test_v1_leak / test_lead_char_id`：**2 failed / 67 passed / 0 skipped**。红的两条都是 W-37 这批"测试先于代码"：`test_closed_runs_refused`（要 `SA.run_status`、`BriefBody.source_run`、frozen/paused 也 409）、`test_looks_parse_list_and_closed`（closed_check 口径变了）；`test_spawn_refuses_closed_run` 断言源码里有 `_refuse_closed(run_id, "开写或推进")`，当前 script_autoflow.py 里没有这个函数——W-37 **进行中、未完成**。
- `arch_scan --check`：FAIL 10 处，全是新文件未入版（ns_api/v1_guard.py、v1_library.py、v2_assets.py、tools/promptfix/golden_v2.py、tools/v2style/bgm_chroma_sim.py）+ golden_v2.py 的 hard_run / nonatomic_json 各 1。
- 我没有读 data/master/ 下任何文件（只看了 config/master/escalate.sha256 摘要与 .gitignore:98-99）。

### 1）HOLLYWOOD
| 项 | 结论 | 证据 |
|---|---|---|
| P1-4a 令牌授权 | ✅ | `autoflow_agent.py:258-270 _check_escalate_token`：无 --token-file → PermissionError；`config/master/escalate.sha256` 不存在 → PermissionError；sha256(令牌 strip) ≠ 摘要 → PermissionError；对上只返回摘要前 8 位。`review_escalate_owner:276-292` 仍先查 by 含"总调度"，再查令牌；审计写 token_digest8 / pid / user，**不写令牌原文**；`autoflow.py:914` 日志只记 digest8。`.gitignore:99 data/master/escalate.token`。测试 `test_owner_direction_flow:411-422` 覆盖"非总调度 / 只写 by 无令牌 / 令牌错 / 对"四支。P2：token 文件不存在时抛 FileNotFoundError 而非 PermissionError（仍拒绝，只是消息不友好）；`--token-file` 路径出现在进程命令行（本机可见，不含原文） |
| P1-4b 接手后照样评审 | ✅ | carry 已删（grep `owner_direction_carry` = 0）。`p1_gate:474` 项目方"修改"时写 `owner_took_over`；`_p1_review:357-360` took 时轮数上限不再 escalate；新稿 sha 不同 → 照常出三评委包；收分后没到门槛 → `:390-402` 自动写 owner_direction（新稿 sha、by="系统（项目方已接手，自动带评分）"、`reference_only=True`），停在 owner_direction 等项目方；approve 记 below_threshold / released_by_owner。测试 `test_owner_revise_new_draft_reviewed_reference_only:447-495` |
| W-35 读锁空/半截 | ✅ | `autoflow.py:606-620`：FileExistsError 后最多 20×10 ms 重读；FileNotFoundError（刚释放）→ 回去重抢；一直读不出 dict → `return None`（按有人持锁，不删）；只有读到 dict 且陈旧 / pid 已死才 unlink |
| W-37 拒绝归档/冻结/暂停 | ⚠ 进行中 | 现在只有 `_reject_archived:203-210`，只在 `/brief` 调（:230），只拒 `archived`；/start /repair /gate 经 `_spawn` 不查；frozen / paused 不拒。测试已写成目标口径（见"实跑"），当前红 |

### 2）V1 → V2 / 新剧 带入口清单（全仓扫）
✅ = 已切断；⚠ = 仍可能带入；标 P 级的要修。

| # | 入口 | 状态 | 证据 |
|---|---|---|---|
| 1 | 写作包（autoflow_agent.packet） | ✅ | clean_cut run 经 `v1_leak.redact` 换掉旧剧名 / 场景 / 道具，内容边界用 CONTENT_RULES_CLEAN；registry_chars/scenes 清空（`run():773`）；本轮 V2 包 grep V1 名 = 0 |
| 2 | story_runs（旧写作线） | ✅ | claude_agent 下 `_start` / `:357` 直接 409，不跑 `_worker`（registry_tables 在 `_worker:481` 里，不可达）；`story_images` 按 `_RP.current_run()` |
| 3 | 导入器 tools/import_script.py | ✅ | `--script` required 无默认（:195）；`--image-doc` 默认 None 且注明 V2 不许引旧文档；`-o` 默认 `runs.json primary` 的导入稿路径 |
| 4 | /brief 续写来源 | ✅/⚠ | `BriefBody.clean_cut=True` 默认；`_reject_archived` 拒 registry_from 含归档剧；但 frozen/paused 来源不拒（W-37 未完） |
| 5 | asset_refs 解析 | ✅ | `config/recipes/asset_refs.json series10_v2` 无 inherits，assets_manifest=assets_v2/manifest.json；`face_of:891-897` manifest 模式只读清单；`project_cfg` 只在有 inherits 时合并父项目（:68-93）；`asset_refs.py:337` 把清单 display_name/aliases 登记进 NAME_ID |
| 6 | **改图 / 导演加强 preflight（ns_api/edits.py）** | **⚠ P1-5a** | `edits.py:669 project = engines_cfg().get("project") or "series10_v1"`，`config/edit_engines.json` 里 project = **series10_v1**。V2 镜头走"改图"时，契约请求按 V1 项目做 asset_refs 槽位规划 → 带 V1 身份脸 / 设定图进 V2 改图作业。应按 shot 所在剧（`runs.current_run()` / framing_project）取 |
| 7 | **frame_spec 人物表** | **⚠ P1-5b** | `frame_spec.py:214 CHAR_IDS={"林晚":"lin_wan",…}`、`:352 WHO_IDS={"她":"lin_wan",…}`、`:649 lead = … id=="lin_wan"`；`gpu3_fields.py:21 FEMALE={"lin_wan"}`。`build_spec` 被 `ns_render/pipeline.compile_with_edits:796` 和 `prompt_snapshot:26` 调用，是 V2 编译也会走的路。V2 人物名不在表里 → `CharacterSpec(id="extra")`，"她"的视线目标 → `lin_wan`。asset_refs 的 NAME_ID 已按清单登记，frame_spec 的两张表没有（grep `CHAR_IDS.update/[` = 0）。两份人物表 = 根因模式 1 |
| 8 | VQA 打分 / 报告 | ⚠ P2 | `postflight.py:56 NAME_ID`、`:168 outer_rows(project="series10_v1")`、`:208` 按 `sims["lin_wan"]` 排脸、`:455/459`；`metrics.py:255` 默认 character "lin_wan"；`report.py:99 WHO`。`remote_score.local_faces` 已按清单（第 1 轮核过），但本地判读仍按 V1 id 取字段——V2 结果只是取不到、不会错判，但字段名写死 |
| 9 | 造型数据种子 ns_agent/looks.py | ⚠ P2 | `:29 LIN_WAN_FACE="assets/characters/lin_wan/lin_wan.png"`，`seed():227` 给 lin_wan 塞 V1 脸；`:71-79` 角色锁 / 参考表写死 V1。API 侧 grep `seed(` 无调用（只 CLI `ns_agent.looks seed`），V2 looks_dir 不会被自动种；但若有人对 V2 跑 seed 就带入 |
| 10 | Ref2VA 身份登记 preflight | ⚠ P2 | `preflight.py:84-101 registered_identity_files` 读 **V1** `data/assets/identity_refs/manifest.json`；`:305` Ref2VA 分支按它判"已登记身份图"。V2 走 Pika 不走 Ref2VA，且结果是拒绝不是带入；但 V2 若开 Ref2VA 会被 V1 清单卡死 |
| 11 | 网页资产 / 人物 / 图片 | ✅ | `assets.py:190 _RP.manifest_character_ids()` 只列清单角色；`ns_api/v1_guard.py`（新，未入版）：primary 非 legacy 时文件必须在 renders/<primary>/ 下，V1 只在 /api/v1-library；`decision_check D-V2-01` 实测只含 lead_f |
| 12 | 剧本库 | ✅ | `script_library.py:27 _DONE_STATES` 含 archived → 历史剧本 |
| 13 | CUTEDIT / compose / 装配 | ✅ | `assemble_series.py:139` 与 `:200` 都改 `RUNS.script_path(run or RUN_ID)`；`tools/cut_export.py:140 RP.script_path`；`cut_project.py:47 _RP.renders_for_data`；`tools/assemble_episode.py:119` 由 `--script` 显式传 |
| 14 | prompt_rewrite | ✅ | 纯文本改写，不读参考图（grep assets/face_of/.png = 0） |
| 15 | pause / control / producer 路径 | ✅ | 第 4 轮已核（pause_state.py、producer.Paths legacy_run_id） |
| 16 | 工具脚本 | ⚠ P2 | `tools/gen_contract/calibrate_imgfix.py:76` 写死 `runs/series10_v1/epNN/P4_epNN.md`；`look_audit / reflock_v9 / reflock_validate / imgfix_ab` 用 `RUN/ep01/P4` 常量——都是离线校准工具，不在生产链，但复用在 V2 上会读 V1 稿 |

### P1 汇总
- **P1-5a** `edits.py:669` + `config/edit_engines.json project=series10_v1`：V2 改图契约按 V1 项目规划参考（真实带入口）。
- **P1-5b** `frame_spec.CHAR_IDS / WHO_IDS`、`gpu3_fields.FEMALE` 写死 V1 人物；V2 编译经 `pipeline.compile_with_edits → build_spec` 会把"她"指到 lin_wan、V2 人物当 extra。应改成从 asset_refs.NAME_ID（已按清单登记）取，一张表。
- **W-37 未完成**：只 /brief、只 archived；/start /repair /gate 未拦；frozen/paused 未拦；测试红 2 条。

### P2
令牌文件不存在抛 FileNotFoundError；postflight/metrics/report 的 V1 id 字段；looks.seed 的 V1 种子；Ref2VA 身份登记读 V1 清单；离线校准工具写死 V1 路径；arch_scan 10 处未入版。

---

## 第 4 轮 · 11-02 20:10 快照 · HOLLYWOOD owner_direction / FACTORY sv-15（48afe13）/ 并发测试复跑

基线：sv-20261102-15 = 48afe13（19:59:30）；之后工作树 21 个文件未提交（含 owner_gate.py / autoflow_agent.py / autoflow.py / script_autoflow.py / P1Review.tsx 等 owner_direction 这批）。

### 实跑
- 9 个测试文件批跑两遍：**195 passed / 195 passed，0 failed，0 skipped**（test_owner_gate / test_autoflow / test_factory / test_system_version / test_promptfix_v2 / test_vqagate / test_looks_table / test_judge_agent / test_cutedit_assemble）。
- `test_two_processes_only_one_advances` 单跑 8 次 + 批跑 2 次 = **10/10 过**。改法：两个子进程各写 ready_i，等 go 文件同时抢锁，持锁方等 release 才放（test_owner_gate.py:301-323）——第 3 轮的偶发根因（A 放锁后 B 才起）已消除。
- `arch_scan --check`：FAIL 但只剩 **1 处**（`services/api/ns_api/script_library.py` mtime_latest 0→1，sv-15 之后的改动，不在本轮范围）。
- 进程：`tools/factory/autoflow_resident.py --interval 30`（pid 38316，19:52 起）单实例；HOLLYWOOD 的 `autoflow.py watch` 已不在；uvicorn 只剩 :8800（:8811 已停）。心跳 data/factory/autoflow_resident.json 20:08:09 runs=[series10_v2]。

### 1）HOLLYWOOD owner_direction
| 问 | 结论 | 证据 |
|---|---|---|
| 授权强度 | **P1-4a 太弱** | `autoflow_agent.py:258 review_escalate_owner`：`if "总调度" not in (by or ""): raise PermissionError` —— 任何进程 `autoflow.py review-state --escalate-owner --by 总调度` 就过；没有登录、没有凭证、不记调用方 pid/会话。`advance_log` 记了 by 文本（autoflow.py:902），但 by 本身是自报的 |
| sha 绑定 | ✅ 对那一稿成立，但被 carry 延长 | `owner_gate.owner_direction:27-39`：STATE.owner_direction.sha ≠ 当前 P1_storyline sha → None；`review_escalate_owner:268` 要求最后一轮评的 sha = 当前稿。**但**见下行 |
| "修改"后新稿不再评审 | **P1-4b 口子成立** | 项目方在 owner_direction 下点"修改"→ `p1_gate:445-449` 写 `owner_direction_carry`；下一次 `_p1_review:325-329` 把 owner_direction 的 sha 直接改成新稿 sha，`:331-339` 有 od 就 `return False/True`、**不再出评审包**。carry 没有次数上限：每次"修改"都重新 carry，一次 escalate 之后这部剧的 P1 永远不进三评委，直到"换方向"（redirect 归档 judge_p1）。文档说"只对当时那一稿有效"，实际是"对之后所有项目方改稿都有效" |
| redirect 只归档 | ✅ | `p1_gate:423-438`：P1 / report / P1_looks / judge_p1 整目录 `rename` 到 `_redirect_<时间>/`，`void_downstream` 移包，P0_brief.outline 前缀新方向；无 unlink / rmtree |
| 其它 | ⚠ | `act(redirect)` 要求 note 非空（:136-137）——"换方向"必须打字；approve 在 od 下记 `below_threshold / released_by_owner / audit`（:151-153）✅ 审计完整 |

**P1-4a 建议（授权）**：改成凭证而不是字符串。可行做法：`data/master/escalate.token`（.gitignore；总调度会话启动时生成，SHA-256 摘要写进 `config/master/escalate_token.sha256` 入版）；CLI 读文件算摘要对上才放行，并把摘要前 8 位 + pid + USERNAME 写进 STATE.owner_direction 与 autoflow.log；agent 守则（docs/AUTOPILOT.md 或各 loop 的 .md）写明"不许读 data/master/"。它挡不住恶意进程（同一用户都能读），但挡得住"顺手 --by 总调度"的误触和自动化脚本，审计也能回溯。更强的做法是把 escalate 做成网页动作、要项目方 / 总调度登录会话（`auth.user_of`），命令行只留 --dry。
**P1-4b 建议**：carry 最多 1 次（或完全不 carry）：项目方改稿后仍出评审包，分数只作参考、不拦——既保留"项目方定方向"，评审数据也不断档。

### 2）FACTORY sv-15
| 项 | 结论 | 证据 |
|---|---|---|
| pause_state.py 唯一判定 | ✅ | `tools/factory/pause_state.py`：远端执行 PAUSE_PY，run = run.json run_id，legacy → data/producer/control.json，其它 → runs/<run>/control.json；runs.json status≠producing 或 control.paused 都算已暂停；读不到 = 已暂停（保守）。`restart_queue.py:111-113`、`system_version.py:916-918` 都改调它；`test_factory.py:721 test_pause_state_real_layout` 用真实目录结构测 V1 control 不能用来判 V2 ✅。P2：剧 id 读 run.json 而不是 `runs.primary_run()`——两个入口（有注释说明同 producer.RUN_ID） |
| assemble_series 按剧取路径 | **⚠ 半改（P1-4c）** | `:139 RUNS.script_path(RUN_ID, ROOT)` ✅；**`:200 load_episode(ROOT / "data/import/script_v2.json", ep)` 仍写死 V1**——这是 `compose()`（成片 / 预览 / CUTEDIT cut_export 共用的合成入口）读的剧本。V2 装配会拿 V1 的集表配音配乐 |
| I11–I13 无 project 失败关闭 | ✅ | `preflight.py:367-368`（I11）、`:391-393`（I12/I13）：`elif not proj and kind == "image": add(..., "fail", "出图作业没有 framing_project…失败关闭")` |
| lead_f 造型只从 manifest 读 | ✅/⚠ | `looks_table.py:65-86 lead_manifest()` 从 assets_v2/manifest.json 取 LEAD_LOOKS / ADULT / DAILY / SHOES，代码不再写死 ✅；但 `closed_check:140` 和 `packet_user:170` 仍读 `assets_v2/owner_inputs.json`——造型集合仍两个来源（P2，第 1 轮 P2-8 剩一半） |
| runs.current_run 统一 | ✅/⚠ | `runs.py:85-90 current_run()`：NS_RUN 优先，其次 NS_PRIMARY_RUN / primary ✅。但 runs.py 的 `spec_from_file_location` 加载器副本从 9 份涨到 **12 份**（新增 ns_recipes/compiler、tools/import_script、tools/factory/autoflow_resident）——每多一份就多一处口径漂移点（P2） |
| autoflow_resident.py | ✅ | 单实例 `data/factory/autoflow_resident.lock` O_EXCL + 死 pid 接管（:49-66）；只推 `ADVANCE_STATUSES=("preparing","active","producing")`（:25-26、:77-83）；推进用 `autoflow.py run --source daemon`，跨进程锁在 autoflow 里（:97-99）；心跳 json；HOLLYWOOD 的会话级 watch 已停、不重复。P2：`_pid_alive` 用 `tasklist` 子进程（:40），30 s 一拍可接受 |

### 3）并发测试
✅ 10/10（见"实跑"）。不再偶发。

### P1 汇总
- **P1-4a** escalate-owner 授权只靠 `--by` 含"总调度"（建议凭证 + 审计，见上）。
- **P1-4b** owner_direction carry 无上限 → 一次 escalate 后项目方改稿永远不进三评委（与"只对那一稿有效"的说法不符）。
- **P1-4c** `tools/assemble_series.py:200` 仍写死 V1 剧本（第 1 轮 P1-4 只改了 :139 一处）。

### P2
pause_state 读 run.json 而非 runs.primary_run；looks_table closed_check / packet_user 仍读 owner_inputs.json；runs.py 加载器 12 份；"换方向"必须打字；arch_scan 剩 1 处（script_library.py mtime_latest）。

---

## 第 3 轮 · 11-02 19:45 快照 · HOLLYWOOD H2–H5 修复 + UISCRIPT 新建剧本页

### 实跑
- `pytest test_owner_gate / test_autoflow / test_ui_no_tech_words_assetux / test_story_runs_uirsi / test_judge_agent / test_l123_no_reject_ui`：**批跑 1 failed / 55 passed / 0 skipped**；失败 `test_owner_gate.py::test_two_processes_only_one_advances`，单跑 3 次全过 → **flaky**（见 P1-3b）。
- `arch_scan --check`：FAIL 22 处（untracked_code 为主；新增 `tools/factory/autoflow_resident.py` 未入版却被 test_factory import）。
- 第 2 轮三评委确由守护自动汇总：`autoflow.log` 19:42:23 `source=daemon pid=4792` → 19:42:24 verdict awaiting_writer "返修中（第 2 轮，评审 31.67/40）"；`judge_p1/r2/RESULT.json` n=3 totals [33,31,31] mean 31.67 judge_ids r2-fable/r2-opus/r2-sonnet base_sha=613ef1da…；STATE.json rounds[-1] passed=False why=["均分 31.67 < 34"] revise_attempt=3。✅

### 1）HOLLYWOOD 逐项
| 项 | 结论 | 证据 |
|---|---|---|
| 跨进程锁 | ✅ 有 | `autoflow.py:595-617 acquire_advance_lock`：O_EXCL 建 `work_epNN/advance.lock`，写 pid/source/at；陈旧（>1800 s）或 pid 已死接管；`cmd_run:624-633` 拿不到 → 记 `skipped_locked` 退出，finally unlink |
| 并发测试 | ⚠ 有但 flaky | `test_two_processes_only_one_advances` 起两个子进程各拿锁、睡 2 s；批跑时失败、单跑过——负载下 A 进程可能"拿锁-睡 2 s-释放"完才轮到 B 起来 → 两个 GOT。要用屏障（同时起跑信号 / 更长持锁）才稳；`test_advance_lock_cross_process` 单进程逻辑测试 ✅ |
| watch 扫评审 .done | ✅ | `autoflow.py pending_done:773-795`：verdict==awaiting_p1_judges 时读 STATE.rounds[-1].dir，三个 judge .done 齐才报；测试 `test_watch_detects_all_judges_done` 覆盖"少一家不报" |
| 扫描范围含 flow.py | ✅ 停用 | `flow.py:865-871 autoflow_tick` 只返回 due 不执行；旧实现改名 `_autoflow_tick_retired` 留档不调用；测试 `test_single_advance_entry_flow_tick_reports_only`。但 `test_packets_have_no_advance_cmd_and_cli_logs` 仍只扫 tools/script_rsi（P2） |
| ep_gate 走 packet() | ✅ | `autoflow_agent.py:420-423` 调 `packet(..., output_path=op)`；packet 新增 `output_path` 参数（:99、:109） |
| autoflow.log 拆分 | ✅ | `script_autoflow.py:58` 子进程 stdout 改写 `autoflow.stdout.log`；autoflow.log 仅 JSON 行（旧的首行状态 JSON 仍留在文件头，历史脏数据） |
| writer_tasks advance_cmd 清掉 | ✅ | `grep -l advance_cmd writer_tasks/*.json` = 0；void 目录两份旧包仍含该字段（存档，不被任何路径读） |
| void 写法统一 | ✅ | 文件名 `<step>_a<k>.void<HHMMSS>.json`、包内 status=voided + voided_at、`VOID_LOG.jsonl` 记 why/moved；P2 包和 19:17:58 looks 包的 VOID_LOG 没补一条（只有 19:42:23 自动 void 那条） |
| CHANGELOG 改正 | ⚠ 半改 | :648 加了"autoflow_tick 停用推进"，但 :646 原文"一次命令行 autoflow 推进…待 SCRIPTWRITER 确认"未改——时间线仍把真凶写错 |
| W-25 别的写 approved 路径 | ✅ 无 | `owner_gate.act` 是唯一外部入口（approve 时 `p1_review_ok` 否则 PermissionError → /gate 409，`script_autoflow.py:184-185`）；`set_status` 只被 p1_gate（revising/pending）和 intake_full_p4（epNN）调；`ns_api.owner_gates` / `data/sop/owner_gates.json` / orchestrator engine 的 approved 是 V1 SOP g4/g5 另一套文件；没有 `/api/gates` 路由（只有 `/api/producer/gate`，不同系统）；story_runs 不碰 owner_gates。直接手改 `<run>/owner_gates.json` 仍可（`_read` 无校验，P2） |

### 2）UISCRIPT 逐项
| 问 | 结论 | 证据 |
|---|---|---|
| 按钮显示条件 | ✅ | `P1Review.tsx:13-16 canShowP1`：只有 verdict==awaiting_owner_p1 且 latest.passed!==false 且 P1 非 revise_requested；按钮只有"用这版"（:106）"修改"（:109）；"修改"给 6 个一键选项 QUICK（:9、:89），文字可选（:96）——符合 L-123 + 一键原则 |
| clean_cut 默认 | ✅ true | `NewScriptPage.tsx:223 continueOld=false`，`:291 clean_cut: !continueOld`，勾"续写已有剧"才 false；后端 `test_brief_clean_cut_default_true` |
| /gate 的 by | ⚠ 取会话但不拒未登录 | `script_autoflow.py:183 _actor(request)` 从 `auth.user_of` 取名、不信前端 ✅；但没登录返回 "未登录" 后**照样写 approved**（:160-168 无 403）。`auth.py:9` 自己写"各闸门接口原有的检查会拒绝（403）"，这里没有；`test_p1_approve_refused_until_review_passed` 甚至以 request=None（= 未登录）成功 approve 作为通过条件。story-images pick 对 unauthenticated 是 403（test_story_runs_uirsi:287）。→ **P1-3a** |
| story_runs claude_agent 409 | ✅ | `story_runs.py:298-299`（_start）、`:357-358` 都 `raise HTTPException(409, AGENT_REFUSE)` |
| xfail 去掉 | ✅ | `test_ui_no_tech_words_assetux.py` 末尾 `test_status_ts_fully_plain` 无标记且通过；`grep -rl xfail tests/` 只剩 test_qa_laptop / test_resolution_layers / test_video_rca（旧文件，与本批无关） |

### P1
- **P1-3a /gate 未登录也能"用这版"**（上表）。建议 `_actor` 拿不到用户直接 403，测试把 request=None 的 approve 改成断言 403。
- **P1-3b 并发测试 flaky**（上表）。红了一次就会被当"偶发"忽略，等于没有覆盖。

### P2
- CHANGELOG:646 时间线未改正；`test_packets_have_no_advance_cmd_and_cli_logs` 不扫 flow.py；`pending_done` 在 p1_collect 因 base_sha 变化 / 条目不全而 n<3 时 verdict 仍 awaiting_p1_judges 且 .done 全在 → 守护每 30 s 再起一次 run（空转）；`owner_gates.json` 可手改无校验；`tools/factory/autoflow_resident.py` 新文件未入版但已被 test_factory import（arch_scan untracked_imported）；autoflow.log 文件头残留一行旧 stdout JSON。

---

## 第 2 轮 · 11-02 19:36 快照 · HOLLYWOOD 三批（A 门槛 / B 闸门守卫 / C 去 advance_cmd + watch 守护）

注意：HOLLYWOOD 在我复核期间仍在改（owner_gate.py 19:36:22、test_owner_gate.py 19:35:40、void 目录 19:30–19:33 改名），下面以 19:36 工作树为准。

### 实跑
- `pytest tests/test_owner_gate.py tests/test_autoflow.py tests/test_judge_agent.py`：**2 failed, 23 passed, 0 skipped**。失败：`test_owner_gate.py::test_gate_actions`、`test_owner_gate.py::test_no_p2_packet_before_p1_approved`，都是 `owner_gate.py:111 PermissionError: 还没有 P1 故事线`——19:36:22 新加的 W-25（"用这版"必须先过三评委）让两条老用例的 `OG.act(..., "approve")` 直接炸。报告说"测试过"，当前红。
- `arch_scan --check`：FAIL（19 处退化，比上轮 26 少；HOLLYWOOD 新文件 looks_table.py / owner_gate.py 仍是 untracked_code，入版即消）。
- 进程：`autoflow.py watch --run-dir data/pipeline/runs/series10_v2 --interval 30`（pid 14412，19:32:36 起）在跑；uvicorn :8800 与 :8811 两个 API 实例在跑；resident_sync 的 autopilot 拍在跑（`data/autopilot/flow/last_tick.json` 19:36:05，dry=false）。

### P0

**P0-H1 · HOLLYWOOD · "推进只有两个入口"不成立：autopilot 的 flow.autoflow_tick 仍是活着的第四个入口，而且它才是 19:17 事故的真凶**
- 说：（CHANGELOG_AGENTS.md:646）19:17:06 的 P2 是"一次命令行 autoflow 推进……待 SCRIPTWRITER 确认是否其 advance_cmd"；（:647、docs/hollywood/writer_agent_interface.md:37）"推进只有两个入口：网页 /repair 和 .done 守护"。
- 实际：`data/autopilot/flow/autoflow_tick.json` 记着 `"series10_v2/ep01": "P1_a1.json@1793614617"`（=19:16:57，写手建 .done 后 1 秒）——是 `tools/autopilot/flow.py:862-897 autoflow_tick` 读 writer_tasks 里 best 包的 `advance_cmd`（`flow.py:849`）并 `subprocess.run` 出来的，V2-WALK 已在 `docs/master/V2_WALK_AUDIT.md` W-23 写明。这条路现在仍在跑：`tools/autopilot/resident_sync.py:928-943 autoflow_thread → autoflow_tick_once`，`ops/logs/autoflow_tick_core.out` 19:36:05。HOLLYWOOD 既没停它，也没在时间线里认它。
- 为什么"去掉 advance_cmd"堵不住它：① `writer_tasks/P1_a2.json`（19:25:46，早于 19:31 的改动）**仍含 advance_cmd**，其 .done 19:33:36 已在；`autoflow_due` 每集只取 (attempt, mtime) 最大的包，眼下恰好是 `P1_looks_a2.json`（19:33:38，新包、无 cmd → `not x.get("cmd")` 跳过）挡在前面，一旦它被消费 / 改名，P1_a2 就成 best，autopilot 会再执行一次 P1_a2 的 advance_cmd——与 watch / 网页并发推进同一集；② `flow.py:855-858` 的 P4 分支**自己拼 cmd**（`autoflow.py run … --import dry`），根本不看包里有没有 advance_cmd，今后每个 P4 .done 都会被 autopilot 推一次。
- 根因模式 1（双入口）未关：推进入口现在是 4 个（CLI、网页 /start /repair、watch 守护、autopilot flow tick），彼此无共享锁（见 P1-H2）。
- 建议（给 HOLLYWOOD，抄 DEBUG-RSI 因为 flow.py 归 autopilot）：flow.autoflow_due/autoflow_tick 对 V2 run 关掉或改成只调 watch 的同一函数；清掉现存包里的 advance_cmd（P1_a1 / P1_a2 / void 里两份，改字段不删文件）；CHANGELOG 646 的时间线按 autoflow_tick.json 改正。

### P1

**P1-H2 · 同一集会被推进两次：三个 spawner 的"正在推进就跳过"都只在各自进程内**
- `autoflow.py cmd_watch` 用进程内 `procs` dict（diff :79-86）；`script_autoflow._procs` 是 API 进程内 dict（:27、:46-48），而 API 有两个实例（:8800 / :8811 → 两个 dict）；autopilot 用 `work_epNN/flow_tick.lock`（flow.py:873-877），watch 和网页都不看这把锁。没有任何跨进程锁文件。watch 30 s 一扫 + 项目方点 /repair（或 UISCRIPT 从 8811 点）= 两个 `autoflow.py run` 同时跑同一集，各自 `packet()` 写 `_a<k+1>`、各自改 autoflow_epNN.json。
- 建议：一把 `<run>/work_epNN/advance.lock`（O_EXCL 建文件 + 过期）放进 `autoflow.cmd_run` 入口，三个 spawner 自然共用；测试起两个进程并发 run。

**P1-H3 · A）"三家交齐后自动汇总"不自动**
- `autoflow.py pending_done`（diff :63-72）只看 `autoflow_epNN.json.awaiting.output + .done`；而 `_p1_review` 在等评委时 `st.set(verdict="awaiting_p1_judges", awaiting=None)`（autoflow_agent.py:240）。评委写 `judge_p1/r2/judge_k/out/p1_review.json.done` 不触发任何推进——第 2 轮三家交齐后要靠人点 /repair 或 CLI。现状：19:35:08 起 verdict=awaiting_p1_judges（0/3），守护不会接。
- 门槛本身 ✅ 在配置：`config/prompts/hollywood_p1_review.yaml`（min_mean 34 / min_item_mean 2.01 / max_rounds 3 / judges 3），`review_passed` 读 cfg；代码里的 `cfg.get("min_mean", 34)` 等是兜底默认值，重复了一份数字（P2）。

**P1-H4 · 测试与报告不符 + 覆盖缺口**
- 当前 2 条红（见"实跑"）。
- `test_no_p2_packet_before_p1_approved` 对失败分支（raise）和放行分支都测了 ✅；`test_packets_have_no_advance_cmd_and_cli_logs` 断言 tools/script_rsi/*.py 无 "advance_cmd" ✅，但没查 `tools/autopilot/flow.py`（它还在读 advance_cmd）；`test_pending_done_detection` 用绝对路径（`ROOT / 绝对路径` 恰好等于绝对路径）才过，生产写的是相对路径（H.RC._rel），没测到真实分支；没有任何用例测 watch 并发 / 跨进程锁 / autopilot tick 与 watch 互斥。
- `ep_gate` 的整集返修包（autoflow_agent.py:336-344）直接 `AF.write_json`，不走 `packet()`，守卫（和将来任何包级规则）管不到它——步名 revise 在白名单里所以今天不出事，但是第二个出包口。

**P1-H5 · autoflow.log 两种内容混写**
- `script_autoflow._spawn` 把子进程 stdout 重定向到 `<run>/autoflow.log`（:58-60），`advance_log` 又往同一文件 append JSON 行。现文件第 1 行是 `cmd_run` print 的整段状态 JSON，不是 advance 记录；按"每行一条推进记录"读会错。

### P2
- 19:17 时间线是否站得住：**结构上站得住**（CLEAN_CUT.json 18:45 → P2_ep01_a1 19:17:06 → owner_gates.json 19:17:57；gates 为空 = P1 从未 approved），新 `enabled()` 对 CLEAN_CUT run 一律生效后这一幕不会重演；但"是谁推的"写错了（见 P0-H1）。
- void 处置：`writer_tasks_void/P2_ep01_a1.json` 已移入（不删 ✅），但文件内仍 `status: open`、无 voided_at / 原因；另一份改名成 `P1_looks_a2.void191758_jsonbug.json`——两种隔离写法。建议统一在包里写 `status: void, voided_at, why`。
- 守护潜在空转：`post_step` 的 not_importable 分支（autoflow_agent.py:572、576）不清 `awaiting`，最后一个补丁产物的 .done 一直在 → `pending_done` 每 30 s 命中一次、每次起一个 `autoflow.py run`。现在没发生（awaiting=None），到 P4 阶段会。
- 其它出包 / 推进路径核对：`story_runs._start` 在 claude_agent 下只写 writer_package.json、不出 writer_task ✅；`story_api.ts` 只改了状态词 ✅；`script_autoflow` 的 /start /repair /gate 都经 `_spawn`（带 --source web）✅；grep `nsfs.writer_task` 只有 autoflow_agent 一个生产者 ✅。
- 第二季旧包 `series10_s2/writer_tasks/*.json` 仍带 advance_cmd（TODO_BOARD I-16 已记）——autopilot tick 对它们照样有效，第二季恢复前要先清。

---

## 第 1 轮 · 11-02 19:30–20:00（OVERSIGHT-F）

### 复核范围
FACTORY（K-OPS-F23–F26、runs.py、资产包模式、preflight I11/I12、decision_check D-V2-01/02/OPS-128、重启去暂停、story-runs 外部 API）；PROMPTFIX（K-REN-957–959、run_paths.py）；HOLLYWOOD（owner_gate / p1_gate / ep_gate / _looks_step / closed_check / script_autoflow /gate /tasks /brief /import、P1 三评委）；UISCRIPT（NewScriptPage / P1Review）；STYLE-V2（tools/v2style）。

### 实跑结果（出处）
- `pytest -q -rs` 13 个测试文件：**177 passed，0 skipped**（test_factory / test_promptfix / test_promptfix_v2 / test_v1_leak / test_system_version / test_owner_gate / test_judge_agent / test_gen_contract / test_current_run / test_looks_table / test_lead_char_id / test_autoflow / test_l123_no_reject_ui）。
- `tools/qa/decision_check.py`：69 条 ✅67 ❌0 ⏳2（D-V2-01 ✅ 只含 lead_f；D-V2-02 ⏳ pending_until IMPORTED；D-OPS-128 ✅）。注意：不带 `-X utf8` 直接跑会 UnicodeEncodeError 崩（cp1252），不是业务问题。
- `tools/qa/arch_scan.py --check`：**FAIL，26 处退化**（见 P2-13）。

### P0（立即退回）

**P0-1 · PROMPTFIX · K-REN-957 规则没写进知识库（和今天 K-REN-956 漏写同一类）**
- 说：K-REN-957–959 已加规则。
- 实际：`knowledge/rules/render_promptfix.yaml` 的 diff 只新增 K-REN-956、958、959；`grep -rn K-REN-957 knowledge/` = 0 条。代码和测试却到处引用它：`services/agent/ns_agent/asset_refs.py:1245,1267,1286,1371`、`frame_job.py:312`（rules 列表里写了 "K-REN-957"）、`framing.py:361`、`gen_contract/preflight.py:208`、`tests/test_promptfix.py:214`。
- 根因模式：规则写了不生效（知识库是规则的唯一来源，缺一条 = 下次编译审计对不上号）。
- 建议：PROMPTFIX 补 K-REN-957（背影 / 远景人物不送正脸 + 景深层次句）到 render_promptfix.yaml，check 指到 test_promptfix.py 对应用例；AUDIT 把"代码引用的 K-* 必须在 knowledge/rules 里存在"做成 arch_scan 一条。

### P1（这轮必须修，不阻断其它人）

**P1-2 · HOLLYWOOD · 19:17 前漏出的 P2 包"没被接走"，但也没作废，仍是 open**
- 问 1）P1 闸门是否真的挡住自动出 P2；漏出的 P2 包是否没被接走。
- 实际：闸门逻辑在（`autoflow_agent.chain_step` 两处 `p1_gate(...)`，`p1_gate` 在 P1 非 approved 时 return False）。V2 run 当前 `autoflow_ep01.json` verdict=awaiting_writer（三评委 27.33<34 已出 P1 第 2 稿），P2 stage 标成 held_by_p1_gate。**确实没被接走**：`writer_out/` 下没有 P2_ep01_a1.json/.done。
- 但：`data/pipeline/runs/series10_v2/writer_tasks/P2_ep01_a1.json` 仍 `status: open`（created 19:17:06，闸门 19:17:57 才 enable），它依据的 P1 已被改名为 `P1_storyline.v192546.json`（19:25 返修时）。`writer_tasks_void/` 里只有 P1_looks_a2.json，P2 没进 void。`GET /api/script-autoflow/{run}/tasks` 把它列成 answered=false 的待写包（`script_autoflow.py:139`）。若任何写手把它写回，P1 一 approve，`chain_step` 对 P1-P2 的 attempts==1 直接 `ready()` 收稿——收的是基于旧 P1 的大纲。
- 建议：HOLLYWOOD 把 P2_ep01_a1.json 移到 writer_tasks_void（不删）；p1_gate 在 revise 时顺手把下游 open 包一起 void；/tasks 对 held 的包标 held，不列为待写。

**P1-3 · FACTORY · K-OPS-F26"不解别人的暂停"读错 control 文件，V2 当 primary 时无效**
- 说：system_version.server_pause_owner / restart_queue.pre_paused 先读服务器 control，已加规则 F26 + 测试 test_a09。
- 实际：两处都写死 `data/producer/control.json`（`tools/qa/system_version.py:922`、`tools/autopilot/restart_queue.py` 新增 pre_paused `cat {rs.R}/data/producer/control.json`）。而 producer 的 control 路径按 F24 分剧：`tools/autopilot/producer.py:550` 非 legacy 剧 = `data/producer/runs/<run>/control.json`；primary 现在是 series10_v2。于是读到的是 V1（已归档）的 control，不是正在跑的主剧。`tests/test_system_version.py:376-378` 用 `_FakeRS.ctrl` 假字符串，测不到路径。另外 K-OPS-F20（`producer.py:1881`）说暂停唯一来源是 runs.json status，这两处只看 control.paused_by，又是第二个入口。
- 根因模式：同一事实两个入口；规则写了不生效。
- 建议：FACTORY 改成 `runs.producer_dir(run, root)/control.json`（经 runs.py 唯一入口），并把 runs.json status≠producing 也算"别人暂停"；测试断言路径。

**P1-4 · CUTEDIT/FACTORY · tools/assemble_series.py 一半 V2 一半 V1（L-126 漏点）**
- 实际：`tools/assemble_series.py:38-41` RUN_ID=`RUNS.primary_run()`（= series10_v2），但 `:139` 仍 `json.loads((ROOT / "data/import/script_v2.json")...)` 读 V1 导入稿；今天该文件改了 compose()（CUTEDIT 对齐）却没动这一行。V2 一旦装配，拿 V2 的 state 配 V1 的镜表。
- 建议：改为 `RUNS.script_path(RUN_ID)`；arch_scan hard_import_path 对 tools/ 也要算（它现在 138 处只是计数、不算退化）。

**P1-5 · UISCRIPT/HOLLYWOOD · 新建剧本页不传 clean_cut，/brief 默认 False → 从页面新建的剧不是"完全切割"**
- 实际：`services/api/ns_api/script_autoflow.py` BriefBody `clean_cut: bool = False`；`grep -rn clean_cut apps/web/src` = 0 条，`NewScriptPage.tsx` 的 brief body 不含该字段。series10_v2 的 CLEAN_CUT.json 是 18:45 手工放的。下一部从页面建的剧，写作包会带旧剧人物 / 场景表（`autoflow_agent.run` 只在 clean_cut 时清 rc/rs）。
- 建议：V2 起 /brief 默认 clean_cut=True（或页面显式传 true）；test_owner_gate 的 brief 用例去掉 `clean_cut=True` 参数后应仍为 clean。

### P2（记录，下轮跟）

**P2-6 · PROMPTFIX · preflight I11/I12/I13 对"没有 project 的作业"是 na（放行）**
- `preflight.py` 新增段：`proj = req.get("framing_project") or req.get("project")`；`if proj and manifest_rel(proj)` 才判，否则 `add("I11","na",...)`。`unified_frame.py:67/222` 用 `job.get("framing_project")`；`tools/poster/gen.py:72`、`tools/pipeline/image_jobs.py:263` 等走 contract_request，是否带 project 未逐一核。V2 期间"没 project"应按当前剧判，不应 na。

**P2-7 · 全体 · runs.py 的加载器复制了 9 份，口径已开始漂**
- `grep` 到 9 个文件各自 `spec_from_file_location(... tools/autopilot/runs.py)`：ns_agent/run_paths、ns_api/run_paths、gen_contract/preflight（两处）、vqa/continuity、ns_render/pipeline、tools/factory/inbox、tools/gen_contract/remote_score、tools/promptfix/compile_sha、tools/qa/arch_scan。只有 `ns_agent/run_paths._ctx` 认 `NS_RUN`；`ns_api/run_paths` 不认；`tools/qa/decision_check._current_primary` 直接读 runs.json、绕过 `NS_PRIMARY_RUN`。多剧并行时 agent 侧和 API 侧会解析到不同剧。
- 建议：一个公共 `ns_runs()` 加载器 + 一个 `current_run()`，其它全调它。

**P2-8 · HOLLYWOOD · lead_f 造型清单三个来源**
- `tools/script_rsi/looks_table.py:119-142` closed_check 读 `assets_v2/owner_inputs.json`；`asset_refs.face_of/manifest` 读 `assets_v2/manifest.json`；`looks_table.py:65-67` 还写死 `LEAD_LOOKS=("O1".."O4")`。今天三者一致（都 O1–O4 / SH1 SH2 / J1 J2），改一处就会裂。K-OPS-F23 说 V2 只认 manifest.json。

**P2-9 · HOLLYWOOD · 评审口径有一处放宽 + 状态文件被手改**
- `config/prompts/hollywood_p1_review.yaml` `require_stable: false`（注释"总调度 20:xx 口径不含 σ"），代码 `review_passed` 原本有 σ≤1 判据，现在只记录。评委独立性：三家 judge_id J1-fable / J2-opus / J3-sonnet 不同、各自目录、无证据条目记 1 分（`judge_agent.p1_collect`），均分 27.33 未过、已出 P1 第 2 稿——流程正确；但 judge_id 是自报的，没法从文件证明模型不同。
- `judge_p1/STATE.json` 里 `"packed_at": "2026-11-02T19:5x"`、`extra_fixes`/`extra_by` 是手工写入（代码只写 strftime）。手改机器状态文件以后没法区分"系统判的"和"人加的"。
- 请总调度确认 σ 放宽是你定的；建议 extra_fixes 走单独文件。

**P2-10 · 测试改动核对**
- 未发现删断言 / 改失败为跳过。`test_promptfix.py` 删了两个 `pytest.skip`（现在真跑）；`test_vqagate.test_continuity_prev_same_scene` 改为 monkeypatch 钉 V1 路径；`test_factory:212`、`test_story_runs_uirsi:289/292` 是跟着接口改断言。
- 唯一软点：`tests/test_ui_no_tech_words_assetux.py` 新增 `@pytest.mark.xfail(strict=False)` 的 `test_status_ts_fully_plain`（status.ts 还有"已打回""契约全过""Q9"），这是把没做完的事标成预期失败——要有工单跟。
- `tests/test_owner_gate.py:51-54` 闸门接线测试是源码字符串断言（`ag.count("p1_gate(...)") == 2`），不是行为测试；P1 挡 P2 的行为没有用例。

**P2-11 · HOLLYWOOD/UISCRIPT · 闸门接口和"不让项目方打字"**
- `/gate` 的 `by` 由前端传、默认"项目方"（`GateBody.by="项目方"`），P1Review.tsx 不传；写审计靠中间件。`owner_gate.act` 要求"修改"必须有一句话（`ValueError("“修改”要写一句话")`），前端按钮 disabled 直到输入。和记忆"登录即本人·一键确认、不让项目方打字"有张力——建议"修改"给点选项（选择题）+ 可选原话。
- 2）"先收下再异步"：✅ `script_autoflow.gate` 先 `_og().act()` 落盘再 `_spawn`，正在跑时只记下。

**P2-12 · FACTORY · story-runs 外部 API 修复 ✅，但其它外部写作口没按 writer_backend 挡**
- ✅ `story_runs._start` 开头 `if writer_backend()=="claude_agent": _hand_to_agent(); return`，三个调用点（:399/:555/:571）都经 `_start`；`config/llm_providers.json writer_backend="claude_agent"`。
- 仍会调外部文本 API 的：`ns_api/script_chat.py:392`（/chat/completions）、`ns_api/prompt_rewrite.py`（用途 prompt_rewrite）、`ns_api/edits.py:493 call_llm`。都不是图片（不违 K-REV-V01），但 L-109 测试期花钱。V2 页面若能到这些入口要挡。

**P2-13 · 全体 · arch_scan --check FAIL（26 处退化）**
- 14 处 untracked_code（新文件未入版，提交后消）；2 处 untracked_imported（run_paths.py 被 asset_revs/bible/compiler、assets/character_hub/cut_project 引用但没入版）。
- STYLE-V2 实打实的：`tools/v2style/camera_ab.py` def_ssh 1 / no_timeout 1 / hard_path 6；`grade_ab.py` def_ssh 1 / no_timeout 3 / hard_path 4；`voice_v2.py` hard_path 6 / nonatomic_json 1；`bgm_theme_worker.py` nonatomic_json 1；`looks.py` no_timeout 1。sv-15 发版前要清零。

**P2-14 · UISCRIPT/FACTORY · 笔记本上两个 ns_api 实例**
- 进程表：uvicorn :8800（19:25:12，正式）+ uvicorn :8811（19:26:46，`apps/web/vite.uiscript_tmp.config.ts` 指向它）。同一份代码两套进程读写同一 data/，闸门 / 任务状态可能被两边各自缓存。`producer.py serve` 两行是 py 启动器 + 子进程，不是重复。
- 建议：UISCRIPT 用完 8811 即停；FACTORY 去重脚本按端口认。

**P2-15 · FACTORY · 文档漂移**
- `tools/autopilot/runs.py:7-11` 模块注释仍写"primary 一律保持旧路径……primary 不加前缀"，与 K-OPS-F24 相反；读代码的人会按旧口径理解。
- `autoflow_ep01.json` 里 P1G 段 status=awaiting_owner、P1R 段 revise_requested 同时存在（/tasks 原样返回），网页若按 P1G 显示会误导。P1Review.tsx 的 canOwnerAct 已排除此情况，但数据本身该改。

### ✅ 核对通过（有出处）
- K-OPS-F23/F24/F25/F26 四条都在 `knowledge/rules/ops_factory.yaml` 新增段，check 指向的测试都存在且通过。
- `config/factory/hosts.json` gpu33 / gpu36 / laptop `owner_controlled: true`；`tools/factory/hosts.py owner_lane` 没道 / 认不出 = False（失败关闭）。
- producer：`adult_shot_ids` + `owner_trigger_ids` 未触发不派（diff :162-163、:247-250）；route=local_only 非自有道 raise（:172-173）。
- preflight 新增 I11（清单 sha）/ I12（道）/ I13（品牌词）；I2 在资产包模式下清单无脸 = fail，不退旧脸（`preflight.py` manifest_missing_faces、stale_face_slots 新分支）。
- `asset_refs.face_of`：manifest_rel 有值只读清单、不读 face_overrides / faces（:891-897）。
- V2 写作包无 V1 内容：P2_ep01_a1.json、P1_a2.json 里 grep 林晚|顾沉|lin_wan|gu_chen|series10_v1|阿岚 = 0。
- runs.json：primary=series10_v2（preparing）、legacy_unprefixed_run=series10_v1（archived）、assets_manifest=assets_v2/manifest.json；manifest 只有 lead_f（looks O1–O4 looks_closed=true，items SH1/SH2/J1/J2）。
- STYLE-V2 候选只用 `assets_v2/characters/lead_f/face/lead_f_face_v1.png` + `outfits/outfit_trench_coat.png`（`grade_ab.py:38-39`、`camera_ab.py:36`），`grep lin_wan|series10_v1|data/looks|identity_refs tools/v2style` = 0。但路径写死、没经 manifest sha 核对（K-OPS-F23 口径），归 P2-13 一起改。
- `tests/conftest.py` 钉 `NS_PRIMARY_RUN=series10_v1`，只对真实仓库生效（`runs.primary_run:58-60`），tmp 目录测试读自己的登记表。
- L-123：P1Review.tsx 只有"用这版 / 修改"两个按钮；`owner_gate.act` 拒绝 reject。web 其余"打回 / 驳回"字样在反馈工单（FeedbackLayer）与 V1 旧页（EditCenter / SeasonPeek），不是今天改的。

### 给总调度的问题（需你定）
1. P2-9：`require_stable: false`（σ 不拦）是不是你定的？
2. P2-11："修改"必须打一句话 vs"不让项目方打字"，按哪条？
