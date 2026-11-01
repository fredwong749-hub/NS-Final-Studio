"""LOCALGPU 追加（总调度 fredw-2b 11-01）：身份参考脸的视线会不会被 Qwen-Image 带进首帧（SCRIPT-RSI / VIDEO-RCA 怀疑，置信度中）。

A = 现行身份脸 data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png（正面看镜头的大头）
B = 同一张设定图 A-s202（ar-f9519334bc）侧视栏裁的侧脸 data/ab/identity_gaze_ab/refs/lin_wan_face_side_A_s202.png
其余全同：first_frame_jobs.json 的作业（提示词、其余参考图、frame_v9 = S★ 参数），同种子；只换 refs[0]。
出图走生产唯一出图路径的 build_graph（ns_render.unified_frame），本机道 laptop:0（127.0.0.1:18388）；scope=ab：
图只进 data/ab/identity_gaze_ab/，不写 takes.json / 契约账本。
度量：gaze_mp（ns_agent.vqa.contract.gaze_mp + config gate.gaze_mp 的 A/T/P，命中 = 高置信度正对镜头）、
YuNet 视线（ns_qc.gaze.image_gaze，暂定阈值）、sface（ns_qc.face SFace 余弦，参考 = 现行身份脸，两组同一参考）。
用法：python tools/localgpu/identity_gaze_ab.py run ep01-S1,ep01-S2,ep01-S5 --seeds job,job+100
      python tools/localgpu/identity_gaze_ab.py page
"""
from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "services/agent", "packages/schema", "services/api", "packages/qc"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

URL = "http://127.0.0.1:18388"
OUT = ROOT / "data/ab/identity_gaze_ab"
PAGE = ROOT / "data/review_pages/identity_gaze_ab"
FACE_A = "data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png"
FACE_B = "data/ab/identity_gaze_ab/refs/lin_wan_face_side_A_s202.png"
ARMS = {"A": FACE_A, "B": FACE_B}
JOBS = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"


def load_job(sid: str) -> dict:
    jobs = json.loads(JOBS.read_text(encoding="utf-8"))["jobs"]
    j = next(x for x in jobs if x["shot"] == sid)
    if j.get("intimate_ep"):
        raise SystemExit(f"{sid} 是亲密镜头，不出")
    if j["refs"][0] != FACE_A:
        raise SystemExit(f"{sid} refs[0] 不是现行林晚身份脸（{j['refs'][0]}），不在本 A/B 范围")
    return j


def seeds_for(job: dict, spec: str) -> list[int]:
    out = []
    for s in spec.split(","):
        s = s.strip()
        out.append(int(job["seed"]) + (int(s[4:]) if s.startswith("job+") else 0) if s.startswith("job") else int(s))
    return out


_FM = {}


def face_models():
    if "m" not in _FM:
        from ns_qc import gaze as GZ
        _FM["m"] = GZ._models()
    return _FM["m"]


def measure(img: Path) -> dict:
    import cv2
    from ns_agent.vqa import contract as VC
    from ns_qc import face as QF
    from ns_qc import gaze as GZ
    bgr = cv2.imread(str(img))
    m = face_models()
    faces = VC.gaze_mp(img)
    g = VC.gate_cfg().get("gaze_mp") or {}
    A, T, P = float(g.get("A", 0.3)), float(g.get("T", 0.05)), float(g.get("P", 0.12))
    hits = [f for f in faces or [] if abs(A * f["yaw_n"] + f["eye_x"]) <= T and f["pitch_n"] <= P]
    big = sorted(faces or [], key=lambda f: -(f.get("box") or [0, 0, 0, 0])[3] if f.get("box") else 0)
    yg = GZ.image_gaze(bgr, m)
    ref = cv2.imread(str(ROOT / FACE_A))
    sf = None
    if m is not None:
        fr, fi = QF.largest(m.faces(ref)), QF.largest(m.faces(bgr))
        if fr is not None and fi is not None and float(fi[3]) >= QF.MIN_FACE_PX:
            sf = round(QF.cosine(m.embed(ref, fr), m.embed(bgr, fi)), 3)
    return {"gaze_mp_faces": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items() if k in ("yaw_n", "pitch_n", "eye_x", "gaze_x")}
                              for f in (faces or [])][:3],
            "gaze_mp_measured": faces is not None and len(faces) > 0, "gaze_mp_hit": bool(hits),
            "gaze_mp_score": round(abs(A * big[0]["yaw_n"] + big[0]["eye_x"]), 3) if big else None,
            "gate": {"A": A, "T": T, "P": P}, "yunet_gaze": yg.get("status"), "sface_vs_face_A": sf}


