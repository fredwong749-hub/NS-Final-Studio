"""VIDEO-RCA：首帧“看镜头”根因 A/B（出图层）。同一出图图（first_frame_jobs.json 该镜 graph）、同参考、同 seed，只改一句系统句。

假设（证据见 docs/video_rca/RCA_r1.md §看镜头）：
  H1 双人镜系统句 framing.two_shot_clause 写了“各自至少四分之三侧脸朝向镜头（… toward the camera）”→ 两人都对镜头；
  H2 单人镜：图1 脸部参考是正脸直视镜头的大头照，Qwen-Image 2.1 把参考的视线一起抄过来；正文“视线朝画面左侧”压不住。
臂：old = 原提示词；new = 替换 / 追加系统视线句。只在 gpu36:2 跑（让道同 lab.py），出图存 data/ab/video_rca/<exp>/。

    .venv/Scripts/python.exe tools/video_rca/img_lab.py <exp.json>
exp.json：{"name":..., "arms":[{"id":..., "shot":..., "seed":..., "replace":[[old,new],...], "append": "..."}]}
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab as L  # noqa: E402

ROOT = L.ROOT
FFJ = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"


def upload_png(rel: str) -> str:
    p = ROOT / rel
    b = "----rca" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"rca_{p.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + p.read_bytes() + \
        (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nvideo_rca\r\n"
         f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n").encode()
    r = json.loads(L.api("/upload/image", body, f"multipart/form-data; boundary={b}", timeout=600))
    return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]


def _local_free():
    """本机道 laptop:0（18388）：队列为空才交（生产优先）"""
    d = json.loads(L.api("/queue", timeout=20))
    n = len(d["queue_running"]) + len(d["queue_pending"])
    return (n == 0), f"本机道队列 {n}"


def main(p: Path, local: bool = False):
    if local:            # 跳板慢 / 断时走笔记本本机道，不经网络（scope=ab，只写 data/ab/video_rca/）
        L.PORT = 18388
        L.lane_free = _local_free
    exp = json.loads(p.read_text(encoding="utf-8"))
    name = exp["name"]
    out = L.AB / name
    out.mkdir(parents=True, exist_ok=True)
    jobs = {j["shot"]: j for j in json.loads(FFJ.read_text(encoding="utf-8"))["jobs"]}
    res_p = out / "results.json"
    res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.exists() else {}
    ups: dict[str, str] = {}
    for a in exp["arms"]:
        if res.get(a["id"], {}).get("file"):
            continue
        j = jobs[a["shot"]]
        g = json.loads(json.dumps(j["graph"]))
        prompt = None
        for n in g.values():
            for k, v in list(n["inputs"].items()):
                if isinstance(v, str) and v.startswith("@upload:"):
                    rel = v[8:]
                    if rel not in ups:
                        ups[rel] = upload_png(rel)
                    n["inputs"][k] = ups[rel]
            if n["class_type"] == "TextEncodeQwenImage21":
                t = n["inputs"]["prompt"]
                for o, nw in a.get("replace") or []:
                    if o not in t:
                        raise SystemExit(f"{a['id']}：原句不在提示词里：{o[:40]}")
                    t = t.replace(o, nw)
                if a.get("append"):
                    t = t.replace("专业电影画面", a["append"] + "，专业电影画面", 1)
                n["inputs"]["prompt"] = prompt = t
            if n["class_type"] == "RandomNoise":
                n["inputs"]["noise_seed"] = int(a["seed"])
            if n["class_type"] == "SaveImage":
                n["inputs"]["filename_prefix"] = f"video_rca/{name}/{a['id']}"
        while True:
            ok, why = L.lane_free()
            if ok:
                break
            print("让道：", why, flush=True)
            time.sleep(15)
        body = {"prompt": g, "client_id": L.CLIENT + uuid.uuid4().hex[:8],
                "extra_data": {"ns_tag": {"agent": "VIDEO-RCA", "kind": "image", "v": 1, "label": f"实验 {name}/{a['id']}"}}}
        pid = json.loads(L.api("/prompt", json.dumps(body).encode(), timeout=120))["prompt_id"]
        print("SUBMIT", a["id"], pid, flush=True)
        while True:
            time.sleep(10)
            try:
                h = json.loads(L.api(f"/history/{pid}", timeout=30))
            except Exception:  # noqa: BLE001
                continue
            if pid in h and h[pid].get("status", {}).get("completed") is not None:
                break
        rec = {"shot": a["shot"], "seed": a["seed"], "prompt": prompt, "status": h[pid].get("status", {}).get("status_str")}
        for node in h[pid].get("outputs", {}).values():
            for im in node.get("images", []) or []:
                q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"})
                dst = out / f"{a['id']}.png"
                dst.write_bytes(L.api(f"/view?{q}", timeout=600))
                rec["file"] = str(dst.relative_to(ROOT))
        print("DONE", a["id"], rec.get("file"), rec["status"], flush=True)
        res[a["id"]] = rec
        res_p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def export(p: Path):
    """服务器端执行（srv_run.py，kind=image）：@upload: 参考图换成 @ref<i> 占位 + inputs 映射"""
    exp = json.loads(p.read_text(encoding="utf-8"))
    jobs = {j["shot"]: j for j in json.loads(FFJ.read_text(encoding="utf-8"))["jobs"]}
    out = []
    for a in exp["arms"]:
        j = jobs[a["shot"]]
        g = json.loads(json.dumps(j["graph"]))
        inputs = {}
        for n in g.values():
            for k, v in list(n["inputs"].items()):
                if isinstance(v, str) and v.startswith("@upload:"):
                    key = f"@ref{len(inputs)}"
                    inputs[key] = v[8:]
                    n["inputs"][k] = key
            if n["class_type"] == "TextEncodeQwenImage21":
                t = n["inputs"]["prompt"]
                for o, nw in a.get("replace") or []:
                    if o not in t:
                        raise SystemExit(f"{a['id']}：原句不在提示词里：{o[:40]}")
                    t = t.replace(o, nw)
                if a.get("append"):
                    t = t.replace("专业电影画面", a["append"] + "，专业电影画面", 1)
                n["inputs"]["prompt"] = t
            if n["class_type"] == "RandomNoise":
                n["inputs"]["noise_seed"] = int(a["seed"])
        out.append({"id": a["id"], "shot": a["shot"], "seed": a["seed"], "kind": "image", "graph": g, "inputs": inputs,
                    "prompt": [n["inputs"]["prompt"] for n in g.values() if n["class_type"] == "TextEncodeQwenImage21"][0]})
    (L.AB / exp["name"]).mkdir(parents=True, exist_ok=True)
    (L.AB / exp["name"] / "jobs_local.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    L.export(exp["name"], out)


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(Path(sys.argv[2]))
    elif sys.argv[1] == "local":
        main(Path(sys.argv[2]), local=True)
    else:
        main(Path(sys.argv[1]))
