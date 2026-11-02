"""V2 运镜 A/B（STYLE-V2，L-127 / L-107：新运镜先 Pika A/B 再进 config/director/camera_moves.yaml）。

调研依据（STYLE-V2 调研，11-02）：Vogue China 2025 Forces of Fashion 子弹时间（影视飓风 60 台 iPhone 弧形阵列 genlock，
https://creativecow.net/media-storms-vogue-bullet-time-production-diary/ ；爱范儿 https://www.ifanr.com/1642209 ）；
高速环绕 / 慢动作急推参照 E! GlamBOT（Bolt 机械臂 + Phantom 1000fps，https://nofilmschool.com/Oscars-GlamBOT-Technical ）。

视频 = 生产同一条图：ns_render.h3_video.build(base="pika_flex")（MiniMax H3 + Pika Flex LoRA，6 步 lcm），只给首帧
（子弹时间 / 环绕不要尾帧锁死机位）；首帧 = V2 调色样张（data/ab/v2_style/grade，lead_f 身份脸 + O1 风衣，非成人）。
打分 = 服务器上生产同一个 score_clip.py（运动 / 硬切 / J4 / SFace 身份 / 分身），判定口径 = camera_moves.yaml ab_criteria
AB1–AB5（tools/director/camera_ab.judge，角色名换成“女主”）；运镜是否真的执行（定格、环绕方向、急推）由总调度看抽帧亲审。
道：只用借来的道（client 前缀 stylev2-）。A/B 总数 ≤ 20。

  python tools/v2style/camera_ab.py run      # 出片 + 打分（已完成的跳过）
  python tools/v2style/camera_ab.py page     # data/review_pages/v2_style/camera.html
"""
from __future__ import annotations

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
for p in ("services/render_router", "services/agent", "packages/schema", "tools/v2style", "tools/director"):
    sys.path.insert(0, str(ROOT / p))
from ns_render import h3_video as HV  # noqa: E402
import common as C  # noqa: E402

OUT = ROOT / "data/ab/v2_style/camera"
RES = OUT / "results.json"
PAGE = ROOT / "data/review_pages/v2_style/camera.html"
CFG = C.cfg()
FACE = C.asset("face")                       # assets_v2/manifest.json，sha 校验
CLIENT = CFG["client_prefix"]
LANES = {k: (v["url"], v["host"], v["outdir"]) for k, v in CFG["lanes"].items()}
VS = CFG["video_score"]
SRV, SRV_REPO, SCORE_HOST = VS["dir"], VS["repo"], VS["host"]
FRAMES = 124            # 17k+5 网格，约 5.2 s @24fps
MAX_ARMS = 20

WHO_EN = ("a 23-year-old Chinese female fashion model with long straight blue hair and a blunt fringe, "
          "wearing a black glossy patent-leather double-breasted belted trench coat")
CONSTRAINTS = ("Her face stays stable and sharp throughout, with no clipping through objects, no duplicate people, "
               "and no on-screen text or watermark.")

# 首帧（grade 样张的 _post.png = 调色前；视频出完后期再统一套 LUT）
FIRST = {
    "F_full": "data/ab/v2_style/grade/fantasy_a/s2_post.png",
    "F_mid": "data/ab/v2_style/grade/fantasy_a/s3_post.png",
    "R_full": "data/ab/v2_style/grade/reality_a/s2_post.png",
    "R_mid": "data/ab/v2_style/grade/reality_a/s3_post.png",
}
SCENE_EN = {
    "F_full": "standing on the riverside promenade of the Bund in Shanghai, the Lujiazui skyline behind her",
    "F_mid": "sitting sideways on the arm of a velvet sofa in an art-deco hotel lobby, brass lamps and marble walls behind her",
    "R_full": "in a narrow Shanghai shikumen lane with laundry poles and weathered brick walls, holding a convenience-store bag",
    "R_mid": "sitting on the edge of a bed in a cramped rented room, cardboard boxes in the corner and a small desk lamp behind her",
}
SOUND = {
    "F_full": "Wind off the river, distant city traffic, the soft creak of patent leather.",
    "F_mid": "Quiet hotel lobby ambience, a faint murmur of distant voices, the soft creak of patent leather.",
    "R_full": "Lane ambience, a distant scooter, footsteps on worn concrete, a plastic bag rustling.",
    "R_mid": "A small room hum, a distant street outside the window, the faint rustle of a paper cup.",
}