def render(job: dict, arm: str, seed: int) -> dict:
    from ns_render import image_params as IP
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyClient
    sid = job["shot"]
    j = {**job, "refs": [ARMS[arm], *job["refs"][1:]]}
    d = OUT / sid
    d.mkdir(parents=True, exist_ok=True)
    client = ComfyClient(URL)
    up = lambda p: client.upload_image(p, subfolder="ns_ab/identity_gaze_ab")  # noqa: E731
    wf, eff, sent = UF.build_graph(j, seed, up, f"ns_ab/identity_gaze_ab/{sid}_{arm}_s{seed}")
    t0 = time.time()
    entry, secs = client.run(wf, timeout_s=1800)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
    raw = d / f"{sid}_{arm}_s{seed}_raw.png"
    client.download(item, raw)
    post = IP.post_file(raw, eff)
    return {"file": str(Path(post["path"]).relative_to(ROOT)).replace("\\", "/"), "raw": str(raw.relative_to(ROOT)).replace("\\", "/"),
            "comfy_s": round(secs, 1), "wall_s": round(time.time() - t0, 1), "preset": job.get("preset") or UF.preset_id(),
            "loras": eff.get("loras"), "prompt_sha": __import__("hashlib").sha256(sent.encode()).hexdigest()[:12]}


