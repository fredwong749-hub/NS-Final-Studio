"""VIDEO-RCA：按问题类目算发生率（现行版 / 全部尝试 / 按配方），数字全部来自生产打分文件，不另测。

来源：data/pipeline/runs/series10_v1/video/state_gpu33.json、state_gpu36.json（renders + superseded，score 字段 = score_clip.py 输出）；
看镜头：data/acting/gaze_labels.json（总调度人工标签，clip: 前缀 = 片头，img: = 首帧）。
“现行版” = 每镜 chosen 那一版（state.shots[sid].chosen）。

    .venv/Scripts/python.exe tools/video_rca/rates.py [--json out.json] [--exp data/ab/video_rca/<exp>/results.json]
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VID = ROOT / "data/pipeline/runs/series10_v1/video"
SIZE_IDX = {"极近特写": 0, "大特写": 0, "特写": 1, "近景": 2, "中近景": 2, "中景": 3, "中全景": 4, "全身": 5, "全景": 5, "远景": 6}
BANDS = [0.45, 0.27, 0.17, 0.115, 0.095, 0.05]


def size_class(h):
    return next((i for i, b in enumerate(BANDS) if h >= b), len(BANDS))


def classes(s: dict, people: int = 1) -> dict:
    """单条打分 → {类目: True/False/None(未测)}"""
    v6, v7 = s.get("v6") or {}, s.get("v7") or {}
    ids = [it for it in (s.get("identity") or {}).values() if it]
    want = SIZE_IDX.get(s.get("size_wanted") or "")
    fh = s.get("face_h_med")
    hands = v6.get("hands_max")
    people = v6.get("people") or people
    out = {
        "动作不足/站桩(mean<0.5)": None if s.get("mean") is None else s["mean"] < 0.5,
        "开场定格(head_s>0.5)": None if s.get("head_s") is None else s["head_s"] > 0.5,
        "结尾定住(tail_s>0.5)": None if s.get("tail_s") is None else s["tail_s"] > 0.5,
        "4帧一顿(J4>=1.2且z>=3)": None if s.get("J4") is None else (s["J4"] >= 1.2 and (s.get("J4_z") or 0) >= 3),
        "镜内硬切": None if s.get("cuts") is None else len(s["cuts"]) > 0,
        "身份漂移(p10<0.5)": None if not ids else any((it.get("sface_p10") or 0) < 0.5 for it in ids),
        "多手(hands_max>2×人数)": None if hands is None else hands > 2 * people,
        "坏手指(bad_finger>0.2)": None if v6.get("bad_finger_frac") is None else v6["bad_finger_frac"] > 0.2,
        "分身(dup_side>0.1)": None if v6.get("dup_side_frac") is None else v6["dup_side_frac"] > 0.1,
        "脸部泛红(cheek_red>0.25)": None if s.get("cheek_red_max") is None else s["cheek_red_max"] > 0.25,
        "景别退档(差≥1档)": None if (want is None or fh is None) else abs(size_class(fh) - want) >= 1,
        "发色漂移(dS或dV>25)": None if s.get("hair_dS") is None else max(abs(s["hair_dS"]), abs(s.get("hair_dV") or 0)) > 25,
        "口型(V7不过)": {"不通过": True, "通过": False}.get(v7.get("status")),
    }
    return out


def load_renders(with_superseded: bool = False):
    rows = []
    for h in ("gpu33", "gpu36"):
        p = VID / f"state_{h}.json"
        if not p.exists():
            continue
        st = json.loads(p.read_text(encoding="utf-8"))
        for sid, r in st["shots"].items():
            for x in (r.get("renders") or []) + ((r.get("superseded") or []) if with_superseded else []):
                if x.get("score") and not x["score"].get("error"):
                    rows.append({"shot": sid, "variant": x["variant"], "recipe": x["recipe"], "score": x["score"],
                                 "current": r.get("chosen") == x["variant"] and r.get("status") in ("done", "best_effort"),
                                 "first_frame": x.get("first_frame")})
    return rows


def gaze_rates():
    lab = json.loads((ROOT / "data/acting/gaze_labels.json").read_text(encoding="utf-8"))
    clips = {k[5:-4]: v for k, v in lab.items() if k.startswith("clip:")}
    stare = {k: v in ("开头看镜头", "开头定格+看镜头") for k, v in clips.items() if v != "看不清"}
    rows = {}
    for r in load_renders(with_superseded=True):      # 人工标签打在当时的版本上（含后来被首帧换版作废的）
        rows.setdefault(f"{r['shot']}__{r['variant']}", r)
    tab = collections.Counter()
    for k, s in stare.items():
        r = rows.get(k)
        ff = Path((r or {}).get("first_frame") or "").name
        fl = lab.get(f"img:{ff}#0")
        tab[(fl or "首帧未标", s)] += 1
    imgs = [v for k, v in lab.items() if k.startswith("img:") and v != "看不清"]
    return {"片头看镜头": [sum(stare.values()), len(stare)],
            "片头定格+看镜头": [sum(1 for v in clips.values() if v == "开头定格+看镜头"), len(stare)],
            "首帧看镜头": [imgs.count("看镜头"), len(imgs)],
            "首帧看镜头→片头看镜头": [tab[("看镜头", True)], tab[("看镜头", True)] + tab[("看镜头", False)]],
            "首帧没看→片头看镜头": [tab[("没看镜头", True)], tab[("没看镜头", True)] + tab[("没看镜头", False)]]}


def summarize(rows):
    out = {}
    for scope, sel in (("现行版", [r for r in rows if r["current"]]), ("全部尝试", rows)):
        c, n = collections.Counter(), collections.Counter()
        for r in sel:
            for k, v in classes(r["score"]).items():
                if v is None:
                    continue
                n[k] += 1
                c[k] += bool(v)
        out[scope] = {k: [c[k], n[k]] for k in n}
    by = collections.defaultdict(list)
    for r in rows:
        by[r["recipe"]].append(r)
    out["按配方(全部尝试)"] = {}
    for rec, sel in by.items():
        c, n = collections.Counter(), collections.Counter()
        for r in sel:
            for k, v in classes(r["score"]).items():
                if v is None:
                    continue
                n[k] += 1
                c[k] += bool(v)
        out["按配方(全部尝试)"][rec] = {k: [c[k], n[k]] for k in n}
    return out


def main(argv):
    rows = load_renders()
    res = summarize(rows)
    res["看镜头(人工标签)"] = gaze_rates()
    res["_n"] = {"renders": len(rows), "current": sum(r["current"] for r in rows)}
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
