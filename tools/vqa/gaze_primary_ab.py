"""看镜头“确定性主判”A/B（VQAGATE 11-02，总调度：VLM 判定余量薄，0.5/0.6 MP 之间 eye_contact 来回翻 → gaze_mp 主判、VLM 辅助，先 A/B 再上线）。

样本 = 总调度视线标签（data/acting/gaze_labels.json 的 img:* 条目，“看镜头 / 没看镜头”，图 = video/inputs/<jpg>）。
每张记看图模型原判（不经 merge）与 gaze_mp 原始分数，离线比两条规则对标签的召回 / 误报：
  R0 现行：VLM defect 或 gaze_mp 命中（≤T）即拦（拿不准带复判略：要再调看图，R0 取 VLM 原判代替）
  R1 主判：gaze_mp 测到脸 → 命中（≤T）拦、远离（>2T）放、带内（T–2T）听 VLM；没测到脸 → 听 VLM
    python tools/vqa/gaze_primary_ab.py run [--via-tunnel]  # 跑看图 + gaze_mp → data/vqa/gate_calib/gaze_primary_ab.json（可续跑）
    python tools/vqa/gaze_primary_ab.py report   # 两条规则对标签
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "packages/qc")]
OUT = ROOT / "data" / "vqa" / "gate_calib" / "gaze_primary_ab.json"
sys.path.insert(0, str(ROOT))


def _inputs() -> Path:
    from tools.autopilot import runs
    return runs.run_dir(runs.primary_run(strict=True)) / "video" / "inputs"


def samples() -> list[tuple[str, str]]:
    lab = json.loads((ROOT / "data/acting/gaze_labels.json").read_text(encoding="utf-8"))
    out = []
    for k, v in lab.items():
        if k.startswith("img:") and v in ("看镜头", "没看镜头"):
            f = k[4:].split("#")[0]
            if (_inputs() / f).exists():
                out.append((f, v))
    return out


def score(f: dict, g: dict) -> float:
    return abs(g["A"] * f["yaw_n"] + f["eye_x"])


def run() -> None:
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import contract as VQ
    if "--via-tunnel" in sys.argv:          # 笔记本 8870 在让道时会卡：跳过它，走隧道 8871 → gpu36（client 会转 b64）
        _up = VC._local_up
        VC._local_up = lambda u: False if u.rstrip("/").endswith(":8870") else _up(u)
    rows = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    done = {r["img"] for r in rows}
    for f, lab in samples():
        if f in done:
            continue
        shot = "-".join(f.split("_")[0].split("-")[:2])
        from ns_agent.vqa import continuity as CT
        prompt = (CT.shot_rec(shot) or {}).get("img_prompt") or ""
        v = VC.inspect_image(str(_inputs() / f), prompt, [])
        ec = ((v.get("checks") or {}).get("eye_contact") or {}) if not v.get("error") else {}
        faces = VQ.gaze_mp(_inputs() / f)
        rows.append({"img": f, "label": lab, "vlm": ec.get("s"), "vlm_e": str(ec.get("e") or "")[:120], "error": v.get("error"),
                     "faces": [{k: x.get(k) for k in ("yaw_n", "pitch_n", "eye_x", "bs_y", "blink", "ybox")} for x in faces or []]})
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
        os.replace(tmp, OUT)
        print(len(rows), f, lab, ec.get("s"), len(faces or []), flush=True)


def decide(r: dict, g: dict, rule: str) -> bool | None:
    vlm = r.get("vlm")
    if r.get("error") or vlm is None:
        return None
    fs = [x for x in r["faces"] if x.get("pitch_n") is not None and x["pitch_n"] <= g["P"]
          and (x.get("bs_y") or 0) <= g.get("down_max", 9) and (x.get("blink") or 0) <= g.get("blink_max", 9)]
    hit = any(score(x, g) <= g["T"] for x in fs)
    if rule == "R0":
        return vlm == "defect" or hit
    if not r["faces"]:
        return vlm == "defect"
    if hit:
        return True
    if any(score(x, g) <= g.get("band", 2.0) * g["T"] for x in fs):
        return vlm == "defect"
    return False


def report() -> dict:
    from ns_agent.vqa import contract as VQ
    g = {"A": 0.3, "T": 0.05, "P": 0.2, "band": 2.0, **(VQ.gate_cfg().get("gaze_mp") or {})}
    raw = json.loads(OUT.read_text(encoding="utf-8"))
    # 标签按“图里第几个人”（img:<jpg>#k），规则按整张图判 → 按图汇总：任一人看镜头 = 这张图看镜头
    by: dict = {}
    for r in raw:
        if r["img"] in by:
            if r["label"] == "看镜头":
                by[r["img"]]["label"] = "看镜头"
        else:
            by[r["img"]] = dict(r)
    rows = list(by.values())
    res = {}
    for rule in ("R0", "R1"):
        tp = fp = fn = tn = 0
        for r in rows:
            d = decide(r, g, rule)
            if d is None:
                continue
            pos = r["label"] == "看镜头"
            tp += d and pos
            fp += d and not pos
            fn += (not d) and pos
            tn += (not d) and not pos
        res[rule] = {"recall": f"{tp}/{tp + fn}", "false_pos": f"{fp}/{fp + tn}", "agree": round((tp + tn) / max(1, tp + fp + fn + tn), 3)}
    res["n"] = len(rows)
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["run"]:
        run()
    print(json.dumps(report(), ensure_ascii=False))
