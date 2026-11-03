"""REFLOCK 验证（2026-10-31）：3 镜 × 2 seed，“有资产参考”（ns_agent.asset_refs 槽位规划）vs “无资产参考”（旧做法：只挂脸，
服装靠文字），其它完全一样（同一编译器输出正文、同一 S★ 后缀、同 seed、同一出图图）。出图走 gpu33:1（IMGGEN 借道，隧道 18189），
出完在 gpu33 上原地跑 score_remote（身份 / 景别 / 文字）+ hands_remote（坏手），本机跑 Q2 / Q4 / Q7，生成契约逐项结果表 + 接触印样。

    .venv/Scripts/python.exe tools/gen_contract/reflock_validate.py [--render] [--score] [--page]
输出：data/pipeline/runs/<legacy run>/images/reflock_val/、data/review_pages/asset_reflock/
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
for p in ("services/agent", "packages/schema", "tools/pipeline", "tools/prompt_v2", "tools/ab", "services/render_router"):
    sys.path.insert(0, str(ROOT / p))

RUN = ROOT / ("data/pipeline/runs/" + _LEGACY)
OUT = RUN / "images" / "reflock_val"
PAGE = ROOT / "data/review_pages/asset_reflock"
URL = "http://127.0.0.1:18189"
HOST, OUTDIR, R = "gpu33", "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu1", "/root/work/fredw/imggen"
SHOTS = {"ep01-S3": "林晚中全景，鞋可见（造型 A：透明 12cm 细高跟 = 衣橱 LW-S01）",
         "ep01-S1": "林晚特写，细银链 + 钻石水晶甲（造型 A）",
         "ep01-S4": "双人镜：顾沉（主体）+ 林晚"}
SEEDS = (20261311, 20261312)
STATE = OUT / "state.json"


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def build_jobs() -> list[dict]:
    import image_jobs as IJ
    import plan_c_preview as PC
    from ns_agent import asset_refs as AR
    prod, bible = IJ.production_globals(), IJ.load_bible()
    __import__("os").environ.setdefault("NS_ALLOW_P4_SOURCE", "1")   # CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：标定 / 对照实验复现当时 P4 稿出的图，属调研用途
    si, ep = IJ.load_episode(RUN / "ep01" / "P4_ep01.md")
    g = IJ.merged_globals(si.globals, prod)
    jobs = []
    for sid in SHOTS:
        shot = next(s for s in ep.shots if f"ep01-S{s.index}" == sid)
        on = [c.name for c in shot.cast if c.presence == "在画"]
        cf = IJ.core_faces()                       # K-OPS-E29：身份脸唯一入口 asset_refs.face_of
        faces = [cf[n] for n in on if n in cf]
        for variant in ("asset", "noasset"):
            if variant == "asset":
                prompt, c, sr, plan = IJ.frame_prompt_full(ep, shot, g, [], _LEGACY, bible)
                refs, rec = plan.files, AR.record(sr, plan)
            else:
                prompt, c, _, _ = IJ.frame_prompt_full(ep, shot, g, faces, _LEGACY, bible, assets=False)
                refs, rec = faces, None
            for seed in SEEDS:
                key = f"{sid}_{variant}_s{seed}"
                graph = IJ.with_loras(PC.graph(prompt, ["@upload:" + r for r in refs], seed, f"reflock_val/{key}"), c.image_loras)
                j = {"id": key, "shot": sid, "ep": 1, "variant": variant, "seed": seed, "prompt": prompt, "refs": refs,
                     "asset_refs": rec, "cast": IJ.cast_of(shot), "loras": [[f, w] for f, w in c.image_loras],
                     "compiled_by": "tools/pipeline/image_jobs.py → ns_agent.compiler.compile_shot", "framing_project": _LEGACY,
                     "graph": graph, "out": str((OUT / f"{key}.png").relative_to(ROOT)).replace("\\", "/")}
                jobs.append(j)
    return jobs


def _api(path, data=None):
    req = urllib.request.Request(URL + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def render(jobs):
    import char_sheet_qi21 as CS
    import submit_jobs as SJ
    import image_jobs as IJ
    from ns_agent.gen_contract import preflight as PF
    st = jl(STATE, {}) or {}
    cache = {}
    for j in jobs:
        if (ROOT / j["out"]).exists() and j["id"] in st:
            continue
        if j["variant"] == "asset":                      # 契约闸：有资产参考组必须过 preflight（I5 例外见下）
            r = PF.check(IJ.contract_request(j))
            st.setdefault(j["id"], {})["preflight"] = r.to_dict()
            if not r.ok:
                print("preflight 不过", j["id"], r.reasons(), flush=True)
        for p in SJ.placeholders(j["graph"]):
            if p not in cache:
                cache[p] = CS.upload(URL, ROOT / p)
        g = SJ.resolve(j["graph"], cache)
        body = {"prompt": g, "client_id": "reflock-" + j["id"]}
        try:   # GPU 任务归属标签（K-OPS-G01，extra_data.ns_tag）；出错就不带标签
            from ns_agent import comfy_tag as CT
            sh = str(j.get("shot") or "")
            CT.attach(body, CT.make("REFLOCK", "first_frame", episode=j.get("ep"), shot=sh.rsplit("-", 1)[-1] or None,
                                    label=f"参考锁定验证 {j.get('variant')}", job=j["id"]))
        except Exception:  # noqa: BLE001
            body.pop("extra_data", None)
        pid = json.loads(_api("/prompt", json.dumps(body).encode()))["prompt_id"]
        t0 = time.time()
        while True:
            time.sleep(4)
            h = json.loads(_api(f"/history/{pid}"))
            if pid in h:
                if h[pid].get("status", {}).get("status_str") == "error":
                    raise RuntimeError(json.dumps(h[pid]["status"])[:600])
                ims = [im for n in h[pid]["outputs"].values() for im in n.get("images", [])]
                if ims:
                    im = ims[0]
                    dest = ROOT / j["out"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(_api(f"/view?filename={im['filename']}&subfolder={im['subfolder']}&type={im['type']}"))
                    st.setdefault(j["id"], {}).update(remote_path=f"{OUTDIR}/{im['subfolder']}/{im['filename']}",
                                                      render_s=round(time.time() - t0, 1), prompt_id=pid)
                    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
                    print(time.strftime("%H:%M:%S"), "done", j["id"], round(time.time() - t0), "s", flush=True)
                    break
            if time.time() - t0 > 1800:
                raise TimeoutError(j["id"])


def ssh(cmd, stdin=None, timeout=900):
    return _rssh().run_retry(HOST, cmd, input=stdin, timeout=timeout, tries=1, text=True)   # 原来不重试：tries=1

def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location("_rssh_41", _P(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod



def score(jobs):
    st = jl(STATE, {})
    items = [{"id": j["id"], "path": st[j["id"]]["remote_path"]} for j in jobs if st.get(j["id"], {}).get("remote_path")]
    refs = {k: [f"{R}/refs/{k}_face_ref2va.png"] for k in ("lin_wan", "gu_chen", "chen_yu")}
    r = ssh(f"cd {R} && /root/work/fredw/venv_idm/bin/python score_remote.py - 2>/dev/null",
            json.dumps({"refs": refs, "items": items}, ensure_ascii=False))
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not out:
        raise RuntimeError(r.stderr[-500:])
    d = json.loads(out[-1])
    hi = [{"id": i["id"], "path": i["path"], "faces": len(d["items"].get(i["id"], {}).get("faces", []))} for i in items]
    rh = ssh(f"cd {R} && /root/work/fredw/venv_hand/bin/python hands_remote.py 2>/dev/null", json.dumps({"items": hi}))
    ho = [ln for ln in rh.stdout.splitlines() if ln.startswith("{")]
    hands = json.loads(ho[-1]) if ho else {}
    for i in items:
        it = d["items"].get(i["id"], {})
        for f in it.get("faces", []):
            f.pop("emb", None)
        st[i["id"]].update(remote=it, hands=hands.get(i["id"]), cross=d.get("cross"))
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def post(jobs):
    import image_jobs as IJ
    from ns_agent.gen_contract import postflight as PO
    st = jl(STATE, {})
    for j in jobs:
        s = st.get(j["id"]) or {}
        if not (ROOT / j["out"]).exists():
            continue
        req = IJ.contract_request(j)
        if not req.get("asset_refs"):                       # 无资产参考组：Q2 仍按本镜的资产规划量（同一把尺子比两组）
            req["asset_refs"] = next(x["asset_refs"] for x in jobs if x["shot"] == j["shot"] and x["variant"] == "asset")
        local = PO.measure_local(ROOT / j["out"], req["asset_refs"], s.get("remote"))
        r = PO.evaluate(ROOT / j["out"], req, remote=s.get("remote"), cross=s.get("cross"), hands=s.get("hands"), local=local)
        s["postflight"] = r.to_dict()
        s["local"] = local
        st[j["id"]] = s
        print("post", j["id"], r.ok, [i.id for i in r.blocking], flush=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    RUNS.gate_legacy_tool(None, __file__)
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = build_jobs()
    (OUT / "jobs.json").write_text(json.dumps([{k: v for k, v in j.items() if k != "graph"} for j in jobs], ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    a = sys.argv[1:] or ["--render", "--score", "--post"]
    if "--render" in a:
        render(jobs)
    if "--score" in a:
        score(jobs)
    if "--post" in a:
        post(jobs)


if __name__ == "__main__":
    main()
