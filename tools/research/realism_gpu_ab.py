"""⤴ 已取消（L-087：项目方选 R0、对现行画面和颜色非常满意；总调度 11-01 17:5x）——不要再跑；scope=ab 跑法可作以后实验的模板。

真人写实 GPU 档 A/B（RESEARCH，R11-12 / R11-13；总调度 fredw-2b 11-01 定方案 ②：scope=ab）。

3 镜（ep01-S1 特写 / S2 中景 / S5 近景，办公室夜景，非亲密）× 3 档：
  G0  现行 frame_v9 重出（对照组）：生产当前首帧的参考图 / 提示词已和现在的编译结果不一样（三镜 refs 都换过身份脸，
      S1 提示词也变了，11-01 17:0x 核对），直接拿它比不干净，所以用同一种子按现在的作业重出一张，不改任何东西
  G1  只改提示词：删系统锐度句 / 写实套话 / “无字幕”，S★ 后缀换成具体光线句（BAKEOFF qa_suffix 同一句）
  G2  G1 + NiceGirls UltraReal Asians 0.6 换掉 krea2（gpu36 已有，不下载）
G0 / G1 / G2 用生产当前首帧的种子，走 ns_render.unified_frame.render_ab（= frame-jobs scope=ab 的同一函数）：
不写 takes.json、不进 auto_current / rescore / 契约账本，图在 data/ab/realism_ab/<shot>/，记录追加 takes.jsonl。

让道（生产优先）：每张图提交前，目标道必须 ① ComfyUI 连续 idle_s 秒没有任何任务（运行 + 排队）；② 不在 PRODUCER
租约 / control.hold_lanes 里；③ 不在 tools/bakeoff/run/hold 里。任一不满足就等；等满 wait_max 秒还没空就放弃这一张。
一道一次只交一张。

用法：
  .venv/Scripts/python.exe -X utf8 tools/research/realism_gpu_ab.py --dry-run       # 只编提示词 + preflight，不连 GPU
  .venv/Scripts/python.exe -X utf8 tools/research/realism_gpu_ab.py --lanes gpu36:0,gpu36:1
  .venv/Scripts/python.exe -X utf8 tools/research/realism_gpu_ab.py --page-only      # 只重做审片页 / 盲看页
"""
from __future__ import annotations

import argparse
import html
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "services/api", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

EXP = "realism_ab"
OUT = ROOT / "data" / "ab" / EXP
PAGE = ROOT / "data" / "review_pages" / EXP
SHOTS = [("ep01-S1", "特写"), ("ep01-S2", "中景"), ("ep01-S5", "近景")]
SSTAR = "专业电影画面，徕卡M 50mm f/2镜头，焦点锐利，微反差强，皮肤纹理清晰，自然高光，暖调通透，干净真实"
NEW_SUFFIX = "竖构图写实照片，50mm 镜头视角，自然光比，光从侧前方落在脸颊和发丝上形成真实的明暗过渡"
# 按长 → 短：同一处只删最长的那种写法
DELETE = ["，面部清晰对焦，五官锐利",
          "，真实皮肤质感，可见细小毛孔与细软绒毛，自然的轻微不对称，眼睛为真实人眼大小",
          "，真实皮肤质感，可见细小毛孔与细软绒毛",
          "，无字幕、无文字、无水印"]
G2_LORA = "civitai/niceasians_qwen21.safetensors"
TIERS = {"g0": "现行 frame_v9（同种子按现在的作业重出）", "g1": "只改提示词（去锐度 / 套话，后缀写具体光线）",
         "g2": "G1 + NiceGirls Asians 0.6 换 krea2"}


