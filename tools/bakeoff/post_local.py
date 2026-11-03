"""BAKEOFF：本机跑 REFLOCK 的契约 postflight（ns_agent.gen_contract.postflight）——Q2 造型 / Q7 场景用它的 CLIP 区域实现，
不再用 score_srv 的颜色直方图代理（总调度 11-01 + ITERAUDIT：直方图代理对透明鞋无效，不得用于排名）。

输入：data/ab/image_bakeoff/{plan.json, results.json, full/*.jpg}（run.py pull 拉回的 768×1344 JPEG q92）
     请求 = 本镜 Shot Spec 的 cast + 本镜完整资产记录（plan.shot_rec，REFLOCK plan_for 4 槽 record）——各组用同一个“应该穿什么”标准；
     remote = score_srv 的 score_remote 同格式输出；hands = hands_remote 的 flags。
输出：data/ab/image_bakeoff/postflight.json {id: ContractResult.to_dict()+local}
用法：.venv/Scripts/python.exe tools/bakeoff/post_local.py [--only id1,id2]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
AB = ROOT / "data/ab/image_bakeoff"
sys.path.insert(0, str(ROOT / "services/agent"))


def main(argv):
    argv = RUNS.gate_legacy_tool(argv, __file__)
    from ns_agent.gen_contract import postflight
    plan = json.loads((AB / "plan.json").read_text(encoding="utf-8"))
    res = json.loads((AB / "results.json").read_text(encoding="utf-8"))
    outp = AB / "postflight.json"
    out = json.loads(outp.read_text(encoding="utf-8")) if outp.exists() else {}
    only = set(argv[1].split(",")) if len(argv) > 1 and argv[0] == "--only" else None
    items = {i["id"]: i for i in plan["items"]}
    t0, n = time.time(), 0
    for iid, r in res["items"].items():
        if only and iid not in only or (not only and iid in out):
            continue
        it = items.get(iid)
        img = AB / "full" / f"{iid}.jpg"
        if not it or not img.exists() or "remote" not in r:
            continue
        rec = plan.get("shot_rec", {}).get(it["shot"]) if it["kind"] != "edit" else None
        req = {"kind": "image", "project": _LEGACY, "shot_id": it["src"] if it["kind"] != "edit" else "ep05-S5",
               "cast": plan.get("casts", {}).get(it["src"], []) if it["kind"] != "edit" else [{"name": "林晚", "presence": "在画", "x": "中"}],
               "asset_refs": rec or {}}
        try:
            d = postflight("image", {"image": str(img), "request": req, "remote": r["remote"], "cross": res.get("cross_raw") or {},
                                     "hands": {"flags": r.get("Q5") or []}})
        except Exception as e:  # noqa: BLE001
            d = {"error": str(e)[:400]}
        out[iid] = d
        n += 1
        if n % 20 == 0:
            outp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            print(f"{n} 张 {time.time() - t0:.0f}s", flush=True)
    outp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("postflight", n, "新增，共", len(out))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
