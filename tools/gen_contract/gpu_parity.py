"""服务器打分与笔记本打分逐项一致性核对（REFLOCK 11-01，总调度：搬到 gpu33 GPU 前后 5 张图分数要相同）。
同一张交付图：笔记本 postflight.measure_local（CPU） vs remote_score.full_score（gpu33 GPU，原始输出 + 同参数后处理复现）。
输出 data/review_pages/asset_reflock/gpu_parity.json

    .venv/Scripts/python.exe tools/gen_contract/gpu_parity.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))
import remote_score as RS  # noqa: E402
from ns_agent.gen_contract import postflight as PO  # noqa: E402
from ns_render import image_params as IP  # noqa: E402

V9 = ROOT / "data/pipeline/runs/series10_v1/images/reflock_val/v9"
IDS = ["ep01-S3_vR_s20261311", "ep01-S3_vR_s20261312", "ep01-S1_vR_s20261311", "ep01-S4_vR_s20261311", "ep01-S4_vRb_s20261311"]
HOSTDIR = "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu1/reflock_v9/"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jobs = {j["id"]: j for j in json.loads((V9 / "jobs.json").read_text(encoding="utf-8"))}
    st = json.loads((V9 / "state.json").read_text(encoding="utf-8"))
    ls = RS.ssh("gpu33", "ls " + HOSTDIR).stdout.split()
    post = RS.post_of(IP.resolve("frame_v9", {"style_suffix": ""}))
    items, rec_of = [], {}
    for k in IDS:
        rec = jobs[k]["asset_refs"]
        rec_of[k] = rec
        hp = sorted(x for x in ls if x.startswith(k + "_"))
        items.append({"id": k, "host_path": HOSTDIR + hp[-1] if hp else None, "file": st[k]["file"], "post": post,
                      "rows": PO.q2_rows(rec), "scene": PO.scene_file(rec)})
    t0 = time.time()
    srv = RS.full_score("gpu33", items)
    t_srv = time.time() - t0
    rows = []
    for it in items:
        k = it["id"]
        t1 = time.time()
        loc = PO.measure_local(ROOT / it["file"], rec_of[k], (srv.get("items") or {}).get(k))
        t_loc = time.time() - t1
        s = (srv.get("local") or {}).get(k) or {}
        d2 = [(a["label"], a["clip"], b["clip"], round(abs(a["clip"] - b["clip"]), 4)) for a, b in zip(loc["Q2"], s.get("Q2") or [])]
        rows.append({"id": k, "local_s": round(t_loc, 1), "Q2": d2,
                     "Q4": {x: (loc["Q4"].get(x), (s.get("Q4") or {}).get(x)) for x in ("lap_full", "sat_mean", "specular")},
                     "Q7": ((loc.get("Q7") or {}).get("clip"), (s.get("Q7") or {}).get("clip"))})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    out = {"server_seconds_total": round(t_srv, 1), "server_device": srv.get("clip_gpu") or srv.get("clip_device"),
           "clip_error": srv.get("clip_error"), "rows": rows}
    (ROOT / "data/review_pages/asset_reflock/gpu_parity.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("server", out["server_seconds_total"], "s", out["server_device"], out["clip_error"])


if __name__ == "__main__":
    main()
