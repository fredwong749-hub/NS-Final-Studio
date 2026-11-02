"""PROMPTFIX 11-02 20:2x：V2 金样测试首帧（总调度 20:10 派）——不依赖 V2 剧本（P4 未出），用一镜测试分镜走完整出图链路：
资产包清单（I11 sha）→ 唯一编译入口 build_first → preflight（I2 / I11 / I12 / I13）→ 借道出图（scope=ab，不写 takes）→
契约 postflight（Q1 身份 / Q2 服装 / Q5 人数手）+ 本地看图逐条核对（提示词）+ anomaly（人数 / 头数 / 手数）→ 四项全过才拷进
data/review_pages/v2_golden/（只放通过的）。成人造型（O2 / O3 / J1 / J2）一律拒绝，那要项目方触发。

    python tools/promptfix/golden_v2.py --compile                 # 只编译 + preflight，打印提示词与 trace
    python tools/promptfix/golden_v2.py --render --lane gpu36:0   # 借道出图 + 验收（借道先用 tools/debug/lanes.py lend）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", "tools/vqa", "tools/gen_contract", ""):
    sys.path.insert(0, str(ROOT / p))

def _current_run() -> str:
    """剧 id 从 runs.current_run 取（arch_scan hard_run：不写死剧 id）；本工具只给资产包模式（V2）的剧用"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("runs_golden", ROOT / "tools" / "autopilot" / "runs.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return os.environ.get("NS_RUN") or m.current_run(ROOT)


PROJECT = _current_run()
OUT = ROOT / "data" / "review_pages" / "v2_golden"
AB = ROOT / "data" / "ab" / "v2_golden"
NAME = "女主"                       # 清单 display_name 未定时的称呼（asset_refs.MANIFEST_DEFAULT_ALIAS）
LOOK = "O1"
IMG = ("中近景，平视机位，女主穿黑色漆皮双排扣长风衣（系腰带）站在外滩江边的观景平台栏杆旁，身体侧对镜头，"
       "视线望向画面右侧对岸陆家嘴的灯火，夜色里霓虹倒映在黄浦江面，暖金色路灯从左侧打在她脸颊和风衣的漆皮上，"
       "江风吹起几缕长发，真实皮肤质感")
MOTION = "static shot，固定机位，女主望向对岸灯火，江风吹动发梢——中近景，女主侧身站在栏杆旁，视线停在对岸灯火上"


def _atomic_write(path, text: str) -> None:
    """先写临时文件再 os.replace（arch_scan nonatomic_json）"""
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def build_script():
    from ns_schema.script import ScriptImport
    fx = json.loads((ROOT / "tests/fixtures/promptfix/frozen_v1_subset.json").read_text(encoding="utf-8"))
    ep = fx["episodes"][0]
    sh = dict(ep["shots"][0])
    sh.update(index=1, img_prompt=IMG, motion_prompt=MOTION, img_triggers=[], motion_triggers=[], dialogue=[], dialogue_raw=None,
              cast=[{"name": NAME, "presence": "在画", "x": "中", "depth": "中", "part": None, "raw": f"{NAME}（在画｜中｜中）"}],
              cast_raw=f"{NAME}（在画｜中｜中）", scene_id=None, scene_detail="外滩江边观景平台，夜", h3_prompt=None, adult=False,
              adult_reasons=[], link=None, link_carry=None)
    ep2 = {**ep, "number": 1, "shots": [sh], "cast": [NAME], "scene_ids": [], "high_intensity": False,
           "looks": [{"character": NAME, "from_shot": None, "slots": {"服装": "黑色漆皮双排扣长风衣（系腰带）"},
                      "en": "a black patent leather double-breasted trench coat belted at the waist", "raw": "服装=黑色漆皮双排扣长风衣（系腰带）"}]}
    g = dict(fx["globals"])
    g["character_locks"] = [{"name": NAME, "description": "24岁中国成年女性，真人写实"}]
    g["lora_triggers"] = []
    d = {k: v for k, v in fx.items() if not k.startswith("_")}
    d.update(globals=g, episodes=[ep2], sources=[{"path": f"{PROJECT} golden test", "sha256": ""}])
    return ScriptImport.model_validate(d)