def run(shots: list[str], seed_spec: str) -> None:
    log = OUT / "takes.jsonl"
    done = set()
    if log.exists():
        for ln in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            done.add((r["shot"], r["arm"], r["seed"]))
    for sid in shots:
        job = load_job(sid)
        for seed in seeds_for(job, seed_spec):
            for arm in ("A", "B"):
                if (sid, arm, seed) in done:
                    continue
                r = {"scope": "ab", "experiment": "identity_gaze_ab", "shot": sid, "arm": arm, "seed": seed, "face_ref": ARMS[arm],
                     **render(job, arm, seed)}
                r["metrics"] = measure(ROOT / r["file"])
                r["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                print(json.dumps({k: r[k] for k in ("shot", "arm", "seed", "comfy_s")} | r["metrics"], ensure_ascii=False))


def summary(rows: list[dict]) -> dict:
    out = {}
    for arm in ("A", "B"):
        rs = [r for r in rows if r["arm"] == arm]
        meas = [r for r in rs if r["metrics"]["gaze_mp_measured"]]
        sf = [r["metrics"]["sface_vs_face_A"] for r in rs if r["metrics"]["sface_vs_face_A"] is not None]
        out[arm] = {"n": len(rs), "gaze_mp_measured": len(meas), "gaze_mp_hits": sum(r["metrics"]["gaze_mp_hit"] for r in meas),
                    "yunet_cam": sum(r["metrics"]["yunet_gaze"] == "疑似看镜头" for r in rs),
                    "yunet_measured": sum(r["metrics"]["yunet_gaze"] in ("疑似看镜头", "视线离轴") for r in rs),
                    "sface_mean": round(sum(sf) / len(sf), 3) if sf else None, "sface_min": min(sf) if sf else None,
                    "sface_n": len(sf)}
    return out


def page() -> Path:
    rows = [json.loads(x) for x in (OUT / "takes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    PAGE.mkdir(parents=True, exist_ok=True)
    s = summary(rows)
    (PAGE / "summary.json").write_text(json.dumps({"summary": s, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    rel = lambda p: "../../../" + p  # noqa: E731  data/review_pages/identity_gaze_ab → 仓库根
    e = html.escape
    pairs: dict = {}
    for r in rows:
        pairs.setdefault((r["shot"], r["seed"]), {})[r["arm"]] = r

    def cell(r):
        if not r:
            return "<td>—</td>"
        m = r["metrics"]
        hit = "命中（正对镜头）" if m["gaze_mp_hit"] else ("未命中" if m["gaze_mp_measured"] else "未测")
        return (f"<td><a href='{rel(r['file'])}'><img src='{rel(r['file'])}'></a><div class='m'>gaze_mp：<b>{hit}</b>"
                f"（|A·yaw+eye_x| = {m['gaze_mp_score']}，线 ≤{m['gate']['T']}）<br>YuNet 视线：{e(str(m['yunet_gaze']))}"
                f"<br>sface（对现行身份脸）：<b>{m['sface_vs_face_A']}</b></div></td>")
    trs = "".join(f"<tr><th>{e(k[0])}<br>seed {k[1]}</th>{cell(v.get('A'))}{cell(v.get('B'))}</tr>" for k, v in sorted(pairs.items()))
    srow = "".join(f"<tr><th>{a}</th><td>{v['n']}</td><td>{v['gaze_mp_hits']} / {v['gaze_mp_measured']}</td><td>{v['yunet_cam']} / {v['yunet_measured']}</td>"
                   f"<td>{v['sface_mean']}（最低 {v['sface_min']}，n={v['sface_n']}）</td></tr>" for a, v in s.items())
    doc = f"""<!doctype html><meta charset="utf-8"><title>身份脸视线 A/B（identity_gaze_ab）</title>
<style>body{{font:14px/1.5 system-ui,"Microsoft YaHei";margin:20px;background:#111;color:#ddd}}img{{width:300px;display:block}}
table{{border-collapse:collapse}}td,th{{border:1px solid #444;padding:6px;vertical-align:top}}.m{{font-size:12px;max-width:300px}}
.refs img{{width:160px;display:inline-block;margin-right:10px}}b{{color:#fff}}</style>
<h2>身份参考脸的视线会不会带进首帧？（本机道 laptop:0 · scope=ab · S★ / frame_v9 参数不动）</h2>
<p>同一作业（first_frame_jobs.json 的提示词、造型图、参考板）、同种子，只换图1：
<b>A</b> = 现行身份脸（正面看镜头）；<b>B</b> = 同一张设定图 A-s202 侧视栏裁的侧脸。度量口径：gaze_mp = 看图闸门 Q9 的 MediaPipe 虹膜旁证
（config gate.gaze_mp）；YuNet 视线 = ns_qc.gaze 暂定阈值（只记录）；sface = SFace 余弦，两组都对现行身份脸（项目闸门 Q-D1 线 0.30）。</p>
<div class="refs">A：<img src="{rel(FACE_A)}"> B：<img src="{rel(FACE_B)}"></div>
<h3>汇总</h3><table><tr><th>组</th><th>张数</th><th>gaze_mp 正对镜头 / 测到</th><th>YuNet 疑似看镜头 / 测到</th><th>sface 均值</th></tr>{srow}</table>
<h3>逐张（左 A / 右 B，点图看原尺寸）</h3><table><tr><th></th><th>A 现行正脸</th><th>B 侧脸裁切</th></tr>{trs}</table>
<p>数据：data/ab/identity_gaze_ab/takes.jsonl；脚本：tools/localgpu/identity_gaze_ab.py</p>"""
    (PAGE / "index.html").write_text(doc, encoding="utf-8")
    return PAGE / "index.html"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "run":
        run(sys.argv[2].split(","), sys.argv[sys.argv.index("--seeds") + 1] if "--seeds" in sys.argv else "job")
        print(page())
    else:
        print(page())
