"""渲染任务中心数据核对（GPUVIEW 11-01；规则 K-OPS-G02）：界面用的 /api/render-tasks 与各来源直接读数是否一致。

与 DATAALIGN 的 tools/qa/data_parity.py（待交付）同一思路：界面数字 = 后端源头。这里核三件事：
  P1 分桶对得上：counts.all = pending + rendering + failed + done，且等于 rows 条数；每个桶的数 = rows 里该状态的条数。
  P2 ComfyUI 队列：每条道直接 GET /queue 的 prompt_id 集合 = 接口里该道“渲染中 / 等待”的行（comfy 行 + 带 prompt_id 的画布任务行）。
  P3 画布任务：直接 GET :8800/api/jobs 里 queued + running 的条数 = 接口里 source=ns_api 的“等待 + 渲染中”条数。
队列在两次读之间会变：不一致时隔 3 秒重核一次，两次都不一致才算不过。
用法：.venv/Scripts/python.exe tools/qa/render_tasks_parity.py [--api http://127.0.0.1:8800] [--jobs-api http://127.0.0.1:8800]
退出码 0 = 一致；1 = 不一致；2 = 读不到（未测 ≠ 通过）。结果写 data/qa/render_tasks_parity/<时间>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))


def _get(url: str, timeout: float = 60):
    tok = ""
    try:
        tok = (ROOT / "data" / "auth" / "viewer_token").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    req = urllib.request.Request(url, headers={"x-ns-viewer-token": tok})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check(api: str, jobs_api: str) -> dict:
    from ns_render import endpoints as EP
    d = _get(f"{api}/api/render-tasks")
    rows = d["rows"]
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "api": api, "counts": d["counts"], "checks": []}
    c = d["counts"]
    by = {k: sum(1 for r in rows if r["status"] == k) for k in ("pending", "rendering", "failed", "done")}
    ok1 = c["all"] == len(rows) == sum(by.values()) and all(c[k] == by[k] for k in by)
    res["checks"].append({"id": "P1", "ok": ok1, "detail": {"counts": c, "rows_by_status": by, "rows": len(rows)}})
    lanes = {}
    for g in EP.gpu_ids():
        name = EP.lane_name(g)
        try:
            q = _get(EP.url_for_gpu(g) + "/queue", timeout=10)
        except Exception as e:  # noqa: BLE001
            lanes[name] = {"ok": None, "err": str(e)[:120]}
            continue
        # 接口的队列读数最多旧约 7 秒（采集 4 s + 缓存 3 s）：刚进队 15 秒内的不要求已显示；
        # 接口里还显示、队列里已没有的，只要在 ComfyUI 历史里（刚做完）就不算多出来
        now_ms = time.time() * 1000
        items = q.get("queue_running", []) + q.get("queue_pending", [])
        direct = {it[1] for it in items if now_ms - float((it[3] if len(it) > 3 and isinstance(it[3], dict) else {}).get("create_time") or 0) > 15000}
        try:
            hist = set(_get(EP.url_for_gpu(g) + "/history?max_items=40", timeout=15).keys())
        except Exception:  # noqa: BLE001
            hist = set()
        all_q = {it[1] for it in items}
        shown = {r["ids"].get("prompt_id") for r in rows if r["lane"] == name and r["status"] in ("pending", "rendering")
                 and r["source"] in ("comfy", "ns_api") and r["ids"].get("prompt_id")}
        comfy_shown = {r["ids"].get("prompt_id") for r in rows if r["lane"] == name and r["status"] in ("pending", "rendering")
                       and r["source"] == "comfy"}
        # 画布任务在 ComfyUI 出完后还要存版本 / 质检，那几秒 job 仍是“渲染中”但队列里已没有 → 只记录，不算不一致
        post = sorted(shown - direct - comfy_shown)
        post = sorted(set(post) - hist)
        missing, extra = sorted(direct - shown), sorted(comfy_shown - all_q - hist)
        lanes[name] = {"ok": not missing and not extra, "direct": len(direct), "shown": len(shown),
                       "missing": missing[:5], "extra": extra[:5], "ns_api_post_processing": post[:5]}
    reach = [v for v in lanes.values() if v["ok"] is not None]
    res["checks"].append({"id": "P2", "ok": bool(reach) and all(v["ok"] for v in reach), "detail": lanes})
    jobs = _get(f"{jobs_api}/api/jobs")
    direct_n = sum(1 for j in jobs if j.get("state") in ("queued", "running"))
    shown_n = sum(1 for r in rows if r["source"] == "ns_api" and r["status"] in ("pending", "rendering"))
    res["checks"].append({"id": "P3", "ok": direct_n == shown_n, "detail": {"jobs_active_direct": direct_n, "rows_active_ns_api": shown_n}})
    res["ok"] = all(x["ok"] for x in res["checks"])
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8800")
    ap.add_argument("--jobs-api", default="http://127.0.0.1:8800")
    a = ap.parse_args()
    try:
        r = check(a.api, a.jobs_api)
        if not r["ok"]:
            time.sleep(3)
            r = check(a.api, a.jobs_api)
            r["rechecked"] = True
    except Exception as e:  # noqa: BLE001
        print(f"读不到：{e}")
        return 2
    out = ROOT / "data" / "qa" / "render_tasks_parity" / f"{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    for x in r["checks"]:
        print(x["id"], "通过" if x["ok"] else "不一致", json.dumps(x["detail"], ensure_ascii=False)[:300])
    print("结果：", "一致" if r["ok"] else "不一致", out.relative_to(ROOT))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
