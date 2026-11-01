"""服务器常驻生产：每次推完代码后在服务器副本上重放（幂等；WORKFLOW 11-01，K-OPS-W07）。
复用 offline_20261101 的 prep.py / patch_night.py，区别：不重置 FREEZE_TS（并回按 resident_sync 记的 last_pull）、可反复跑。
  1) night.py / sync.py 副本只管本机（OFFLINE_SELF）的集；gpu36 的 remote_score.COMFY_PY 指本目录 venv
  2) data/producer/control.json：解除暂停，only = 本机负责集的镜，hold 另一台的道（gpu33 GPU2 坏卡本来就不在道表）
  3) 笔记本留下的租约作废（改到期，不删）
用法（服务器上，repo 目录）：<OFF>/venv/bin/python ops/offline/resident_prep.py gpu33|gpu36
"""
import glob
import json
import sys

SELF = sys.argv[1]
VIDEO_ONLY = "video-only" in sys.argv[2:]
OFF = "/root/work/fredw/offline_20261101"
R = OFF + "/repo"
EPS = {"gpu33": [1, 3, 5], "gpu36": [2, 4, 6, 7, 8, 9, 10]}[SELF]


def patch_night():
    p = R + "/tools/series10_video/night.py"
    s = open(p, encoding="utf-8").read()
    if "OFFLINE_SELF" in s:
        return "night 已打补丁"
    s = s.replace('DEFAULT_CTRL = {"force_eps"', 'OFFLINE_SELF = __import__("os").environ.get("OFFLINE_SELF")  # resident 补丁\nDEFAULT_CTRL = {"force_eps"', 1)
    s = s.replace('for h in ("gpu33", "gpu36"):', 'for h in ((OFFLINE_SELF,) if OFFLINE_SELF else ("gpu33", "gpu36")):')
    s = s.replace('for host in ("gpu33", "gpu36"):', 'for host in ((OFFLINE_SELF,) if OFFLINE_SELF else ("gpu33", "gpu36")):')
    s = s.replace("        for ep, ids in rs.items():\n",
                  "        for ep, ids in rs.items():\n            if OFFLINE_SELF and hosts.get(str(ep), OFFLINE_SELF) != OFFLINE_SELF:\n                continue\n", 1)
    s = s.replace("    for e, x in st[\"eps\"].items():\n",
                  "    for e, x in st[\"eps\"].items():\n        if OFFLINE_SELF and x.get(\"host\") != OFFLINE_SELF:\n            continue\n", 1)
    n = s.count("OFFLINE_SELF")
    if n < 4:            # 上游 night.py 改了结构：不写半截补丁，交人看
        raise SystemExit(f"night.py 补丁锚点只命中 {n} 处，未写入（上游结构变了，需更新 resident_prep.py）")
    open(p, "w", encoding="utf-8").write(s)
    return f"night 补丁 {n} 处"


def patch_sync_and_score():
    msgs = []
    sp = R + "/tools/series10_video/sync.py"
    t = open(sp, encoding="utf-8").read()
    if "OFFLINE_SELF" not in t:
        t = t.replace('for h in ("gpu33", "gpu36"):', 'for h in ((__import__("os").environ["OFFLINE_SELF"],) if __import__("os").environ.get("OFFLINE_SELF") else ("gpu33", "gpu36")):  # resident')
        open(sp, "w", encoding="utf-8").write(t)
        msgs.append("sync 补丁")
    if SELF == "gpu36":
        rp = R + "/tools/gen_contract/remote_score.py"
        t = open(rp, encoding="utf-8").read()
        old = 'COMFY_PY = "/root/claude-kimi-ns-studio-v1/env/comfy/bin/python"'
        if old in t:
            open(rp, "w", encoding="utf-8").write(t.replace(old, 'COMFY_PY = "/root/work/fredw/venv/bin/python"  # resident gpu36'))
            msgs.append("remote_score 补丁")
    return "；".join(msgs) or "sync/score 已打补丁"


def control():
    shots = sorted({f.split("/renders/")[1].split("/")[0] + "-" + f.split("/renders/")[1].split("/")[1]
                    for f in glob.glob(R + "/data/renders/ep*/S*/takes.json") if int(f.split("/renders/ep")[1][:2]) in EPS})
    other = ["gpu36:0", "gpu36:1", "gpu36:2"] if SELF == "gpu33" else ["gpu33:0", "gpu33:1", "gpu33:3"]
    cp = R + "/data/producer/control.json"
    try:
        c = json.load(open(cp, encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    if VIDEO_ONLY:      # 总调度 18:4x：出图由笔记本 producer 统一负责，服务器 producer 不起、控制文件保持暂停
        c.update(paused=True, paused_by="LAPTOP_IMAGES", note=f"SERVER_RESIDENT {SELF}：只跑视频（night / vidgen），出图归笔记本 producer",
                 only=shots, hold_lanes=other)
    else:
        # NETFIX 11-01（K-OPS-N04，CONSENT AUTOPILOT → NETFIX）：出图回到服务器本机派单。only / hold / paused 一律由
        # tools/netfix/dispatch.py 算：只派 config/netfix/partition.json 本机分区 ∩ data/autopilot/ready_episodes.json 的镜
        # （没准备好的集不进 only；交集空 = ["__none__"]），hold 别机的道 + laptop:0，paused 跟随笔记本全局暂停（data/netfix/laptop_ctrl.json）
        import importlib.util
        spec = importlib.util.spec_from_file_location("netfix_dispatch", R + "/tools/netfix/dispatch.py")
        D = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(D)
        lc = D.jl(R + "/data/netfix/laptop_ctrl.json", None)
        if lc is None:   # 没有笔记本快照 = 不知道全局是否暂停 → 安全侧：暂停
            lc = {"paused": True, "paused_by": "NETFIX：缺 data/netfix/laptop_ctrl.json 快照"}
        f = D.control_for(SELF, lc, D.jl(R + "/data/autopilot/ready_episodes.json", {}))
        c.update(paused_at=None, **f)
        shots, other = f["only"], f["hold_lanes"]
    json.dump(c, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n = 0
    for f in glob.glob(R + "/data/producer/leases/*.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # 服务器上 COMPUTERNAME 不存在 → 本机租约 host=None，进程没了 producer 自己判失效；只作废笔记本（有 COMPUTERNAME）留下的
        if d.get("host") and d.get("until", 0) > 0:
            d["until"] = 0
            d["note"] = "SERVER_RESIDENT：非本机进程的租约作废"
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False)
            n += 1
    return f"control only={len(shots)} 镜 hold={other}；作废租约 {n}"


if __name__ == "__main__":
    print(SELF, patch_night(), "|", patch_sync_and_score(), "|", control())
