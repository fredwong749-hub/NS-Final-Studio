"""VQA 闸门回归集（VQAGATE 11-02，DISTILL missed_defect_to_regression；总调度：接 system_version cut 闸门（FACTORY）与 iter_gate（SYSARCH））。

人指出的漏检 / 误报存进 data/vqa/regression/<case>.json：{case, kind, image, expect, note, source, ...}。
改 VQA 口径（config/vqa.json、config/gen_contract.json 的 Q1a_attr、hair_attr / contract 代码）前后都要全过：任何一条和 expect 不符 → 退出 1。

  kind = q1a                确定性逐人头发（hair_attr.measure + judge，人物卡读 config），本机跑，不占看图卡
  kind = q1a_vlm_known_gap  已知缺口：确定性应仍是 expect.Q1a_det（翻了要更新用例），--vlm 时再核对看图逐人问答
  另外 --vlm 时跑 data/vqa/gate_calib/gaze_regression.json（看镜头，tools/vqa/gaze_regression.py 的 judge）

    python tools/vqa/regression_check.py            # 确定性用例（cut / iter_gate 用）
    python tools/vqa/regression_check.py --vlm      # 加看图类用例（慢，占看图卡）
    python tools/vqa/regression_check.py --json     # 机读结果（master_review 机签读 pairs）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "data" / "vqa" / "regression"


def cases() -> list[dict]:
    out = []
    for p in sorted(REG.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:      # 坏用例要显式报，不能静默跳过（漏跑 = 假全过）
            out.append({"case": p.stem, "kind": "broken", "error": repr(e)[:200]})
    return out


def run_q1a(c: dict, cards: dict) -> str:
    from ns_agent.vqa import hair_attr as HA
    img = ROOT / c["image"]
    if not img.exists():
        return "missing_image"
    todo = {cid: b for cid, b in (c.get("boxes") or {}).items() if cid in cards}
    allb = c.get("all_boxes") or list(todo.values())
    order = list(todo.values()) + [b for b in allb if b not in todo.values()]
    fs = HA.measure(img, order)
    bad = []
    for (cid, _b), f in zip(todo.items(), fs):
        bad += HA.judge(cid, f, cards[cid])
    return "fail" if bad else "pass"


def main(argv: list[str]) -> int:
    sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "packages/qc"), str(ROOT)]
    from ns_agent.gen_contract import cfg
    cards = ((cfg().get("image_thresholds") or {}).get("Q1a_attr") or {}).get("cards") or {}
    vlm = "--vlm" in argv
    rows = []
    for c in cases():
        k = c.get("kind")
        if k == "broken":
            rows.append({"case": c["case"], "want": "?", "got": "broken", "why": c.get("error")})
        elif k == "q1a":
            rows.append({"case": c["case"], "want": c["expect"]["Q1a"], "got": run_q1a(c, cards)})
        elif k == "q1a_vlm_known_gap":
            img = ROOT / c["image"]
            if not img.exists():
                rows.append({"case": c["case"], "want": c["expect"]["Q1a_det"], "got": "missing_image"})
    if vlm:
        from tools.vqa import gaze_regression as GR
        reg = json.loads((ROOT / "data/vqa/gate_calib/gaze_regression.json").read_text(encoding="utf-8"))
        for it in reg.get("items") or []:
            r = GR.judge(ROOT / it["path"], it.get("shot", ""))
            got = "看镜头" if r.get("eye_contact") else "没看镜头"
            rows.append({"case": "gaze:" + Path(it["path"]).stem, "want": it["label"], "got": got})
    bad = [r for r in rows if r["want"] != r["got"]]
    pairs = [{"auto": "fail" if r["got"] in ("fail", "看镜头") else "pass", "human": "fail" if r["want"] in ("fail", "看镜头") else "pass"}
             for r in rows if r["got"] not in ("missing_image", "broken")]
    if "--json" in argv:
        print(json.dumps({"n": len(rows), "bad": bad, "pairs": pairs}, ensure_ascii=False))
    else:
        for r in rows:
            print(("OK  " if r["want"] == r["got"] else "BAD ") + f"{r['case']}: 应 {r['want']} 得 {r['got']}")
        print(f"REGRESSION {'PASS' if not bad else 'FAIL'}：{len(rows) - len(bad)}/{len(rows)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
