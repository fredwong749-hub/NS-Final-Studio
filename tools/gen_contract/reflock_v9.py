"""REFLOCK 验证第二轮（总调度 11-01）：用总调度认可的 v9 配方重出 3 镜——徕卡 S★（Turbo 8 步、krea2 0.5、无 lin_wan_qi、
1.5× 出图 + lanczos 缩回 + USM）、去头造型图、场景底图（解析器槽位里有就进）。出图图结构 = tools/series10_imggen/imgfix_ab.build
（与 IMGGEN 对照 vR / vN 同一条路径），只换参考与提示词：
  vR  资产参考（ns_agent.asset_refs 默认：双人镜只给主体脸）
  vRb 资产参考 + 双人镜两张脸各占一槽（two_person=both_faces；只 ep01-S4）
  vN  无资产参考（assets=False：只挂身份脸，服装靠文字）
打分：最终图（post 后）scp 到 gpu33 原地 score_remote / hands_remote（参考含 lin_wan@master = 本镜实际挂的母版裁切），本机 Q2 / Q4 / Q7。

    .venv/Scripts/python.exe tools/gen_contract/reflock_v9.py [--render] [--score]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/series10_imggen", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))

RUN = ROOT / "data/pipeline/runs/series10_v1"
OUT = RUN / "images" / "reflock_val" / "v9"
STATE = OUT / "state.json"
LANE, URL = "gpu33:1", "http://127.0.0.1:18189"
SHOTS = ("ep01-S3", "ep01-S1", "ep01-S4")
SEEDS = (20261311, 20261312)


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def jobs():
    import image_jobs as IJ
    from ns_agent import asset_refs as AR
    prod, bible = IJ.production_globals(), IJ.load_bible()
    __import__("os").environ.setdefault("NS_ALLOW_P4_SOURCE", "1")   # CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：标定 / 对照实验复现当时 P4 稿出的图，属调研用途
    si, ep = IJ.load_episode(RUN / "ep01" / "P4_ep01.md")
    g = IJ.merged_globals(si.globals, prod)
    out = []
    for sid in SHOTS:
        shot = next(s for s in ep.shots if f"ep01-S{s.index}" == sid)
        on = [c.name for c in shot.cast if c.presence == "在画"]
        faces = [IJ.CORE_FACES[n] for n in on if n in IJ.CORE_FACES]
        vs = [("vR", {}), ("vN", None)] + ([("vRb", {"two_person": "both_faces"})] if len(on) > 1 else [])
        for vid, kw in vs:
            if kw is None:
                prompt, c, _, _ = IJ.frame_prompt_full(ep, shot, g, faces, "series10_v1", bible, assets=False)
                refs, rec = faces, None
            else:
                prompt, c, _, _ = IJ.frame_prompt_full(ep, shot, g, [], "series10_v1", bible)     # 正文 + S★ 后缀
                sr, plan = AR.plan_for("series10_v1", ep, shot, "qwen_image_2.1", **kw)
                body = prompt[len(AR.plan_for("series10_v1", ep, shot, "qwen_image_2.1")[1].prompt_prefix):]
                prompt, refs, rec = plan.prompt_prefix + body, plan.files, AR.record(sr, plan)
            for seed in SEEDS:
                out.append({"id": f"{sid}_{vid}_s{seed}", "shot": sid, "variant": vid, "seed": seed, "prompt": prompt,
                            "refs": refs, "asset_refs": rec, "cast": IJ.cast_of(shot), "loras": [["krea2_film_texture_qwen21.safetensors", 0.5]],
                            "compiled_by": "tools/pipeline/image_jobs.py → ns_agent.compiler.compile_shot",
                            "framing_project": "series10_v1", "recipe": "v9：leica_sstar（imgfix_ab.build sstar，无 lin_wan_qi）"})
    return out


def render(js):
    import imgfix_ab as FX
    import imggen as IG
    from ns_render import image_params as IP
    st = jl(STATE, {}) or {}
    for j in js:
        if st.get(j["id"], {}).get("file"):
            continue
        o = {"prompt": j["prompt"], "sstar": [], "refs": j["refs"], "no_suffix": True}
        g, eff, prompt = FX.build(j, None, o, j["seed"], URL, f"reflock_v9/{j['id']}")
        c = IG.Lane(LANE, URL)
        pid = c.submit(g, front=True)
        t0 = time.time()
        dest = OUT / f"{j['id']}_raw.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        while True:
            time.sleep(5)
            r = c.fetch(pid, dest)
            if r:
                break
        final = dest
        post = IP.post_file(dest, eff) if eff and r == "ok" else None
        if post:
            final = Path(post["path"])
        st[j["id"]] = {"status": r, "file": str(final.relative_to(ROOT)).replace("\\", "/"), "secs": round(time.time() - t0, 1),
                       "sent_prompt": prompt}
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        print(time.strftime("%H:%M:%S"), "done", j["id"], r, round(time.time() - t0), flush=True)


def score(js):
    import image_jobs as IJ
    import remote_score as RS
    from ns_agent.gen_contract import postflight as PO
    from ns_agent.gen_contract import preflight as PF
    st = jl(STATE, {})
    # 出图机器上原地打分（K-OPS-122，scp 经跳板不稳）：ComfyUI 原始输出（1.5× 出图），脸框按最终图宽换算
    ls = RS.ssh("gpu33", "ls /root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu1/reflock_v9/").stdout.split()
    host = {}
    for j in js:
        hits = sorted(x for x in ls if x.startswith(j["id"] + "_"))
        if hits and st.get(j["id"], {}).get("file"):
            host[j["id"]] = "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu1/reflock_v9/" + hits[-1]
    # 11-01：Q1–Q8 一次 ssh 在 gpu33 上算完（CLIP 在 GPU；与笔记本 metrics 同一份代码）
    sys.path.insert(0, str(ROOT / "services/render_router"))
    from ns_render import image_params as IP
    post = RS.post_of(IP.resolve("frame_v9", {"style_suffix": ""}))
    rec_by_shot = {j["shot"]: j["asset_refs"] for j in js if j["variant"] == "vR"}
    jobs_pf, reqs = [], {}
    for j in js:
        s = st.get(j["id"])
        if not s or not s.get("file") or j["id"] not in host:
            continue
        req = IJ.contract_request({**j, "graph": {}})
        s["preflight"] = PF.check(req).to_dict() if j["asset_refs"] else None
        if not req.get("asset_refs"):
            req["asset_refs"] = rec_by_shot[j["shot"]]           # 同一把尺子量两组
        reqs[j["id"]] = req
        jobs_pf.append({"id": j["id"], "host_path": host[j["id"]], "file": str(ROOT / s["file"]), "post": post, "request": req})
    res = RS.postflight_full("gpu33", jobs_pf)
    for k, d in res.items():
        st[k]["postflight"] = d
        print("post", k, d["ok"], d["blocking"], flush=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    js = jobs()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "jobs.json").write_text(json.dumps([{**j, "out": jl(STATE, {}).get(j["id"], {}).get("file")} for j in js],
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    a = sys.argv[1:] or ["--render", "--score"]
    if "--render" in a:
        render(js)
    if "--score" in a:
        score(js)
        (OUT / "jobs.json").write_text(json.dumps([{**j, "out": jl(STATE, {}).get(j["id"], {}).get("file")} for j in js],
                                                  ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
