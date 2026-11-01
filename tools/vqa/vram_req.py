"""VQAGATE 11-01：本机看图显存压测用的请求集（项目 .venv 跑）：同一套 rubric / 跨镜参考，写成 JSON（只含本机文件路径，不出本机）。
样本 = ep01 当前首帧 7 张 + 总调度 100 张视线标签里各取 n 张正 / 反例（data/acting/gaze_labels.json，图 = video/inputs/<jpg>）。
    .venv/Scripts/python.exe tools/vqa/vram_req.py [--n 10]  → data/vqa/vram_bench/requests.json"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/vqa", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))
from ns_agent.vqa import continuity as CT  # noqa: E402
from ns_agent.vqa import rubric  # noqa: E402
import gate_scan as GS  # noqa: E402

n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 10
reqs = []
for s in range(1, 8):
    sid = f"ep01-S{s}"
    t, _ = GS.active(sid, "image")
    if not t:
        continue
    extra, note = CT.refs_for(sid, "first")
    r = rubric.build_image_request(str(ROOT / "data" / t["file"]), t.get("prompt") or "", GS.refs_of(sid, t), extra_refs=extra,
                                   spec={"continuity": note} if note else None)
    reqs.append({"id": f"{sid}_v{t['n']}", "label": None, "req": r})
lab = json.loads((ROOT / "data/acting/gaze_labels.json").read_text(encoding="utf-8"))
img = {}
for k, v in lab.items():
    if k.startswith("img:"):
        f = k[4:].split("#")[0]
        img[f] = img.get(f, False) or v == "看镜头"
pos = [f for f, v in sorted(img.items()) if v][:n]
neg = [f for f, v in sorted(img.items()) if not v][:n]
for f in pos + neg:
    p = ROOT / "data/pipeline/runs/series10_v1/video/inputs" / f
    if not p.exists():
        continue
    sid = f.split("_")[0]
    r = rubric.build_image_request(str(p), (CT.shot_rec(sid) or {}).get("img_prompt") or "", [])
    reqs.append({"id": f, "label": img[f], "req": r})
out = ROOT / "data/vqa/vram_bench/requests.json"
out.write_text(json.dumps(reqs, ensure_ascii=False, indent=0), encoding="utf-8")
print(len(reqs), "requests →", out)
