"""造型审计的内容层问题 → 写作模型（llm_config "script_write" = abliteration，关推理）按 P1 登记改正（REFLOCK 2026-10-31）。

Claude 只写系统、不写内容：本工具只把问题、登记原文、该镜原文交给写作模型，收回“修订提案”，做机器校验
（台词不在输入里、改后正文不得再写同角色其它造型的部件、不得出现 HC-02 / HC-07 阻断词），写进
<run>/assets/look_revisions.json。是否导入正式剧本走现有导入流程（备份 + 日志），不在这里直接改剧本。

    .venv/Scripts/python.exe tools/gen_contract/look_revise.py [--budget 0.05] [--dry-run]
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "services/api", "packages/schema", "tools/pipeline", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))

RUN = ROOT / "data/pipeline/runs/series10_v1"
TAG = "reflock-lookfix-20261031"
SYSTEM = ("你是短剧剧本的分镜修订员。只按给定的造型登记修正一镜的 img 画面描述里与登记冲突的服装 / 鞋 / 饰品写法；"
          "其它内容（动作、机位、光线、场景、质感句）尽量逐字保留；不写台词；全部角色都是成年人；不改发色、发型、标志物。"
          "输出 JSON：{\"choice\": \"text\" 或 \"registry\", \"img\": \"改后的完整 img 正文\", \"registry_note\": \"若选 registry：该镜起改用哪套造型\", \"why\": \"一句话\"}。"
          "choice=text 表示按本镜登记造型改正文；choice=registry 表示正文是剧情需要的换装过程，应把本镜起的造型登记改为另一套（此时 img 原样返回）。")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    import look_audit as LA
    import hard_constraints as HC
    from run_chain import call_llm
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 0.05
    rep = LA.audit()
    looks = LA.AR.load_looks(LA.P)
    d = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    shots = {f"ep{e['number']:02d}-S{s['index']}": (e, s) for e in d["episodes"] for s in e["shots"]}
    out = []
    for i in rep["issues"]:
        if i["layer"] != "content" or i["level"] != "block" or i["where"] not in shots:
            continue
        ep, s = shots[i["where"]]
        reg = {LA.AR.ID_NAME.get(c, c): {lid: L.zh for lid, L in lks.items()} for c, lks in looks.items()}
        user = json.dumps({"问题": i["detail"], "建议": i["fix"], "镜号": i["where"], "img原文": s["img_prompt"],
                           "本集造型行": [{"角色": r["character"], "自镜": r.get("from_shot"), "原文": r["raw"]} for r in ep["looks"]],
                           "P1造型登记": reg}, ensure_ascii=False, indent=1)
        if "--dry-run" in sys.argv:
            print(user[:600])
            continue
        r = call_llm(SYSTEM, [{"role": "user", "content": user}], max_tokens=1500, reasoning=False, tag=TAG, budget=budget,
                     meta={"link": "reflock-lookfix", "shot": i["where"]})
        m = re.search(r"\{.*\}", r["content"], re.S)
        prop = json.loads(m.group(0)) if m else {"error": "无 JSON", "raw": r["content"][:500]}
        checks = []
        new = prop.get("img") or ""
        if prop.get("choice") == "text":
            lab = re.search(r"“([^”]+)”", i["detail"])
            if lab and lab.group(1) in new:
                checks.append(f"改后仍写“{lab.group(1)}”")
        checks += [x["message"] for x in HC.check_text(new) + HC.check_look_lock(new) if x.get("level") == "block"]
        out.append({"shot": i["where"], "issue": i, "proposal": prop, "checks": checks, "ok": not checks and "error" not in prop,
                    "model": r["model"], "usd": round(r["usd"], 5)})
        print(i["where"], prop.get("choice"), "ok" if not checks else checks, flush=True)
    if "--dry-run" not in sys.argv:
        (RUN / "assets" / "look_revisions.json").write_text(json.dumps(
            {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "by": "写作模型（llm_config script_write，关推理）",
             "status": "提案，未导入正式剧本（导入走 tools/import_script 流程）", "revisions": out}, ensure_ascii=False, indent=1),
            encoding="utf-8")


if __name__ == "__main__":
    main()
