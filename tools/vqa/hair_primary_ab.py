"""发色“Q1a 确定性主判”A/B（VQAGATE 11-02，总调度采纳标准：主判召回 ≥ 现行、误报 ≤ 现行、回归集 12/12 → 带开关上线；召回优先）。

样本 = Q1a 标定集（GATE_CALIBRATION §18，106 张带顾沉 / 陈宇的首帧；标签 = 亲看的串属性 6 张，其余正常）。
每张跑一次生产同款看图（VC.inspect_image，记 hair_mismatch 原判）+ Q1a 确定性（hair_attr.measure + judge，脸框来自标定 emb）。
  R0 现行：VLM hair_mismatch 或 Q1a fail 即拦
  R1 主判：Q1a fail 拦；VLM hair_mismatch 只在 Q1a 没测到（没有可核对的脸）时拦
VLM 说不对、Q1a 说对的图要亲看（hair_mismatch 也管齐刘海等 Q1a 管不到的项）：列在 report 的 need_eye 里，人看后写进 labels_extra。
    python tools/vqa/hair_primary_ab.py run <calib_dir> [--via-tunnel]
    python tools/vqa/hair_primary_ab.py report
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "packages/qc"), str(ROOT)]
OUT = ROOT / "data" / "vqa" / "gate_calib" / "hair_primary_ab.json"
BAD = {"image_006_142caf24", "image_005_c49b5f5f", "image_002_723cbde2", "image_001_3567d4a5", "image_004_113d1bd3", "image_008_4ffc8973"}


def run(calib: Path) -> None:
    from ns_agent.gen_contract import cfg
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import continuity as CT
    from ns_agent.vqa import hair_attr as HA
    if "--via-tunnel" in sys.argv:
        _up = VC._local_up
        VC._local_up = lambda u: False if u.rstrip("/").endswith(":8870") else _up(u)
    cards = cfg()["image_thresholds"]["Q1a_attr"]["cards"]
    items = json.loads((calib / "items.json").read_text(encoding="utf-8"))
    rows3 = json.loads((calib / "rows3.json").read_text(encoding="utf-8"))
    E = {}
    for ln in (calib / "emb.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.startswith('{"path"'):
            d = json.loads(ln)
            E[d["path"]] = d["faces"]
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    done = {r["file"] for r in out}
    for it in items:
        if it["file"] in done or not (ROOT / it["file"]).exists():
            continue
        fs = [f for f in E.get("img/" + it["n"]) or [] if f["det"] >= 0.75 and f["h_ratio"] >= 0.04]
        rs = [r for r in rows3 if r["n"] == it["n"]]
        boxes = [f["bbox"] for f in fs]
        q1a_bad, measured = [], False
        if boxes:
            feats = HA.measure(ROOT / it["file"], boxes)
            for r, x in zip(rs, feats):
                if r["who"] in cards:
                    measured = True
                    q1a_bad += HA.judge(r["who"], x, cards[r["who"]])
        ep, s = it["file"].split("/")[2:4]
        prompt = (CT.shot_rec(f"{ep}-{s}") or {}).get("img_prompt") or ""
        v = VC.inspect_image(str(ROOT / it["file"]), prompt, [])
        hm = ((v.get("checks") or {}).get("hair_mismatch") or {}) if not v.get("error") else {}
        out.append({"file": it["file"], "bad": any(b in it["file"] for b in BAD), "q1a_fail": bool(q1a_bad), "q1a_measured": measured,
                    "vlm": hm.get("s"), "vlm_e": str(hm.get("e") or "")[:120], "error": v.get("error")})
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
        os.replace(tmp, OUT)
        print(len(out), it["file"][-34:], out[-1]["bad"], out[-1]["q1a_fail"], hm.get("s"), flush=True)


def report() -> dict:
    rows = [r for r in json.loads(OUT.read_text(encoding="utf-8")) if not r.get("error") and r.get("vlm") is not None]
    res = {"n": len(rows)}
    for rule in ("R0", "R1"):
        tp = fp = fn = tn = 0
        for r in rows:
            vlm = r["vlm"] == "defect"
            d = (vlm or r["q1a_fail"]) if rule == "R0" else (r["q1a_fail"] or (vlm and not r["q1a_measured"]))
            tp += d and r["bad"]
            fp += d and not r["bad"]
            fn += (not d) and r["bad"]
            tn += (not d) and not r["bad"]
        res[rule] = {"recall": f"{tp}/{tp + fn}", "false_pos": f"{fp}/{fp + tn}"}
    res["need_eye"] = [r["file"] for r in rows if r["vlm"] == "defect" and not r["q1a_fail"] and not r["bad"]]
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["run"]:
        run(Path(sys.argv[2]))
    print(json.dumps(report(), ensure_ascii=False, indent=1))
