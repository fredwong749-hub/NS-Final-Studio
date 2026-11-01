"""UIAUDIT：后端每集每镜 first_frame / last_frame_target / video 是否互不相同、文件是否可取（只读 GET）。
用法：python api_distinct.py out.json
"""
import json, sys, urllib.request, urllib.parse, collections

API = "http://127.0.0.1:8800"


def get(p):
    with urllib.request.urlopen(API + p, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def head(url):
    if not url:
        return None
    u = url if url.startswith("http") else API + url
    u = urllib.parse.quote(u, safe=":/?&=%#")
    try:
        req = urllib.request.Request(u, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except Exception as e:
        return str(getattr(e, "code", e))[:40]


def pick(v):
    if isinstance(v, dict):
        return v.get("url") or v.get("path") or v.get("file")
    return v


summ = get("/api/episodes/summary")
out = {"episodes": []}
for ep in summ["episodes"]:
    n = ep["number"]
    d = get(f"/api/episodes/{n}")
    shots = d.get("shots", [])
    rows = []
    for s in shots:
        ff = pick(s.get("first_frame"))
        lf = pick(s.get("last_frame_target") or s.get("last_frame"))
        vd = pick(s.get("video"))
        rows.append({"id": s.get("id"), "ff": ff, "lf": lf, "video": vd,
                     "ff_http": head(ff), "lf_http": head(lf), "video_http": head(vd)})
    dup = {}
    for k in ("ff", "lf", "video"):
        c = collections.Counter(r[k] for r in rows if r[k])
        dup[k] = {u: n_ for u, n_ in c.items() if n_ > 1}
    out["episodes"].append({"ep": n, "title": ep.get("title"), "summary": ep.get("summary"), "n_shots": len(rows),
                            "has_ff": sum(1 for r in rows if r["ff"]), "has_lf": sum(1 for r in rows if r["lf"]),
                            "has_video": sum(1 for r in rows if r["video"]),
                            "bad_http": [(r["id"], k, r[k + "_http"]) for r in rows for k in ("ff", "lf", "video") if r[k] and r[k + "_http"] != 200],
                            "dup": dup, "rows": rows})
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for e in out["episodes"]:
    print(f"ep{e['ep']:02d} shots={e['n_shots']} ff={e['has_ff']} lf={e['has_lf']} vid={e['has_video']} summ={e['summary']} bad={len(e['bad_http'])} dup={ {k: len(v) for k, v in e['dup'].items()} }")
