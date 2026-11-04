# 提案：冒烟门 `eval/smoke.py run --on gpu33`（W45 SERVER-DEV，2026-11-04；**只提案，eval/ 一行未改**，总调度审后改）

项目方原话：“笔记本本来不适合做任务重的开发,gpu那2台服务器内存那么大,gpu 3090那么多卡,你不用,在这台笔记本做干嘛?”

## 现状（读 eval/smoke.py 得出）

| 门 | 采集做什么 | 重不重 | 依赖哪台 |
|---|---|---|---|
| G1 启动 | HTTP 127.0.0.1:8800 / :8870、`ps` 看常驻进程、全量 config 解析、11 个模块 import 探针 | 轻（import 探针起子进程，十几秒） | **笔记本常驻**（API、autoflow_resident、tunnel_supervisor 都在笔记本） |
| G2 输入 | import_script + episode_ready + sop_gate 提示词证据（smoke_v2 自己的目录） | 中 | 仓库 + 数据 |
| G3 角色 | 编译 / 参考图核对 | 中 | 仓库 + 数据 |
| G4 生成 | `producer.py once --run smoke_v2 --wait`（笔记本 producer → 隧道 → 服务器出图 + **经隧道打分**） | **最重**（R2/R4 都卡在打分 12–30 分钟/镜、超时） | 服务器 GPU；打分链路经隧道 |
| G5 合成 | assemble_episode（ffmpeg） | 重（CPU） | 仓库 + 产物 |
| G6 规格 | ffprobe | 轻 | 产物 |
| G7 幂等 | G2 结构重跑一遍比指纹 | 中 | 同 G2 |
| G8 无人值守 | owner_points 等读文件 | 轻 | 笔记本账本 |

## 提案：分两段跑，笔记本只留“探活”

1. **笔记本段（保留）**：G1 的 HTTP / 进程探活、G8 读账本——这两门本来就是在验“笔记本常驻是不是活着”，搬走就失去意义。耗时秒级。
2. **服务器段（搬 gpu33）**：G1 的 config 解析 + import 探针、G2、G3、G4、G5、G6、G7 在 gpu33 上跑：
   - 代码：复用 `tools/qa/remote_gates.py` 的 `stage_tree`（此刻工作树按 blob sha 增量推到 `cut_snapshots/_dev/<时间>/`，数据目录从 producer 仓库硬链），smoke 进程用独立 venv（`config/qa/remote_dev.json` remote_python）、nice 10。
   - **G4 直接在服务器本机出图 + 本机打分**（不经隧道）：这正是冒烟 R2/R4 失败的那段。前提：smoke_v2 的出图要走一条本机道（不碰 gpu33:2），且不能和生产 producer 抢同一 control.json——建议 smoke 进程用独立的 `data/producer/runs/smoke_v2/`（已是现状）+ 显式 `--lanes gpu33:3` 之类参数，由总调度定用哪条道。
   - 产物（eval/results/<时间>.json、smoke_v2 的 renders / episodes）只写在快照目录里；结果 JSON 拉回笔记本 `eval/results/`（与现在同一 schema nsfs.smoke/1，加字段 `on: "gpu33"`、每门 `elapsed_s`）。

## 需要总调度改的 eval/（草图，不是补丁）

```python
# eval/smoke.py
ap_run.add_argument("--on", default=None, help="gpu33 = G1 探活/G8 在本机，其余门在服务器快照里跑")
...
if a.on:
    RG = load("tools/qa/remote_gates.py")
    cfg = RG.load_cfg(); dev = cfg["snap_root"] + "/_dev/smoke-" + stamp
    st = RG.stage_tree(cfg, a.on, RG.worktree_tree(), dev, cfg["snap_root"] + "/_dev", RG.ignored_paths())
    sp = RG.call_op(cfg, a.on, "spawn", {"job": dev + ".job", "dest": dev, "mode": "exec",
                                        "argv": ["{PY}", "eval/smoke.py", "run", "--only", "G2,G3,G4,G5,G6,G7", "--json-out", "smoke_remote.json"]})
    RG.wait_job(cfg, a.on, dev + ".job", timeout=preset_total_s)
    remote = json.loads(RG.fetch(a.on, dev + "/smoke_remote.json"))
    facts = {**collect_local(["G1_probe", "G8"]), **remote}
```

还需要的 smoke.py 小改动：`--only`（只跑部分门）、`--json-out`（指定结果文件）、G1 拆成 `G1_probe`（HTTP/进程，留本机）和 `G1_static`（config/import，可远端）；`py()` 在 Linux 用 `sys.executable`（现已如此）；`ffprobe_bin()` 在 Linux 用 PATH 里的 ffprobe（gpu33 有）。

## 风险 / 要总调度定的

- G4 在服务器跑会占一条出图道（ep01 冲刺期很紧，W43 报过只剩 gpu33:3）——建议冲刺期仍只在笔记本跑 G1/G8 + 服务器跑 G2/G3/G5/G6/G7，G4 等道空出来再开。
- 数据口径：服务器快照里的数据是服务器 producer 的真实数据，不是笔记本的；smoke_v2 自己的目录每次隔离重建，不受影响；G8 读的账本留在笔记本。
- 评分表 eval/smoke_rubric.md 不用改（门定义不变，只是在哪跑）。