def compile_job():
    from ns_agent import asset_refs as AR
    from ns_agent import frame_job as FJ
    os.environ["NS_RUN"] = PROJECT
    s = build_script()
    ep, sh = s.episodes[0], s.episodes[0].shots[0]
    job = FJ.build_first(PROJECT, ep, sh, s.globals)
    lk = (AR.manifest_meta(PROJECT).get(f"look:lead_f:{LOOK}") or {})
    if job.get("adult") or lk.get("adult") or job.get("route") == "local_only":
        raise SystemExit(f"拒绝：成人 / 本地专用造型不由系统出图（{job.get('adult_reasons') or job.get('route_reasons')}）")
    return job


def preflight(job, lane):
    from ns_agent.gen_contract import preflight as PF
    req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
    req.update(kind="image", project=PROJECT, framing_project=PROJECT, shot_id="v2golden-S1", lane=lane)
    return PF.check(req)


def vlm_prompt_check(image: str, job: dict) -> dict:
    from ns_agent.vqa import client as C
    q = ("按下面的要求逐条核对这张图，每条回答“符合 / 不符合 + 一句理由”，最后一行写“总结：全部符合”或“总结：有不符合”。\n"
         "1. 画面里只有一个人，是成年女性；2. 她穿黑色漆皮双排扣长风衣、系腰带；3. 地点是上海外滩江边夜景，对岸有陆家嘴的灯火；"
         "4. 景别是中近景（胸部以上到腰部），她没有看镜头；5. 画面里没有文字、水印、logo；6. 手指数量正常、没有多出来的手。")
    r = C.generate({"system": "你是严谨的看图核对员，只描述看到的，用中文。", "text": q, "images": [{"path": image, "max_pixels": 1400000}]},
                   wait_s=600, label="promptfix_v2_golden")
    t = r.get("text") or ""
    ok = ("总结：全部符合" in t) and ("不符合" not in t.split("总结")[0])
    return {"status": "pass" if ok else ("untested" if r.get("error") else "fail"), "text": t, "error": r.get("error")}


def ensure_q9(post: dict, img: str, job: dict) -> dict:
    """远端打分不带本地看图复核（Q9 untested）时，在笔记本补跑一次（图只进本地 Qwen3-VL，K-REV-V01），替换 Q9 项"""
    from ns_agent.gen_contract import postflight as PO
    items = (post or {}).get("items") or []
    q9 = next((i for i in items if i.get("id") == "Q9"), None)
    if q9 and q9.get("status") not in ("untested", None):
        return post
    VQ = PO._vqa()
    if VQ is None:
        return post
    req = {k: job.get(k) for k in ("cast", "asset_refs", "prompt", "refs")}
    v = VQ.cached_for(img) or PO._q9_live(VQ, img, req)
    if v is None:                                   # _q9_live 只认 data/renders/epNN/SN 下的图；金样图在 data/ab → 直接调本地看图
        from ns_agent.vqa import client as VC
        v = VC.inspect_image(img, job.get("prompt") or "", list(job.get("refs") or []), wait_s=900)
    st, d, ev = PO._q9_item(VQ, VQ.q9(v))
    new = {"id": "Q9", "title": (q9 or {}).get("title") or "本地看图复核", "status": st, "detail": d, "evidence": ev}
    post = dict(post or {})
    post["items"] = [i for i in items if i.get("id") != "Q9"] + [new]
    return post


def judge(post: dict, an: dict, vl: dict) -> tuple[dict, dict]:
    """四项标签（ALIGNMENT 第 8 步口径）：身份 = Q1；服装 = Q2（判了就用它；Q2=na 即没有设定图 / 单品行可比时，用本地看图逐条核对的
    第 2 条“风衣”结论，来源写明）；提示词 = 本地看图逐条核对；人数 = anomaly.check 的 status"""
    items = {i.get("id"): i for i in (post or {}).get("items") or []}
    q2 = (items.get("Q2") or {}).get("status", "untested")
    lines = [l.strip() for l in (vl.get("text") or "").splitlines() if l.strip()]
    vl_outfit = "pass" if len(lines) >= 2 and lines[1].startswith("符合") else ("untested" if not lines else "fail")
    lab = {"identity": (items.get("Q1") or {}).get("status", "untested"),
           "outfit": q2 if q2 in ("pass", "fail") else vl_outfit,
           "prompt": vl["status"],
           "count": {"pass": "pass", "fail": "fail"}.get(str(an.get("status")), "untested"),
           "vlm_review": {"pass": "pass", "fail": "fail"}.get(str((items.get("Q9") or {}).get("status")), "untested")}
    src = {"outfit": "Q2" if q2 in ("pass", "fail") else "本地看图逐条核对第 2 条（Q2=na：清单造型没有设定图，单品行不可比）"}
    return lab, src


