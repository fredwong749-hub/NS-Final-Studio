"""V2 调色候选样张（STYLE-V2，L-127）：两套视觉语言（幻想 / 现实）× 各 3 个候选 × 各 3 张中性样张。

参考只用 V2 资产包（assets_v2/manifest.json）：lead_f 身份脸 + O1 风衣（server_ok）。不用 O2 / O3 / J1 / J2，不用任何 V1 资产。
出图 = 生产同一条图（ns_render.workflows.qwen_edit 多参考 ref_resolution 0 / 不裁 + image_params.apply 预设 v2_editorial_*），
后处理 = image_params.post_file（lanczos 缩回 + USM）→ looks.apply（ffmpeg lut3d，v2_*.cube）→ 4K（gpu33 SeedVR2 3B
scripts/upscale_4k.py shot，config/vqa.json upscale_4k：2160×3840）。
道：只用借来的道（tools/debug/lanes.py lend，client 前缀 stylev2-）。

  python tools/v2style/grade_ab.py gen      # 出图 + 后处理 + LUT（已完成的跳过）
  python tools/v2style/grade_ab.py score    # 身份 ArcFace（出图那台机器上 score_remote.py）
  python tools/v2style/grade_ab.py up4k     # 4K
  python tools/v2style/grade_ab.py page     # data/review_pages/v2_style/grade.html
输出：data/ab/v2_style/grade/<look>/<scene>{.png,_post.png,_graded.png,_4k.png}，results.json
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/v2style"):
    sys.path.insert(0, str(ROOT / p))
from ns_render import image_params as IP  # noqa: E402
from ns_render import workflows as W  # noqa: E402
import looks as L  # noqa: E402
import common as C  # noqa: E402

OUT = ROOT / "data/ab/v2_style/grade"
RES = OUT / "results.json"
PAGE = ROOT / "data/review_pages/v2_style/grade.html"
CFG = C.cfg()
FACE = C.asset("face")                       # assets_v2/manifest.json，sha 校验
TRENCH = C.asset("garment", look="O1")       # O1 风衣（server_ok）；O2 / O3 / J1 / J2 不用
CLIENT = CFG["client_prefix"]
LANES = {k: v["url"] for k, v in CFG["lanes"].items()}
OUTDIR = {k: v["outdir"] for k, v in CFG["lanes"].items()}
R36 = CFG["image_score"]["host_dir"]
SCORE_PY = CFG["image_score"]["python"]
UP = CFG["upscale_4k"]
UP_DIR, NS_STUDIO, UP_HOST, UP_GPU = UP["work_dir"], UP["ns_studio"], UP["host"], UP["gpu"]

REF_CLAUSE = ("图1是女主的脸部参考（只取脸和发型）。图2是女主的服装参考：黑色漆皮双排扣长风衣（系腰带），"
              "只取服装的款式、颜色、材质和细节，陈列架、灯框和背景不取。")
WHO = "【女主】23岁中国成年女性模特，蓝色长直发，齐刘海，真人写实，身穿黑色漆皮双排扣长风衣（系腰带）"
SCENES = {
    "fantasy": {
        "s1": ("特写", "特写构图：只拍头部与肩颈，脸部约占画面六成，头顶到下巴完整入画，风衣领口立起。她直视镜头，表情冷艳自信，背景是无缝背景纸"),
        "s2": ("全身", "全身构图：头顶到鞋尖完整入画，脚穿透明尖头细高跟。她站在上海外滩江边步道上，身后是黄浦江和陆家嘴天际线，风衣下摆被风吹起，单手插在口袋里，姿态挺拔"),
        "s3": ("中景", "中景构图：膝盖以上入画。她侧身坐在装饰艺术风格酒店大堂的丝绒沙发扶手上，身后是黄铜灯具和大理石墙面，目光看向画面右侧"),
    },
    "reality": {
        "s1": ("特写", "特写构图：只拍头部与肩颈，脸部约占画面六成，头顶到下巴完整入画。她站在老式公寓的窗边，侧脸看向窗外，神情疲惫、若有所思，窗玻璃上有一层水汽"),
        "s2": ("全身", "全身构图：头顶到鞋尖完整入画，脚穿透明尖头细高跟。她走在上海石库门弄堂里，两侧是晾衣竿和斑驳的砖墙，手里拎着便利店塑料袋，低头看手机"),
        "s3": ("中景", "中景构图：膝盖以上入画。她坐在狭小出租屋的床沿，身后是堆着纸箱的墙角和一盏小台灯，风衣没有脱，双手捧着一杯外卖咖啡，目光落在地板上"),
    },
}
SEEDS = {"s1": 20261127, "s2": 20261128, "s3": 20261129}
NO_TEXT = "无字幕、无文字、无水印"


def prompt_for(look: str, scene: str) -> str:
    lang = L.LOOKS[look]["lang"]
    size, body = SCENES[lang][scene]
    return f"{REF_CLAUSE}{body}，{WHO}，{size}，面部清晰，五官可辨，衣装完整，{NO_TEXT}"


def api(url, path, data=None, ctype="application/json", timeout=120):
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def prep_ref(rel: str) -> Path:
    """参考图本地预缩放到长边 768（同生产 refcrops 口径：ref_resolution 0 原尺寸送入编码器）"""
    from PIL import Image
    dst = OUT / "refs" / (Path(rel).stem + "_768.png")
    if not dst.exists():
        im = Image.open(ROOT / rel).convert("RGB")
        s = 768 / max(im.size)
        im = im.resize((round(im.size[0] * s), round(im.size[1] * s)), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst)
    return dst


def upload(url: str, p: Path) -> str:
    b = "----stylev2" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"stylev2_{p.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + p.read_bytes() + \
        (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nstylev2\r\n"
         f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n").encode()
    r = json.loads(api(url, "/upload/image", body, f"multipart/form-data; boundary={b}", timeout=300))
    return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]


def build(look: str, scene: str, names: list[str]) -> tuple[dict, dict, str]:
    eff = IP.resolve(f"v2_editorial_{look}", None)
    pr = prompt_for(look, scene)
    wf = W.qwen_edit(pr, "", names, 768, 1344, SEEDS[scene], f"stylev2/{look}_{scene}", m=W.QwenModel(), loras=[],
                     ref_resolution=0, crop=False)
    wf = IP.apply(wf, eff, set())
    sent = next((n["inputs"].get("prompt") for n in wf.values() if "TextEncodeQwenImage" in n.get("class_type", "")), pr)
    return wf, eff, sent


def load_res() -> dict:
    return C.load_json(RES, {})


def save_res(res: dict) -> None:
    C.save_json_atomic(RES, res)


def gen() -> None:
    res = load_res()
    tasks = [(lk, sc) for lk in L.LOOKS for sc in SEEDS if not (res.get(f"{lk}/{sc}") or {}).get("graded")]
    print("tasks", len(tasks), flush=True)
    refs = [prep_ref(FACE), prep_ref(TRENCH)]
    lk_ = threading.Lock()

    def worker(lane: str, url: str):
        names = [upload(url, r) for r in refs]
        while True:
            with lk_:
                if not tasks:
                    return
                look, sc = tasks.pop(0)
            key = f"{look}/{sc}"
            try:
                wf, eff, sent = build(look, sc, names)
                lab = f"V2 调色样张 {L.LOOKS[look]['label']} · {SCENES[L.LOOKS[look]['lang']][sc][0]} · seed {SEEDS[sc]}"
                body = json.dumps({"prompt": wf, "client_id": CLIENT + uuid.uuid4().hex[:8],
                                   "extra_data": {"ns_tag": {"agent": "STYLE-V2", "kind": "image", "v": 1, "label": lab,
                                                             "t": round(time.time(), 1)}}}).encode()
                pid = json.loads(api(url, "/prompt", body, timeout=300))["prompt_id"]
                t0 = time.time()
                dest = OUT / look / f"{sc}.png"
                host_path = None
                while True:
                    time.sleep(4)
                    try:   # 同道在出视频时 ComfyUI 回应慢：单次超时不算失败，继续等（总上限 20 min）
                        h = json.loads(api(url, f"/history/{pid}", timeout=60))
                    except OSError:
                        if time.time() - t0 > 1200:
                            raise
                        continue
                    if pid not in h:
                        if time.time() - t0 > 1200:
                            raise TimeoutError("20 min 没出图")
                        continue
                    st = h[pid].get("status", {})
                    if st.get("status_str") == "error":
                        raise RuntimeError(json.dumps(st.get("messages", ""))[-300:])
                    ims = [im for nd in h[pid].get("outputs", {}).values() for im in nd.get("images", [])]
                    if ims:
                        im = ims[0]
                        q = f"/view?filename={urllib.parse.quote(im['filename'])}&subfolder={urllib.parse.quote(im['subfolder'])}&type={im['type']}"
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(api(url, q, timeout=180))
                        host_path = "/".join(x for x in (OUTDIR[lane], im["subfolder"], im["filename"]) if x)
                        break
                post = IP.post_file(dest, eff)
                postp = Path(post["path"]) if post else dest
                graded = OUT / look / f"{sc}_graded.png"
                L.apply(postp, look, graded)
                rec = {"look": look, "scene": sc, "lane": lane, "seed": SEEDS[sc], "prompt": sent,
                       "refs": [FACE, TRENCH], "preset": f"v2_editorial_{look}", "lut": f"config/post/luts/v2_{look}.cube",
                       "raw": dest.relative_to(ROOT).as_posix(), "post": postp.relative_to(ROOT).as_posix(),
                       "post_steps": (post or {}).get("steps"), "graded": graded.relative_to(ROOT).as_posix(),
                       "host_path": host_path, "secs": round(time.time() - t0, 1)}
                with lk_:
                    res[key] = rec
                    save_res(res)
                print(time.strftime("%H:%M:%S"), lane, key, rec["secs"], flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", lane, key, repr(e)[:300], flush=True)
                with lk_:
                    res[key] = {"look": look, "scene": sc, "err": repr(e)[:300]}
                    save_res(res)

    th = [threading.Thread(target=worker, args=(n, u)) for n, u in LANES.items()]
    for x in th:
        x.start()
    for x in th:
        x.join()


def _remote(host: str, cmd: str, stdin: bytes | None = None, timeout: int = 1800):
    return C.remote(host, cmd, stdin=stdin, timeout=timeout)


def score() -> None:
    """身份：ArcFace 余弦（score_remote.py，与生产出图质检同一脚本；参考 = lead_f 身份脸）"""
    res = load_res()
    by_host: dict[str, list] = {}
    for k, v in res.items():
        if v.get("host_path"):
            by_host.setdefault(v["lane"].split(":")[0], []).append({"id": "frame:" + k, "path": v["host_path"]})
    face_bytes = (ROOT / FACE).read_bytes()
    for host, items in by_host.items():
        ref = f"{R36}/refs/v2_lead_f_face_v1.png"
        r = _remote(host, f"mkdir -p {R36}/refs && cat > {ref}", stdin=face_bytes)
        if r.returncode:
            print("upload ref fail", host, r.stderr[-200:])
            continue
        man = json.dumps({"refs": {"lead_f": [ref]}, "items": items}).encode()
        r = _remote(host, f"cd {R36} || exit 1; {SCORE_PY} score_remote.py - 2>/dev/null", stdin=man)
        out = [ln for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("{")]
        if not out:
            print("score fail", host, r.stderr.decode("utf-8", "replace")[-300:])
            continue
        d = json.loads(out[-1])
        emb = (d.get("ref_emb") or {}).get("lead_f")
        for it in items:
            q = (d["items"].get(it["id"]) or {})
            fs = q.get("faces", [])
            k = it["id"][len("frame:"):]
            sims = []
            for f in fs:
                if emb and f.get("emb"):
                    import numpy as np
                    a, b = np.array(f["emb"]), np.array(emb)
                    sims.append(round(float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b))), 3))
            res[k]["faces"] = len(fs)
            res[k]["id_sim"] = max(sims) if sims else None
            res[k]["text"] = [t.get("text") for t in q.get("text", [])]
            print(k, len(fs), res[k]["id_sim"], res[k]["text"])
    save_res(res)


def up4k(only: list[str] | None = None) -> None:
    """4K：静帧 → 1 s 24 fps 无损片 → gpu33 scripts/upscale_4k.py shot（SeedVR2 3B，GPU0 = 借来的道）→ 取中间帧 PNG"""
    res = load_res()
    keys = [k for k, v in res.items() if v.get("graded") and not v.get("k4") and (not only or k in only)]
    for k in keys:
        v = res[k]
        name = k.replace("/", "_")
        src = ROOT / v["graded"]
        clip = OUT / "4k_work" / f"{name}.mp4"
        clip.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(src), "-t", "1", "-r", "24",
                        "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(clip)], check=True, timeout=300)
        rclip = f"{UP_DIR}/{name}.mp4"
        r = _remote(UP_HOST, f"mkdir -p {UP_DIR} && cat > {rclip}", stdin=clip.read_bytes())
        if r.returncode:
            print("upload fail", k, r.stderr[-200:])
            continue
        t0 = time.time()
        r = _remote(UP_HOST, f"cd {NS_STUDIO} && UPSCALE_ALLOW_IDLE=1 .venv/bin/python scripts/upscale_4k.py shot {rclip} "
                         f"--out {UP_DIR}/{name} --gpu {UP_GPU} --no-wait 2>&1 | tail -n 25", timeout=3600)
        log = r.stdout.decode("utf-8", "replace")
        ls = _remote(UP_HOST, f"ls {UP_DIR}/{name}/*.4k.mp4 {UP_DIR}/{name}/*4k*.mp4 2>/dev/null | head -1")
        rp = ls.stdout.decode().strip().splitlines()
        if not rp:
            print("4k fail", k, log[-800:])
            v["k4_err"] = log[-500:]
            save_res(res)
            continue
        got = _remote(UP_HOST, f"cat {rp[0]}")
        mp4 = OUT / "4k_work" / f"{name}.4k.mp4"
        mp4.write_bytes(got.stdout)
        png = ROOT / v["graded"].replace("_graded.png", "_4k.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(mp4), "-frames:v", "1", str(png)], check=True, timeout=300)
        pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                             "-of", "csv=p=0", str(png)], capture_output=True, text=True, timeout=60)
        v["k4"] = png.relative_to(ROOT).as_posix()
        v["k4_size"] = pr.stdout.strip()
        v["k4_secs"] = round(time.time() - t0, 1)
        v["k4_engine"] = f"{UP_HOST} SeedVR2 3B（scripts/upscale_4k.py shot --gpu {UP_GPU}）"
        v["k4_log_tail"] = log[-400:]
        save_res(res)
        print(k, v["k4_size"], v["k4_secs"], flush=True)


def page() -> None:
    import html
    res = load_res()
    rel = lambda p: Path(__import__("os").path.relpath(ROOT / p, PAGE.parent)).as_posix()  # noqa: E731
    o = ["<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
         "<title>V2 调色候选</title><style>body{background:#111;color:#ddd;font:14px/1.6 system-ui,'Microsoft YaHei';margin:20px}"
         "h1{font-size:20px}h2{font-size:17px;margin-top:28px;border-top:1px solid #333;padding-top:14px}"
         ".row{display:flex;gap:10px;flex-wrap:wrap}.c{width:300px}.c img{width:300px;border-radius:4px;display:block}"
         ".sm{color:#999;font-size:12px}.cand{margin:14px 0 22px}.lang{display:grid;grid-template-columns:1fr 1fr;gap:24px}"
         "@media(max-width:1500px){.lang{grid-template-columns:1fr}}</style></head><body>",
         "<h1>V2 调色预设候选（幻想 / 现实 两套视觉语言并排）</h1>",
         "<p class=sm>主题：上海时尚模特的幻想和现实的挣扎。左 = 幻想段（时尚大片、艳丽浓郁），右 = 现实段（冷一些、纪实手持感，仍是杂志质感）。"
         "每套 3 个候选，每个候选同一组 3 张中性样张（同 seed，只换风格后缀 + LUT）。点图看 4K 原图（2160×3840）。"
         "参考只用 V2 女主身份脸 + O1 风衣。</p><div class=lang>"]
    for lang, title in (("fantasy", "幻想段"), ("reality", "现实段")):
        o.append(f"<div><h2>{title}</h2>")
        for look, lk in L.LOOKS.items():
            if lk["lang"] != lang:
                continue
            o.append(f"<div class=cand><b>{html.escape(lk['label'])}</b>　<span class=sm>预设 v2_editorial_{look} · LUT v2_{look}.cube</span>"
                     f"<div class=sm>风格后缀：{html.escape(L.SUFFIX[look])}</div><div class=row>")
            for sc in SEEDS:
                v = res.get(f"{look}/{sc}") or {}
                if not v.get("graded") or v.get("hide"):
                    continue
                big = v.get("k4") or v["graded"]
                o.append(f"<div class=c><a href='{rel(big)}' target=_blank><img loading=lazy src='{rel(v['graded'])}'></a>"
                         f"<div class=sm>{SCENES[lang][sc][0]} · {'4K ' + v['k4_size'].replace(',', '×') if v.get('k4_size') else '768×1344'}</div></div>")
            o.append("</div></div>")
        o.append("</div>")
    o.append("</div></body></html>")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text("\n".join(o), encoding="utf-8")
    print(PAGE)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"gen": gen, "score": score, "page": page}.get(cmd, lambda: None)() if cmd != "up4k" else up4k(sys.argv[2:] or None)
    if cmd not in ("gen", "score", "page", "up4k"):
        print(__doc__)