# 运镜：id → (中文名, 视觉语言, 运镜句)
MOVES = {
    "bullet_time": ("子弹时间（定格环绕）", "fantasy",
                    "Frozen-moment bullet time: she is completely still like a statue, her hair and the hem of her coat suspended in mid-air, "
                    "while the camera orbits smoothly around her at a constant speed, about ninety degrees over the shot, keeping her centered, "
                    "the background layers sliding past with strong parallax."),
    "orbit_slowmo": ("慢动作环绕", "fantasy",
                     "The camera orbits slowly around her at eye level, about half a circle over the shot, keeping her centered, "
                     "while she moves in slow motion, her hair and coat drifting softly, her gaze following the lens."),
    "whip_orbit": ("高速环绕急停（机械臂式）", "fantasy",
                   "A robotic high-speed camera move: the camera whips in a fast, tight arc from her side to her front within the first second, "
                   "then decelerates sharply and settles into a locked medium close-up, while she moves in super slow motion, hair drifting."),
    "slowmo_snap_push": ("慢动作急推", "fantasy",
                         "Ultra slow-motion shot: she turns her head slowly toward the lens, hair flowing; halfway through, the camera suddenly "
                         "snaps forward in a fast dolly-in from a medium shot to a close-up of her face, then holds still in slow motion."),
    "handheld_follow": ("手持跟拍（现实段）", "reality",
                        "Handheld documentary camera: the camera follows her at shoulder height with a gentle natural sway and small "
                        "breathing movements, real-time speed, staying close to her."),
}
ARMS_PLAN = {   # 每种运镜 3 条：两个首帧 + 同首帧换 seed
    "fantasy": [("F_full", 20261131), ("F_mid", 20261131), ("F_full", 20261132)],
    "reality": [("R_full", 20261131), ("R_mid", 20261131), ("R_full", 20261132)],
}


def prompt_for(move: str, first: str) -> str:
    cam = MOVES[move][2]
    lang = MOVES[move][1]
    style = ("Live-action, cinematic fashion film, rich saturated colour, glossy magazine look"
             if lang == "fantasy" else "Live-action, documentary-style magazine film, natural light, restrained colour")
    return ("For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            f"integrated_multimodal_description: [Shot 1] {style}, the shot begins in the position, framing and lighting "
            f"established by <Picture 1>, {WHO_EN}, {SCENE_EN[first]}. {cam} The movement is already under way in the very first "
            f"frame and carries on continuously. She does not speak. {CONSTRAINTS}\n\n"
            f"overall_soundscape: {SOUND[first]}\n\nnon_diegetic_music: N/A")


def arms() -> list[dict]:
    out = []
    for mv, (_zh, lang, _c) in MOVES.items():
        for first, seed in ARMS_PLAN[lang]:
            out.append({"id": f"{mv}__{first}_s{seed}", "move": mv, "first": first, "seed": seed})
    assert len(out) <= MAX_ARMS, len(out)
    return out


def api(url, path, data=None, ctype="application/json", timeout=120):
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def upload(url: str, p: Path) -> str:
    kf = HV.keyframe_file(p)
    b = "----stylev2" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"stylev2_{kf.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + kf.read_bytes() + \
        (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nstylev2\r\n"
         f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n").encode()
    r = json.loads(api(url, "/upload/image", body, f"multipart/form-data; boundary={b}", timeout=300))
    return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]


def _remote(host, cmd, stdin=None, timeout=2400):
    return C.remote(host, cmd, stdin=stdin, timeout=timeout)


def load_res() -> dict:
    return C.load_json(RES, {})


def save_res(res: dict) -> None:
    C.save_json_atomic(RES, res)


