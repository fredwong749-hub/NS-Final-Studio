"""VQAGATE 11-01：本机看图显存 / 耗时 / 判定压测——经本机看图服务（127.0.0.1:8870，LOCALGPU 让道模式：出图来活服务自己让卡），
按条改主图 / 参考图像素和输出 token 上限，记服务回报的每条峰值显存（peak_mib = torch max_memory_allocated）与耗时。
    .venv/Scripts/python.exe tools/vqa/vram_bench.py --tag a [--subject 800000] [--ref 200000] [--tokens 1200] [--limit 24]
→ data/vqa/vram_bench/<tag>.json；判定用 rubric.parse 解析（同生产）"""
import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/agent"))


def main():
    from ns_agent.vqa import rubric
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--subject", type=int, default=1300000)
    ap.add_argument("--ref", type=int, default=360000)
    ap.add_argument("--tokens", type=int, default=1800)
    ap.add_argument("--limit", type=int, default=999)
    ap.add_argument("--url", default="http://127.0.0.1:8870")
    ap.add_argument("--requests", default="requests.json")
    ap.add_argument("--b64", action="store_true", help="服务在别的机器（隧道 8871 → gpu36）：本机先缩图转字节再发")
    a = ap.parse_args()
    reqs = json.loads((ROOT / "data/vqa/vram_bench" / a.requests).read_text(encoding="utf-8"))[:a.limit]
    from ns_agent.vqa import client as VC
    out = ROOT / "data/vqa/vram_bench" / f"{a.tag}.json"
    rows = []
    for r in reqs:
        q = r["req"]
        imgs = [{"path": im["path"], "label": im["label"], "max_pixels": a.subject if im["label"] == "【待检图】" else a.ref}
                for im in q["images"]]
        if a.b64:
            import base64
            for im in imgs:
                im["b64"] = base64.b64encode(VC._shrink(Path(im.pop("path")), im["max_pixels"])).decode()
        body = {"system": q["system"], "text": q["text"], "images": imgs, "max_new_tokens": a.tokens, "wait_s": 3600,
                "key": "bench_" + uuid.uuid4().hex[:12], "refresh": True, "label": f"显存压测 {a.tag}"}
        t0 = time.time()
        try:
            res = json.loads(urllib.request.urlopen(urllib.request.Request(a.url + "/generate", json.dumps(body).encode(),
                                                                           {"Content-Type": "application/json"}), timeout=4000).read())
        except Exception as e:  # noqa: BLE001
            res = {"error": repr(e)[:200]}
        v = rubric.parse(res.get("text", "")) if "text" in res else {}
        rows.append({"id": r["id"], "label": r["label"], "label_item_wrong_person": r.get("label_item_wrong_person"), "wall_s": round(time.time() - t0, 1), "secs": res.get("seconds"),
                     "peak_mib": res.get("peak_mib"), "reserved_mib": res.get("reserved_mib"), "tokens_in": res.get("tokens_in"),
                     "tokens_out": res.get("tokens_out"), "error": res.get("error"), "ok_parse": v.get("ok_parse"),
                     "salvaged": v.get("salvaged"), "defects": v.get("defects"), "checks": v.get("checks"), "people": v.get("people")})
        print(a.tag, r["id"], rows[-1]["secs"], "s", rows[-1]["tokens_in"], "→", rows[-1]["tokens_out"], "tok",
              rows[-1]["peak_mib"], "/", rows[-1]["reserved_mib"], "MiB", rows[-1]["defects"], rows[-1]["error"] or "", flush=True)
        out.write_text(json.dumps({"cfg": vars(a), "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
