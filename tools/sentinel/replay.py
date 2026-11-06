"""SENTINEL 回放（规则 K-OPS-S05）：拿 11-01/02 夜间日志，按分钟逐拍喂给同一套 judges + IssueStore，算出每个事件的工单首次发现时间，和“人先发现”的时间比。

  .venv/Scripts/python.exe tools/sentinel/replay.py extract   # 日志 → tests/fixtures/sentinel/replay_20261102.json（最小证据集，测试用）
  .venv/Scripts/python.exe tools/sentinel/replay.py run       # 夹具 → data/sentinel/replay_20261102.json + 打印结果表
数据源：data/producer/log.jsonl（笔记本 producer）、data/sentinel/replay_src/{gpu33,gpu36}_producer_log.jsonl.gz（服务器 producer，
fetch_replay_src.py 只读拉回）、data/netfix/supervisor.log、data/debug/lane_util.jsonl、data/netfix/conn_watch_rate.jsonl、
data/system_versions/deploy_*.json、data/netfix/override_state.json、data/autopilot/assets_ready.json、git show <sv commit>:config/vqa.json。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.sentinel import judges as J  # noqa: E402
from tools.sentinel.store import IssueStore  # noqa: E402

FIX = ROOT / "tests/fixtures/sentinel/replay_20261102.json"
OUT = ROOT / "data/sentinel/replay_20261102.json"
T = J.ts   # W-INFRA 11-06：项目时区（+09:00）读，与 judges / policy 同口径（原 fromisoformat 按本机时区，美东笔记本差 14 h）
T0, T1 = T("2026-11-01T23:30:00"), T("2026-11-02T02:35:00")

# 人先发现的时间（出处：docs/overnight/morning_20261102.md、SLO.md 派单、总调度 02:3x / 02:4x 派单原话）
HUMAN = {
    "pause_0052": ("2026-11-02T01:04:00", "项目方 01:04 指出只有一张卡在忙 → 总调度 01:04 resume（早报 01:04）"),
    "gpu36_0109": ("2026-11-02T01:15:00", "总调度 01:1x–01:2x 亲查 gpu36 交还后两边都不派（早报）"),
    "score_backlog": ("2026-11-02T01:04:00", "总调度 01:04 查出打分 506–1483 s、积压闸顶满（早报 01:04 第②层）"),
    "port8870": ("2026-11-02T01:50:00", "总调度 01:5x 发现 :8870 被 13 小时前旧 server.py 占着（早报 01:5x）"),
    "refs_0124": ("2026-11-02T01:32:00", "FACTORY 01:32 实测 47/50 镜身份脸解析错（早报 01:32 P0）"),
    "vqa_redeploy": ("2026-11-02T02:00:00", "总调度 02:00 发现 sv-03 重推把 vqa.json 还原为 1（早报 01:5x 段）"),
    "gpu33_0222": ("2026-11-02T02:22:00", "项目方 02:22 指出 gpu33 全卡 0%（总调度 02:4x 派单：根因 77 个首帧等总调度定）"),
    "base_0224": ("2026-11-02T02:24:00", "02:24 底座隧道断（派单清单）"),
    "gaze_miss": ("2026-11-02T01:35:00", "总调度 01:3x 目检发现 s20261304 顾沉看镜头（早报 01:32 段）"),
}
# 探针缺口：人先发现、当时还没有能抓它的指标（回放不判提前量，指标落地后补进 EV 表与夹具）
GAPS = {
    "composite_look": ("2026-11-02T03:3x", "项目方先发现：首帧人物和背景不融合、像抠图贴上去", "S8 合成感：等 IMGFIX 确定性指标 + VLM 判定题、VQAGATE 接进契约后，填 sentinel.yaml S8 composite_max 生效"),
}


# ================================================================== extract
def _jl(p: Path):
    for ln in (gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else p.open(encoding="utf-8")):
        try:
            yield json.loads(ln)
        except ValueError:  # arch-ok: 坏行跳过
            continue


def _git_vqa_instances(commit: str) -> int | None:
    """发版 commit 里 config/vqa.json 的 model.instances（运行期真正起作用的那一项；整文件 sha 会被后来的注释改动干扰）"""
    r = subprocess.run(["git", "show", f"{commit}:config/vqa.json"], cwd=str(ROOT), capture_output=True, timeout=30)
    try:
        return int(json.loads(r.stdout.decode("utf-8"))["model"]["instances"]) if r.returncode == 0 else None
    except (ValueError, KeyError, TypeError):  # arch-ok: 取不到 = None（回放该部署不参与比较）
        return None


def extract() -> dict:
    keep = {"pause", "resume", "dispatch", "rendered", "redo_fail", "score_backlog", "start", "master_reject", "passed", "content_fail",
            "redo_auto_approved", "infra_error"}
    logs = {}
    srcs = {"laptop": ROOT / "data/producer/log.jsonl", "gpu33": ROOT / "data/sentinel/replay_src/gpu33_producer_log.jsonl.gz",
            "gpu36": ROOT / "data/sentinel/replay_src/gpu36_producer_log.jsonl.gz"}
    for k, p in srcs.items():
        logs[k] = [{x: d.get(x) for x in ("t", "ev", "obj", "lane", "contract_s", "by", "note", "reason_kind") if d.get(x) is not None}
                   for d in _jl(p) if T0 - 3600 <= d.get("t", 0) <= T1 and d.get("ev") in keep]
    sup = []
    for ln in (ROOT / "data/netfix/supervisor.log").read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\S+) (PROBE fail|PROBE slow but ssh moving data|KILL|UP|EXIT|SPAWN|RELAY|BASE banner slow but alive) (\S+)", ln)
        if m and T0 <= T(m.group(1)) <= T1:
            sup.append({"t": T(m.group(1)), "kind": m.group(2), "host": m.group(3), "line": ln[20:140]})
    lane = [json.loads(x) for x in (ROOT / "data/debug/lane_util.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rate = [json.loads(x) for x in (ROOT / "data/netfix/conn_watch_rate.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    deploys = []
    for p in sorted((ROOT / "data/system_versions").glob("deploy_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for h, r in (d.get("hosts") or {}).items():
            if r.get("ok") and r.get("at"):
                deploys.append({"id": d["id"], "commit": d["commit"], "host": h, "at": r["at"],
                                "vqa_instances": _git_vqa_instances(d["commit"])})
    fix = {
        "logs": logs, "supervisor": sup, "lane_util": lane, "relay_rate": rate, "deploys": deploys,
        # 笔记本 vqa.json：01:49:38 起 model.instances=4（L-100，总调度改；instances_note 原文“gpu36 GPU2 vLLM 并发 4”），文件 02:34 又改过注释，值仍为 4
        "laptop_vqa": {"instances": 4, "since": "2026-11-02T01:49:38"},
        "override": json.loads((ROOT / "data/netfix/override_state.json").read_text(encoding="utf-8")),
        # 01:24 交还时 assets_ready 的样子：WORKFLOW 01:19 push_required 自写 ready=true，无 FACTORY verify（corrected_* / preflight_* 是 01:26 之后补的）
        "assets_ready_0124": {h: {k: v for k, v in r.items() if k in ("ready", "at", "sent", "missing", "checked", "by", "pushed")}
                              for h, r in json.loads((ROOT / "data/autopilot/assets_ready.json").read_text(encoding="utf-8")).items()},
        "gaze_case": {"path": "data/ab/imgfix/ep02-S4/ep02-S4_SLV_s20261304_raw_post.png",
                      "created": datetime.fromtimestamp((ROOT / "data/ab/imgfix/ep02-S4/ep02-S4_SLV_s20261304_raw_post.png").stat().st_mtime).isoformat(timespec="seconds"),
                      # 11-02 02:5x 用 probes.vlm_judge（= gaze_regression.judge，本地看图 + MediaPipe + 裁脸复判）实测；同镜对照 s20261404 判“不看”
                      "verdict": {"eye_contact": True, "evidence": {"s": "defect", "e": "拿不准带裁脸复判：1 张脸看镜头（MediaPipe 分数在 0.05–0.1）"},
                                  "control_s20261404": False}},
    }
    FIX.parent.mkdir(parents=True, exist_ok=True)
    tmpf = FIX.with_suffix(".tmp")
    tmpf.write_text(json.dumps(fix, ensure_ascii=False), encoding="utf-8")
    tmpf.replace(FIX)
    return fix


# ================================================================== run
def cfgs() -> dict:
    from tools.autopilot import policy
    return {k: v["value"] for k, v in policy.load()["sentinel"].items()}


def lane_samples(evs: list[dict], host: str, gpus: list[int], t: float) -> list[float]:
    """按 dispatch → rendered 重建每条道在 t 时刻是否在跑（在跑 = 100，空 = 0；单张上限 15 分钟）"""
    out = []
    for g in gpus:
        ln = f"{host}:{g}"
        busy = 0
        last_d = max((e["t"] for e in evs if e.get("lane") == ln and e["ev"] == "dispatch" and e["t"] <= t), default=None)
        if last_d is not None:
            done = min((e["t"] for e in evs if e.get("lane") == ln and e["ev"] in ("rendered", "infra_error") and last_d <= e["t"]), default=None)
            busy = 100 if (done is None or done > t) and t - last_d < 900 else 0
        out.append(busy)
    return out


def run(fix: dict | None = None) -> dict:
    fix = fix or json.loads(FIX.read_text(encoding="utf-8"))
    C = cfgs()
    from tools.autopilot import policy
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_replay_"))
    store = IssueStore(tmp)
    owners = {s: C[k].get("owner_loop", "总调度") for s, k in {
        "S1": "S1_lane_util_min", "S2": "S2_gpu_all_idle_s", "S3": "S3_score_p50_s", "S4": "S4_recover_s", "S5": "S5_release",
        "S6": "S6_config_parity", "S7": "S7_pause_max_s", "S13": "S13_human_wait"}.items()}
    L = fix["logs"]
    allev = {k: sorted(v, key=lambda e: e["t"]) for k, v in L.items()}
    hist = {"gpu33": [], "gpu36": []}
    gpus = {"gpu33": [0, 1, 3], "gpu36": [0, 1]}
    waits = {"gpu33": {}, "gpu36": {}}
    redo_n = {"gpu33": {}, "gpu36": {}}
    ov = fix["override"]["hosts"]
    t = T0
    while t <= T1:
        F = []
        # ---- S7 暂停（笔记本 control 由 pause / resume 事件重建；判定 = policy.pause_decision）
        ctrl = {"paused": False}
        for e in allev["laptop"]:
            if e["t"] > t:
                break
            if e["ev"] == "pause":
                ctrl = {"paused": True, "paused_by": e.get("by"), "paused_at": J.iso(e["t"]),
                        "reason_kind": e.get("reason_kind")}
            elif e["ev"] == "resume":
                ctrl = {"paused": False}
        F += J.j_pause("laptop", ctrl, t, policy.pause_decision)
        # ---- S2 GPU 全空（每台：笔记本 + 服务器两边派的单合起来算道是否在跑）
        for h in ("gpu33", "gpu36"):
            evs = [e for k in ("laptop", h) for e in allev[k] if e["t"] <= t]
            hist[h].append((t, lane_samples(evs, h, gpus[h], t)))
            recent = [e for e in evs if e["ev"] == "dispatch" and t - e["t"] < 600]
            ready = {"server": sum(1 for e in recent if e in allev[h]),
                     "laptop_partition": sum(1 for e in allev["laptop"] if e["ev"] == "dispatch" and t - 600 < e["t"] <= t)}
            F += J.j_gpu_idle(h, hist[h][-30:], ready, ctrl["paused"], t, C["S2_gpu_all_idle_s"])
        # ---- S3 打分 p50 / 积压闸
        for k in ("laptop", "gpu33", "gpu36"):
            s = [(e["t"], float(e["contract_s"])) for e in allev[k] if e.get("contract_s") is not None and e["t"] <= t]
            b = [e["t"] for e in allev[k] if e["ev"] == "score_backlog" and e["t"] <= t]
            F += J.j_score(k, s, b, t, C["S3_score_p50_s"])
        # ---- S1 出图道利用率（lane_util.jsonl，只用 30 分钟窗口那几条）
        for rec in fix["lane_util"]:
            if rec.get("window_min") == 30 and abs(T(rec["at"]) - t) < 30:
                F += J.j_lane_util(rec, C["S1_lane_util_min"])
        # ---- S4 连接：supervisor.log 重建每条隧道断开时刻
        down = {}
        for e in fix["supervisor"]:
            if e["t"] > t:
                break
            if e["kind"] in ("PROBE fail", "PROBE slow but ssh moving data", "KILL", "EXIT"):
                down.setdefault(e["host"], e["t"])
            elif e["kind"] == "UP":
                down.pop(e["host"], None)
        ports = {h: {"ok": h not in down, "down_since": down.get(h)} for h in {e["host"] for e in fix["supervisor"] if e["t"] <= t}}
        F += J.j_ports(ports, t, C["S4_recover_s"])
        for r in fix["relay_rate"]:
            if 0 <= t - T(r["at"]) < 60:
                F += J.j_relay_rate(r["per_hour"], r["at"], C["S4_recover_s"])
        # ---- S6 配置一致：服务器 vqa.json = 最近一次部署的 sv commit 版本；笔记本 = 工作区（since 起）
        lap = f"instances={fix['laptop_vqa']['instances']}" if t >= T(fix["laptop_vqa"]["since"]) else None
        for h in ("gpu33", "gpu36"):
            dep = [d for d in fix["deploys"] if d["host"] == h and T(d["at"]) <= t]
            if dep and lap:
                F += J.j_parity(h, {"config/vqa.json": lap}, {"config/vqa.json": f"instances={dep[-1]['vqa_instances']}"}, ["config/vqa.json"])
            # 交还条件（policy.handback_ok）：01:24:31 交还时的 assets_ready
            since = (ov.get(h) or {}).get("since")
            if since and T(since) <= t < T("2026-11-02T01:36:08"):
                rec = fix["assets_ready_0124"].get(h)
                F += J.j_handback(h, "server", rec, policy.handback_ok(rec))
        # ---- S13 等人决定：服务器日志第 2 次 redo_fail = 进入“驳回重出 2 次都没换上，等总调度定”
        for h in ("gpu33", "gpu36"):
            for e in allev[h]:
                if e["ev"] == "redo_fail" and t - 60 < e["t"] <= t:
                    redo_n[h][e["obj"]] = redo_n[h].get(e["obj"], 0) + 1
                    if redo_n[h][e["obj"]] == 2:
                        waits[h][e["obj"]] = (e["t"], "驳回重出 2 次都没换上，等总调度定")
            F += J.j_human_wait(h, waits[h], t, C["S13_human_wait"])
        store.apply(F, t, owners)
        t += 60
    rows = [json.loads(x) for x in store.log.read_text(encoding="utf-8").splitlines()] if store.log.exists() else []
    opens: dict[str, list] = {}
    for r in rows:
        if r["status"] == "open":
            opens.setdefault(r["key"], []).append(r)
    first = {k: v[0] for k, v in opens.items()}
    # 事件 → 抓它的工单 key（取最早一张）
    EV = {
        "pause_0052": ["S7:laptop"],
        "gpu36_0109": ["S2:gpu36"],
        "score_backlog": ["S3:p50:laptop", "S3:backlog:gpu33", "S3:backlog:gpu36"],
        "port8870": ["S1:gpu33:0", "S1:gpu33:1", "S1:gpu33:3", "S1:gpu36:0", "S1:gpu36:1", "S3:backlog:gpu33", "S3:backlog:gpu36"],
        "refs_0124": ["S6:handback:gpu33", "S6:handback:gpu36"],
        "vqa_redeploy": ["S6:gpu33:config/vqa.json", "S6:gpu36:config/vqa.json"],
        "gpu33_0222": ["S13:wait:gpu33", "S2:gpu33"],
        "base_0224": ["S4:port:base", "S4:port:gpu33-l0", "S4:port:gpu36-l0"],
    }
    res = {}
    for ev, keys in EV.items():
        hum = T(HUMAN[ev][0])
        win0 = {"pause_0052": "2026-11-02T00:50", "gpu36_0109": "2026-11-02T01:04", "score_backlog": "2026-11-01T23:30",
                "port8870": "2026-11-02T01:20", "refs_0124": "2026-11-02T01:20", "vqa_redeploy": "2026-11-02T01:50",
                "gpu33_0222": "2026-11-02T01:20", "base_0224": "2026-11-02T02:15"}[ev]
        hits = [r for k in keys for r in opens.get(k, []) if T(r["first_seen"]) >= T(win0)]
        hit = min(hits, key=lambda r: r["first_seen"]) if hits else None
        res[ev] = {"human": HUMAN[ev][0], "human_src": HUMAN[ev][1], "key": hit["key"] if hit else None,
                   "first_seen": hit["first_seen"] if hit else None, "title": hit["title"] if hit else None,
                   "lead_min": round((hum - T(hit["first_seen"])) / 60, 1) if hit else None}
    g = fix["gaze_case"]
    if g.get("verdict"):
        det = T(g["created"]) + C["S8_vlm_sample"]["every_s"]
        res["gaze_miss"] = {"human": HUMAN["gaze_miss"][0], "human_src": HUMAN["gaze_miss"][1], "key": "S8:ep02-S4",
                            "first_seen": J.iso(det),
                            "title": f"抽检判定 eye_contact={g['verdict'].get('eye_contact')}（{(g['verdict'].get('evidence') or {}).get('e', '')}）",
                            "lead_min": round((T(HUMAN['gaze_miss'][0]) - det) / 60, 1) if g["verdict"].get("eye_contact") else None,
                            "note": "最坏情况：出图后一个抽检周期（6 分钟）才抽到"}
    out = {"at": datetime.now().isoformat(timespec="seconds"), "tickets": len(first), "events": res,
           "gaps": {k: {"human": h, "what": w, "plan": p} for k, (h, w, p) in GAPS.items()}}
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = (argv or sys.argv[1:] or ["run"])[0]
    if cmd == "extract":
        extract()
        print(FIX)
        return 0
    r = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmpf = OUT.with_suffix(".tmp")
    tmpf.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    tmpf.replace(OUT)
    print("| 事件 | 人发现 | 探针工单 | 首次发现 | 提前（分钟） |\n|---|---|---|---|---|")
    for k, v in r["events"].items():
        print(f"| {k} | {v['human'][11:16]} | {v['key']} | {(v['first_seen'] or '—')[11:19]} | {v['lead_min']} |")
    for k, g in r.get("gaps", {}).items():
        print(f"| {k}（探针缺口） | {g['human'][11:16]} | — | 未覆盖 | {g['plan']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