def script():
    from ns_schema.script import ScriptImport
    return ScriptImport.model_validate(json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8")))


def current_take(shot: str) -> dict:
    ep, s = shot.split("-")
    d = json.loads((ROOT / "data" / "renders" / ep / s / "takes.json").read_text(encoding="utf-8"))
    n = {"ep01-S1": 14, "ep01-S2": 6, "ep01-S5": 4}.get(shot) or (d.get("active") or {}).get("image")   # 与 CPU 档同一批（钉死）
    return next(t for t in d["takes"] if t.get("stage") == "image" and t.get("n") == n)


def g1_edits(prompt: str) -> list[list[str]]:
    out, p = [], prompt
    for w in DELETE:
        if w in p:
            out.append([w, ""])
            p = p.replace(w, "")
    if SSTAR in p:
        out.append([SSTAR, NEW_SUFFIX])
    return out


def _get(url: str, timeout: float = 8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def lane_blocked(lane: str) -> str | None:
    """不能交的原因；None = 这一刻可以"""
    from ns_render import endpoints as EP
    try:
        q = _get(EP.url_for_gpu(lane) + "/queue")
    except Exception as e:  # noqa: BLE001
        return f"连不上（{type(e).__name__}）"
    if q.get("queue_running") or q.get("queue_pending"):
        return "ComfyUI 有任务"
    for f in (ROOT / "data/producer/leases").glob("*.json"):
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("lane") == lane:
                return f"PRODUCER 租约 {f.stem}"
        except (OSError, ValueError):
            pass
    try:
        ctrl = json.loads((ROOT / "data/producer/control.json").read_text(encoding="utf-8"))
        if lane in (ctrl.get("hold_lanes") or []):
            return "PRODUCER hold_lanes"
    except (OSError, ValueError):
        pass
    hold = ROOT / "tools/bakeoff/run/hold"
    if hold.exists() and EP.url_for_gpu(lane).rsplit(":", 1)[-1] in hold.read_text().split():
        return "BAKEOFF hold"
    return None


def wait_idle(lane: str, idle_s: float, wait_max: float) -> bool:
    t0, since = time.time(), None
    while time.time() - t0 < wait_max:
        why = lane_blocked(lane)
        if why:
            since = None
            print(f"  [{lane}] 让道：{why}", flush=True)
            time.sleep(20)
            continue
        since = since or time.time()
        if time.time() - since >= idle_s:
            return True
        time.sleep(10)
    return False


def lora_available(lane: str, name: str) -> bool:
    from ns_render import endpoints as EP
    try:
        info = _get(EP.url_for_gpu(lane) + "/object_info/LoraLoaderModelOnly", timeout=20)
        return name in info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
    except Exception:  # noqa: BLE001
        return False


def plan() -> list[dict]:
    from ns_render import unified_frame as UF
    sc = script()
    jobs = []
    for shot, size in SHOTS:
        t = current_take(shot)
        job = UF._job_for(sc, shot, UF.project_for(sc), None)
        ed = g1_edits(job["prompt"])
        jobs.append({"shot": shot, "size": size, "seed": t["seed"], "g0": t, "edits": ed})
    return jobs


def run(lanes: list[str], idle_s: float, wait_max: float, dry: bool) -> None:
    from ns_agent import comfy_tag as CT
    from ns_api import jobs as J
    from ns_render import unified_frame as UF
    sc = script()
    done = {(r["shot"], r["tier"]) for r in load_records()}
    for j in plan():
        for tier in ("g0", "g1", "g2"):
            if (j["shot"], tier) in done:
                print(j["shot"], tier, "已有，跳过")
                continue
            ov = {"loras": [{"name": G2_LORA, "strength": 0.6}]} if tier == "g2" else None
            if dry:
                from ns_agent.gen_contract import preflight as PF
                job = UF._job_for(sc, j["shot"], UF.project_for(sc), None)
                p = job["prompt"]
                for a, b in j["edits"]:
                    p = p.replace(a, b)
                req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by")}
                req.update(kind="image", project=job.get("framing_project"), shot_id=job["shot"], prompt=p,
                           scope="bakeoff", suffix_variant=True)
                if tier == "g0":
                    req.update(prompt=job["prompt"], scope=None, suffix_variant=None)
                print(j["shot"], tier, "seed", j["seed"], "改写", 0 if tier == "g0" else len(j["edits"]), "处；preflight",
                      PF.check(req).ok, ov or "")
                continue
            ok = False
            for lane in lanes:
                if tier == "g2" and not lora_available(lane, G2_LORA):
                    print(f"  [{lane}] 没有 {G2_LORA}，换道")
                    continue
                if not wait_idle(lane, idle_s, wait_max):
                    print(f"  [{lane}] 等了 {wait_max:.0f} 秒没空，换道 / 放弃")
                    continue
                c = J._make_client(lane)
                ep_s, sh_s = j["shot"].split("-")
                tag = CT.make("RESEARCH", "bakeoff", episode=int(ep_s[2:]), shot=sh_s, label=f"实验 {EXP}/{tier}")
                rec = UF.render_ab(c, sc, j["shot"], experiment=EXP, tier=tier, seed=j["seed"],
                                   prompt_edits=j["edits"] if tier != "g0" else None,
                                   overrides=ov, tag=tag)
                print(j["shot"], tier, lane, rec["file"], f"{rec['seconds']} s", flush=True)
                ok = True
                break
            if not ok:
                print(j["shot"], tier, "没跑成（所有道都没空 / 缺 LoRA）")


def load_records() -> list[dict]:
    f = OUT / "takes.jsonl"
    if not f.exists():
        return []
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    last = {}
    for r in rows:
        last[(r["shot"], r["tier"])] = r
    return list(last.values())


def metrics(path: Path) -> dict:
    from PIL import Image
    from ns_agent.gen_contract.metrics import face_texture, texture
    sys.path.insert(0, str(ROOT / "tools" / "research"))
    import realism_ab as RA
    im = Image.open(path).convert("RGB")
    fb = RA.face_box(im)
    m = {"lap_full": texture(im, fb)["lap_full"], "halo": RA.halo(im)}
    if fb:
        m.update(face_texture(im, fb) or {})
    return m


def pages() -> None:
    recs = {(r["shot"], r["tier"]): r for r in load_records()}
    rows = []
    for shot, size in SHOTS:
        files = {k: recs[(shot, k)]["file"] for k in ("g0", "g1", "g2") if (shot, k) in recs}
        rows.append({"shot": shot, "size": size, "files": files,
                     "metrics": {k: metrics(ROOT / "data" / f) for k, f in files.items()}})
    (OUT / "gpu_metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    css = (":root{--bg:#f6f5f2;--fg:#1d1d1b;--mut:#6b6a66;--card:#fff;--line:#dedbd3;--acc:#9a5b00}"
           "@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe7;--mut:#a3a19b;--card:#21211f;--line:#3a3935;--acc:#f0b55a}}"
           "body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,'Microsoft YaHei',sans-serif}"
           "main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px}h2{font-size:18px;margin:26px 0 8px}"
           ".mut{color:var(--mut)}.row{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.row img{width:100%;border-radius:6px}"
           ".tag{font-weight:600;color:var(--acc)}table{border-collapse:collapse;font-size:13px;display:block;overflow-x:auto}"
           "td,th{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right}td:first-child,th:first-child{text-align:left}"
           "@media (max-width:640px){.row{grid-template-columns:1fr}}")
    head = ("<!doctype html><html lang='zh'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{{t}}</title><style>{css}</style></head><body><main>")
    rel = "../.."
    # 1) 带档名的工作页（给总调度 / 复核）
    keys = ["lap_full", "halo", "face_hf", "face_lap", "p_plastic", "face_oil"]
    P1 = [head.replace("{t}", "写实 GPU A/B"), "<h1>写实 GPU 档 A/B（G0 / G1 / G2，带档名）</h1>",
          "<p class='mut'>同镜同种子，三档都走 scope=ab（不进版本表）。档的含义："
          + "；".join(f"{k.upper()} {html.escape(v)}" for k, v in TIERS.items()) + "。给项目方看用 blind.html。</p>"]
    for r in rows:
        P1.append(f"<h2>{r['shot']} · {r['size']}</h2><div class='row'>" + "".join(
            f"<div><div class='tag'>{k.upper()}</div><img loading='lazy' src='{rel}/{f}' alt='{k}'></div>"
            for k, f in r["files"].items()) + "</div>")
        P1.append("<table><tr><th>档</th>" + "".join(f"<th>{c}</th>" for c in keys) + "</tr>" + "".join(
            f"<tr><td>{k.upper()}</td>" + "".join(f"<td>{r['metrics'][k].get(c, '—')}</td>" for c in keys) + "</tr>"
            for k in r["files"]) + "</table>")
    P1.append("</main></body></html>")
    (PAGE / "gpu.html").write_text("\n".join(P1), encoding="utf-8")
    # 2) 不标名盲看页：每镜三张随机排成 A / B / C，答案只写在 data/ab/realism_ab/blind_key.json
    rnd = random.Random(20261101)
    key, P2 = {}, [head.replace("{t}", "写实盲看"), "<h1>哪一张最像真人照片？</h1>",
                   "<p class='mut'>每一行是同一个镜头的三个版本，顺序是随机的。只看“像不像真人拍的”：皮肤、头发、光。</p>"]
    for r in rows:
        if len(r["files"]) < 3:
            continue
        order = list(r["files"])
        rnd.shuffle(order)
        key[r["shot"]] = dict(zip("ABC", order))
        P2.append(f"<h2>镜头 {SHOTS.index((r['shot'], r['size'])) + 1}</h2><div class='row'>" + "".join(
            f"<div><div class='tag'>{L}</div><img loading='lazy' src='{rel}/{r['files'][k]}' alt='{L}'></div>"
            for L, k in zip("ABC", order)) + "</div>")
    P2.append("</main></body></html>")
    (PAGE / "blind.html").write_text("\n".join(P2), encoding="utf-8")
    (OUT / "blind_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print("页面：", PAGE / "gpu.html", PAGE / "blind.html", "盲看完整镜数", len(key))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", default="gpu36:0,gpu36:1")
    ap.add_argument("--idle", type=float, default=180)
    ap.add_argument("--wait-max", type=float, default=1800)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--page-only", action="store_true")
    a = ap.parse_args()
    if not a.page_only:
        run([x.strip() for x in a.lanes.split(",") if x.strip()], a.idle, a.wait_max, a.dry_run)
    if not a.dry_run:
        pages()


if __name__ == "__main__":
    main()