def score(a: dict, host: str, host_path: str) -> dict:
    """在 gpu36 上用生产 score_clip.py 打分（gpu33 出的片先拉回再推到 gpu36）"""
    stem = a["id"]
    loc = OUT / stem
    loc.mkdir(parents=True, exist_ok=True)
    mp4 = loc / f"{stem}.mp4"
    if not mp4.exists():
        mp4.write_bytes(_remote(host, f"cat {host_path}").stdout)
    ref = f"{SRV}/refs/lead_f_face_v1.png"
    _remote(SCORE_HOST, f"mkdir -p {SRV}/refs && cat > {ref}", stdin=(ROOT / FACE).read_bytes())
    _remote(SCORE_HOST, f"cat > {SRV}/{stem}.mp4", stdin=mp4.read_bytes())
    meta = json.dumps({"refs": {"女主": ref}, "prompt": a["prompt"], "frames": FRAMES, "size": "中景"}, ensure_ascii=False)
    meta = meta.replace("'", "'\"'\"'")
    d = SRV
    cmd = (f"cd {SRV_REPO} || exit 1; export PATH={VS['tools_bin']}:$PATH OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 PYTHONUTF8=1; "
           f"nice -n 10 {VS['python']} tools/series10_video/score_clip.py {d}/{stem}.mp4 {d}/{stem}_sheet.jpg "
           f"'{meta}' > {d}/{stem}.score.txt 2> {d}/{stem}.score.err; echo OK")
    _remote(SCORE_HOST, cmd)
    for suf in ("_sheet.jpg", ".score.txt", ".score.err"):
        r = _remote(SCORE_HOST, f"cat {d}/{stem}{suf}")
        if r.returncode == 0:
            (loc / f"{stem}{suf}").write_bytes(r.stdout)
    # 本地抽帧条（0 / 1 / 2 / 3 / 4 / 5 s）
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                    "select='eq(n\\,0)+eq(n\\,24)+eq(n\\,48)+eq(n\\,72)+eq(n\\,96)+eq(n\\,120)',scale=216:378,tile=6x1",
                    "-frames:v", "1", str(loc / f"{stem}_strip.jpg")], capture_output=True, timeout=300)
    st = loc / f"{stem}.score.txt"
    if not st.exists():
        return {"error": "打分文件没拉回"}
    ln = [x for x in st.read_text(encoding="utf-8").splitlines() if x.startswith("{")]
    return json.loads(ln[-1]) if ln else {"error": "无打分输出"}


def judge(sc: dict, size: str) -> dict:
    import camera_ab as CA          # tools/director/camera_ab.py：AB1–AB5 同口径
    CA.WHO = "女主"
    return CA.judge({"score": sc}, want_size=size)


def scan_existing(ids: set[str]) -> dict:
    """各借来的道上：本工具已提交（排队 / 在跑 / 已完成）的同名臂 → {臂 id: (道, prompt_id)}"""
    out = {}
    for ln, (url, _h, _o) in LANES.items():
        q = json.loads(api(url, "/queue", timeout=120))
        hist = json.loads(api(url, "/history?max_items=300", timeout=120))
        items = [(it[1], it[2]) for it in q["queue_running"] + q["queue_pending"]]
        items += [(pid, h.get("prompt", [None, None, {}])[2]) for pid, h in hist.items()
                  if (h.get("status") or {}).get("status_str") != "error"]
        for pid, g in items:
            for n in (g or {}).values():
                pre = str((n.get("inputs") or {}).get("filename_prefix") or "")
                if n.get("class_type") == "SaveVideo" and pre.startswith("stylev2_cam/") and pre[12:] in ids:
                    out[pre[12:]] = (ln, pid)
    return out