def rejudge_last() -> dict:
    """不重出图：按现行判定口径重判 takes.jsonl 最后一条（判定口径改了时用），通过才拷进 v2_golden/"""
    rows = [json.loads(l) for l in (AB / "takes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rec = rows[-1]
    lab, src = judge(rec["postflight"], rec["anomaly"], rec["vlm"])
    rec.update(label=lab, label_source=src, pass_=all(v == "pass" for v in lab.values()), rejudged_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    rec["pass"] = rec.pop("pass_")
    with (AB / "takes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + chr(10))
    if rec["pass"]:
        import ns_render.pipeline as P
        img = P.DATA / rec["file"]
        OUT.mkdir(parents=True, exist_ok=True)
        dst = OUT / Path(rec["file"]).name
        shutil.copy2(img, dst)
        _atomic_write(OUT / (dst.stem + ".json"), json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    return rec


def render(lane: str, seed: int | None) -> dict:
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyClient
    from ns_render import seed_stream as SS
    sys.path.insert(0, str(ROOT / "tools" / "factory"))
    import hosts as H
    job = compile_job()
    pf = preflight(job, lane)
    if not pf.ok:
        raise SystemExit("preflight 不过：" + "；".join(pf.reasons()))
    AB.mkdir(parents=True, exist_ok=True)
    used = [json.loads(l) for l in (AB / "takes.jsonl").read_text(encoding="utf-8").splitlines()] if (AB / "takes.jsonl").is_file() else []
    s, sinfo = (seed, {"policy": "manual"}) if seed else SS.pick("v2golden-S1", "image", 1, [{"stage": "image", "seed": u["seed"]} for u in used])
    client = ComfyClient(H.lane_url(lane, from_host="laptop"))
    client.client_id = "promptfix-" + client.client_id      # 借道 client 前缀（tools/debug/lanes.py lend）
    client.server_tag = H.host_of(lane) if H.host_of(lane) != "gpu33" else None
    client.ns_tag = {"agent": "PROMPTFIX", "kind": "v2_golden", "label": "V2 金样测试首帧", "obj": "v2golden-S1"}
    job = {**job, "seed_policy": sinfo, "lane": lane}
    import ns_render.pipeline as P
    rel_dir = AB.relative_to(P.DATA).as_posix()
    take, eff, post_rec = UF._run(client, "v2golden-S1", "image", job, s, rel_dir=rel_dir, prefix="ns_ab/v2_golden/S1")
    img = str(P.DATA / take.file)
    host = H.host_of(lane)
    post = UF._postflight(take.file, job, host)
    post = ensure_q9(post, img, job)
    import anomaly as A
    an = A.check(img, [{"name": NAME, "presence": "在画", "faced": True, "x": "中"}], host="gpu36")
    vl = vlm_prompt_check(img, job)
    lab, src = judge(post, an, vl)
    ok = all(v == "pass" for v in lab.values())
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "lane": lane, "seed": s, "seed_policy": sinfo, "file": take.file,
           "prompt": take.prompt, "refs": job["refs"], "compile_trace": job.get("compile_trace"), "label": lab, "pass": ok,
           "label_source": src, "postflight": post, "anomaly": an, "vlm": vl}
    with (AB / "takes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    if ok:
        OUT.mkdir(parents=True, exist_ok=True)
        dst = OUT / Path(take.file).name
        shutil.copy2(img, dst)
        _atomic_write(OUT / (dst.stem + ".json"), json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--lane", default="gpu36:0")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--rejudge", action="store_true")
    a = ap.parse_args(argv)
    if a.rejudge:
        r = rejudge_last()
        print(json.dumps({k: r[k] for k in ("file", "seed", "label", "label_source", "pass")}, ensure_ascii=False))
        return 0 if r["pass"] else 1
    if a.render:
        r = render(a.lane, a.seed)
        print(json.dumps({k: r[k] for k in ("file", "seed", "label", "pass")}, ensure_ascii=False))
        return 0 if r["pass"] else 1
    job = compile_job()
    pf = preflight(job, a.lane)
    print(job["prompt"])
    print(json.dumps({"refs": job["refs"], "trace": job["compile_trace"], "preflight_ok": pf.ok, "fail": pf.reasons()},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
