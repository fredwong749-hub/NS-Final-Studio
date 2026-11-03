"""CAST-S 11-02：V2 第 1 集配角 / 场景设定候选（复用 golden_v2 的唯一编译入口 build_first + preflight + 契约 postflight + 本地看图，
不另写出图链）。新角色没有身份参考 -> 文生图；成人造型一律拒绝。
过渡期原型：正式形态是 tools/pipeline/asset_worker.py（阶段 A 资产作业，M-AUTOPIPE-01）。preflight 走正式的设定候选模式
（mode=setting_candidate + asset_stage），不再在脚本里豁免 I2 / I3。
    python tools/promptfix/cast_v2.py ch_tang_yao --compile
    python tools/promptfix/cast_v2.py ch_tang_yao --render --lane gpu36:0 --seed 1001
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_v2 as G

ROOT, PROJECT = G.ROOT, G.PROJECT
OUT = ROOT / "data" / "review_pages" / "v2_cast"
AB = ROOT / "data" / "ab" / "v2_cast"

CAST = {
    "ch_tang_yao": dict(
        name="唐瑶", age=24, sex="女性",
        desc="24岁中国成年女性，黑色及肩直发向后梳开、无刘海，圆眼、薄唇，皮肤白皙，高挑纤细，右锁骨下一颗小痣，真人写实",
        slots={"服装": "白色棉质吊带背心"}, en="a white cotton camisole",
        img="胸像特写，脸只微微转向画面右侧（接近正脸），眼睛看着画面右侧远处的一点，头和视线都朝向右侧，成年女性唐瑶，24岁，黑色及肩直发向后梳开露出额头、无刘海，圆眼、薄唇，白皙皮肤，右锁骨下方有一颗小痣，穿白色棉质吊带背心，表情平静自然，真实皮肤质感与成熟的五官轮廓"),
    "ch_jiang_yubai": dict(
        name="江予白", age=29, sex="男性",
        desc="29岁中国成年男性，深棕色中长发半扎，单眼皮、高鼻梁，浅肤色，清瘦修长，真人写实",
        slots={"服装": "驼色皮夹克、黑色圆领T恤"}, en="a camel leather jacket over a black crew-neck t-shirt",
        img="胸像特写，脸只微微转向画面右侧（接近正脸），眼睛看着画面右侧远处的一点，头和视线都朝向右侧，成年男性江予白，29岁，深棕色中长发半扎在脑后，单眼皮、高鼻梁，浅肤色，清瘦，穿驼色皮夹克里面黑色圆领T恤，表情平静，真实皮肤质感与成熟的五官轮廓"),
    "ch_zhuo_lin": dict(
        name="卓琳", age=35, sex="女性",
        desc="35岁中国成年女性，黑色齐肩直发中分，颧骨高、薄唇，浅肤色，匀称干练，真人写实",
        slots={"服装": "酒红色西装套装、黑色丝质吊带衫"}, en="a wine-red tailored suit over a black silk camisole",
        img="胸像特写，脸只微微转向画面右侧（接近正脸），眼睛看着画面右侧远处的一点，头和视线都朝向右侧，成年女性卓琳，35岁，黑色齐肩直发中分，高颧骨、薄唇，浅肤色，穿酒红色西装外套里面黑色丝质吊带衫，神情干练冷静，真实皮肤质感，眼角有细微的成熟纹理"),
}
NEUTRAL = "，中性浅灰色纯色背景，柔和均匀的影棚光，无文字无标识"
SCENE_ID = "sk_white_cyc"
SCENE_IMG = ("空镜，无人物，影棚白幕：纯白无缝弧形背景幕从墙面弯到地面，一只环形灯架立在相机位，一台落地风机对着背景幕中央的一把透明亚克力椅，"
             "环形灯正面高亮，白幕反光把影子打平，画面里没有人，无文字无标识")


def _aj():
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import asset_jobs as AJ   # noqa: PLC0415
    return AJ


def script_for(cid: str):
    """一镜设定候选分镜：V2 中性外壳（asset_jobs.setting_script，L-126：不再拿 V1 夹具 frozen_v1_subset.json 当外壳）"""
    from ns_schema.script import ScriptImport
    AJ = _aj()
    if cid == SCENE_ID:
        d = AJ.setting_script(PROJECT, f"{PROJECT} cast test", SCENE_IMG, "【现实段】影棚白幕")
    else:
        c = CAST[cid]
        d = AJ.setting_script(PROJECT, f"{PROJECT} cast test", c["img"] + NEUTRAL, "【现实段】中性背景", name=c["name"],
                              slots=c["slots"], en=c["en"], desc=c["desc"])
    return ScriptImport.model_validate(d)


def preflight(job, lane, cid):
    """与 golden_v2.preflight 同一入口，只多两个字段：mode=setting_candidate + asset_stage（face / scene）"""
    from ns_agent.gen_contract import preflight as PF
    req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
    req.update(kind="image", project=PROJECT, framing_project=PROJECT, shot_id="v2cast-S1", lane=lane,
               mode="setting_candidate", asset_stage="scene" if cid == SCENE_ID else "face")
    return PF.check(req)


def compile_job(cid):
    import os
    from ns_agent import frame_job as FJ
    os.environ["NS_RUN"] = PROJECT
    s = script_for(cid)
    job = FJ.build_first(PROJECT, s.episodes[0], s.episodes[0].shots[0], s.globals)
    if job.get("adult") or job.get("route") == "local_only":
        raise SystemExit("拒绝：成人 / 本地专用")
    if cid == SCENE_ID:                       # 空镜不用人像风格后缀（ISS-1103-004550-8787），与 asset_worker 同一做法
        AJ = _aj()
        import asset_worker as AW   # noqa: PLC0415
        sc = AJ.spec_scene(AJ.p1(ROOT, PROJECT)[0], SCENE_ID)
        job = AW.empty_suffix(job, sc)
        job["compile_trace"] = FJ.trace_of(job)
    return job


def _ask(text, image, label, px=1400000):
    from ns_agent.vqa import client as C
    return C.generate({"system": "你是严谨的看图核对员，只描述看到的，用中文。", "text": text,
                       "images": [{"path": image, "max_pixels": px}]}, wait_s=600, label=label)


def vlm_check(image, cid):
    head = "逐条核对，每条答“符合 / 不符合 + 一句理由”，最后一行写“总结：全部符合”或“总结：有不符合”。\n"
    if cid == SCENE_ID:
        q = head + "1. 画面里没有人；2. 是纯白无缝弧形背景幕的影棚；3. 有环形灯和一把透明亚克力椅；4. 没有文字、水印、logo；5. 画面干净无杂物。"
    else:
        c = CAST[cid]
        q = head + (f"1. 画面里只有一个人，是{c['sex']}，接近正脸、目光落在画面右侧，胸像构图；2. 外观明显是成年人（大约{c['age']}岁，不像未成年）；"
                    "3. 背景是中性纯色，没有场景杂物；4. 画面里没有文字、水印、logo、品牌标志；5. 没有裸露，穿着日常；6. 五官清晰自然、没有畸形。")
    r = _ask(q, image, "cast_v2")
    t = r.get("text") or ""
    ok = ("总结：全部符合" in t) and ("不符合" not in t.split("总结")[0])
    return {"status": "pass" if ok else ("untested" if r.get("error") else "fail"), "text": t, "error": r.get("error")}


def age_check(image, cid):
    """年龄观感：单独问一次本地看图，只要有“像未成年”就作废"""
    if cid == SCENE_ID:
        return {"status": "na", "text": "场景无人物"}
    r = _ask("这张图里的人看起来是成年人还是未成年人？只回答第一行：“成年”或“像未成年”，第二行一句理由。", image, "cast_v2_age", 1000000)
    t = (r.get("text") or "").strip()
    first = t.splitlines()[0] if t else ""
    return {"status": "pass" if first.startswith("成年") else ("untested" if r.get("error") else "fail"), "text": t}


def ocr_check(image):
    """OCR：本地看图读字（本地口径，图不出自有机器）"""
    r = _ask("逐字读出这张图里所有可见的文字、字母、数字、logo 或品牌标志。没有就只回答“无”。", image, "cast_v2_ocr")
    t = (r.get("text") or "").strip()
    return {"status": "pass" if t.startswith("无") and len(t) < 12 else ("untested" if r.get("error") else "fail"), "text": t}


def render(cid, lane, seed):
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyClient
    import ns_render.pipeline as P
    sys.path.insert(0, str(ROOT / "tools" / "factory"))
    import hosts as H
    job = compile_job(cid)
    pf = preflight(job, lane, cid)
    # 设定候选模式（mode=setting_candidate，AUTOPIPE-A 11-03）：I2 / I3（场景：I5）由 preflight 按规则判 na，不再在这里手工豁免；其余项必须全过
    if not pf.ok:
        raise SystemExit("preflight 不过：" + "；".join(pf.reasons()))
    waived = [f"{i.id} {i.detail}" for i in pf.items if (i.evidence or {}).get("mode") == "setting_candidate"]
    client = ComfyClient(H.lane_url(lane, from_host="laptop"))
    client.client_id = "castS-" + client.client_id
    client.server_tag = H.host_of(lane) if H.host_of(lane) != "gpu33" else None
    client.ns_tag = {"agent": "CAST-S", "kind": "v2_cast", "label": "V2 配角设定候选", "obj": f"v2cast-{cid}"}
    job = {**job, "seed_policy": {"policy": "manual"}, "lane": lane}
    AB.mkdir(parents=True, exist_ok=True)
    rel_dir = AB.relative_to(P.DATA).as_posix()
    take, eff, _ = UF._run(client, "v2cast-S1", "image", job, seed, rel_dir=rel_dir, prefix="ns_ab/v2_cast/" + cid)
    img = str(P.DATA / take.file)
    host = H.host_of(lane)
    post = G.ensure_q9(UF._postflight(take.file, job, host), img, job)
    if cid == SCENE_ID:
        an = {"status": "pass", "note": "空镜，无人物，跳过人数检查"}
    else:
        import anomaly as A
        an = A.check(img, [{"name": CAST[cid]["name"], "presence": "在画", "faced": True, "x": "中"}], host="gpu36")
    vl, ag, oc = vlm_check(img, cid), age_check(img, cid), ocr_check(img)
    items = {i.get("id"): i for i in (post or {}).get("items") or []}
    q9 = str((items.get("Q9") or {}).get("status"))
    lab = {"identity": "na", "count": {"pass": "pass", "fail": "fail"}.get(str(an.get("status")), "untested"),
           "q9": {"pass": "pass", "na": "pass", "fail": "fail"}.get(q9, "untested"),
           "prompt_vlm": vl["status"], "ocr": oc["status"], "age": ag["status"]}
    ok = all(v in ("pass", "na") for v in lab.values())
    rec = dict(at=time.strftime("%Y-%m-%dT%H:%M:%S"), id=cid, lane=lane, seed=seed, file=take.file, prompt=take.prompt, refs=job["refs"],
               label=lab, preflight_waived=waived, passed=ok, postflight=post, anomaly=an, vlm=vl, age=ag, ocr=oc)
    with (AB / "takes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    if ok:
        OUT.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img, OUT / f"{cid}_s{seed}.png")
        G._atomic_write(OUT / f"{cid}_s{seed}.json", json.dumps(rec, ensure_ascii=False, indent=1, default=str))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cid")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--lane", default="gpu36:0")
    ap.add_argument("--seed", type=int, default=1001)
    a = ap.parse_args()
    if a.render:
        r = render(a.cid, a.lane, a.seed)
        print(json.dumps({k: r[k] for k in ("file", "seed", "label", "passed")}, ensure_ascii=False))
        return 0 if r["passed"] else 1
    job = compile_job(a.cid)
    pf = preflight(job, a.lane, a.cid)
    print(job["prompt"])
    print(json.dumps({"refs": job["refs"], "preset": job.get("preset"), "ok": pf.ok, "fail": pf.reasons(),
                      "trace": job["compile_trace"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