def run() -> None:
    res = load_res()
    todo = [a for a in arms() if not (res.get(a["id"]) or {}).get("score")]
    for a in todo:
        if not (ROOT / FIRST[a["first"]]).exists():
            raise SystemExit(f"没有首帧 {FIRST[a['first']]}")
    print("arms", len(todo), flush=True)
    for f in {a["first"] for a in todo}:      # 先在主线程生成关键帧缓存（多线程同时写同一文件在 Windows 上 PermissionError）
        HV.keyframe_file(ROOT / FIRST[f])
    existing = scan_existing({a["id"] for a in todo})
    print("已在道上的", existing, flush=True)
    lk = threading.Lock()

    def worker(lane: str):
        url, host, outdir = LANES[lane]
        ups = {}
        while True:
            with lk:
                if not todo:
                    return
                a = todo.pop(0)
            try:
                if a["first"] not in ups:
                    ups[a["first"]] = upload(url, ROOT / FIRST[a["first"]])
                pr = prompt_for(a["move"], a["first"])
                a = {**a, "prompt": pr}
                purl, pout, phost = url, outdir, host
                if a["id"] in existing:          # 上一次进程已提交过（超时中断）：接着等那一条，不重出
                    ln2, pid = existing[a["id"]]
                    purl, phost, pout = LANES[ln2]
                else:
                    wf = HV.build(pr, ups[a["first"]], None, FRAMES, a["seed"], f"stylev2_cam/{a['id']}", base="pika_flex")
                    body = json.dumps({"prompt": wf, "client_id": CLIENT + uuid.uuid4().hex[:8],
                                       "extra_data": {"ns_tag": {"agent": "STYLE-V2", "kind": "video", "v": 1,
                                                                 "label": f"V2 运镜 A/B {a['id']}（seed {a['seed']}）",
                                                                 "t": round(time.time(), 1)}}}).encode()
                    r = json.loads(api(url, "/prompt", body, timeout=300))
                    if r.get("node_errors"):
                        raise RuntimeError(json.dumps(r["node_errors"], ensure_ascii=False)[:400])
                    pid = r["prompt_id"]
                t0 = time.time()
                host_path = None
                while host_path is None:
                    time.sleep(10)
                    try:
                        h = json.loads(api(purl, f"/history/{pid}", timeout=60))
                    except OSError:   # 同道出片时 ComfyUI 回应慢：单次超时继续等，超过总上限才失败
                        if time.time() - t0 > 3600:
                            raise
                        continue
                    if pid not in h:
                        if time.time() - t0 > 3600:
                            raise TimeoutError("60 min 没出片")
                        continue
                    st = h[pid].get("status", {})
                    if st.get("status_str") == "error":
                        raise RuntimeError(json.dumps(st.get("messages"), ensure_ascii=False)[-400:])
                    for node in h[pid].get("outputs", {}).values():
                        for key in ("images", "videos", "gifs"):
                            for im in node.get(key, []) or []:
                                if str(im.get("filename", "")).endswith(".mp4"):
                                    host_path = "/".join(x for x in (pout, im.get("subfolder"), im["filename"]) if x)
                    if host_path is None and st.get("completed"):
                        raise RuntimeError("no_output")
                secs = round(time.time() - t0, 1)
                sc = score(a, phost, host_path)
                size = {"F_full": "全景", "R_full": "全景", "F_mid": "中景", "R_mid": "中景"}[a["first"]]
                rec = {**a, "lane": lane if purl == url else ln2, "host_path": host_path, "secs": secs, "frames": FRAMES, "base": "pika_flex",
                       "first_frame": FIRST[a["first"]], "score": sc, "verdict": judge(sc, size),
                       "mp4": f"data/ab/v2_style/camera/{a['id']}/{a['id']}.mp4",
                       "strip": f"data/ab/v2_style/camera/{a['id']}/{a['id']}_strip.jpg"}
                with lk:
                    res[a["id"]] = rec
                    save_res(res)
                print(time.strftime("%H:%M:%S"), lane, a["id"], secs, rec["verdict"].get("pass"), rec["verdict"].get("fails"), flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", lane, a["id"], repr(e)[:300], flush=True)
                with lk:
                    res[a["id"]] = {**a, "err": repr(e)[:300]}
                    save_res(res)

    th = [threading.Thread(target=worker, args=(ln,)) for ln in LANES]
    for x in th:
        x.start()
    for x in th:
        x.join()


def measure() -> None:
    """运镜执行量（VIDLAB clipmetrics v4 背景光流机位轨迹，挡掉人脸 / 身体）：全片 + 前 1.2 s / 后段 / 前半 / 后半，
    用来判“机位真的在动、方向和节奏对不对”；主体是否定格看 expr_std / lm_nonrigid（越小越静）"""
    sys.path.insert(0, str(ROOT / "tools/vidlab"))
    import clipmetrics as CM
    res = load_res()
    for k, v in res.items():
        if k.startswith("_") or not v.get("score") or v.get("cm"):
            continue
        mp4 = ROOT / v["mp4"]
        seg = {}
        for name, t0, dur in (("all", 0.0, None), ("head", 0.0, 1.2), ("tail", 1.5, None), ("h1", 0.0, 2.6), ("h2", 2.6, None)):
            a = CM.analyze(mp4, t0=t0, dur=dur, j4=False)
            sm = CM.clip_summary(a)
            seg[name] = {x: sm.get(x) for x in ("cam_speed_med", "cam_path_ps", "cam_net_ps", "cam_coherence", "cam_tx", "cam_ty",
                                                 "cam_zoom", "cam_rot", "expr_std", "lm_nonrigid", "head_std", "cam_gaze")}
        v["cm"] = seg
        save_res(res)
        print(k, json.dumps(seg["all"], ensure_ascii=False), flush=True)


def page() -> None:
    import html
    import os
    res = load_res()
    rel = lambda p: Path(os.path.relpath(ROOT / p, PAGE.parent)).as_posix()  # noqa: E731
    o = ["<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
         "<title>V2 运镜 A/B</title><style>body{background:#111;color:#ddd;font:14px/1.6 system-ui,'Microsoft YaHei';margin:20px}"
         "h1{font-size:20px}h2{font-size:17px;margin-top:26px;border-top:1px solid #333;padding-top:12px}"
         ".row{display:flex;gap:12px;flex-wrap:wrap}.c{width:300px}.c video{width:300px;border-radius:4px;background:#000}"
         ".c img{width:300px}.sm{color:#999;font-size:12px}.ok{color:#7c7}.no{color:#d77}.lang{display:grid;grid-template-columns:1fr 1fr;gap:24px}"
         "@media(max-width:1500px){.lang{grid-template-columns:1fr}}</style></head><body>",
         "<h1>V2 运镜 A/B（Pika：MiniMax H3 + Pika Flex，只给首帧）</h1>",
         "<p class=sm>左 = 幻想段运镜（参照 Vogue China 子弹时间、高速环绕、慢动作急推），右 = 现实段（手持跟拍）。每种运镜 3 条：两张首帧 + 同首帧换 seed。"
         "调研出处见 camera_moves.yaml 对应条目。只放运镜执行到位、通过 AB1–AB5 的片。</p>"]
    o.append("<div class=lang>")
    for lang, title in (("fantasy", "幻想段"), ("reality", "现实段")):
        o.append(f"<div><h2>{title}</h2>")
        for mv, (zh, lg, cam) in MOVES.items():
            if lg != lang:
                continue
            items = [v for v in res.values() if v.get("move") == mv and v.get("score") and v.get("show")]
            stab = res.get("_moves", {}).get(mv, {})
            o.append(f"<h3>{html.escape(zh)} <span class=sm>{mv}</span></h3><div class=sm>{html.escape(stab.get('note', ''))}</div><div class=row>")
            for v in items:
                o.append(f"<div class=c><video controls loop muted preload=metadata src='{rel(v['mp4'])}'></video>"
                         f"<div class=sm>{v['first']} · seed {v['seed']}</div></div>")
            if not items:
                o.append("<div class=sm>（这一种没有稳定出效果的片，不放）</div>")
            o.append("</div>")
        o.append("</div>")
    o.append("</div></body></html>")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text("\n".join(o), encoding="utf-8")
    print(PAGE)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        run()
    elif cmd == "page":
        page()
    elif cmd == "measure":
        measure()
    elif cmd == "list":
        for a in arms():
            print(a["id"])
    else:
        print(__doc__)
