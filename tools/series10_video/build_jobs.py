"""VIDEO10（2026-10-31）：series10_v1 视频作业编译——Shot Spec → 配方引擎 → ComfyUI 图（笔记本端，纯编译，不提交）。

提示词 / 图一律由系统编译器生成（K-PRM-301，不手拼）：
  P4_epNN.md ─(tools/pipeline/p4_adapter.check_p4：拼现行全局头 + 真实导入器 + spec_import)→ Shot Spec v2
  ─(services/recipes ns_recipes.compiler.compile_shot：官方 ref-en 六段 / base-en、σ 表、两段式、PDD)→ RenderPlan.graph

每镜预编译一组“变体”，服务器端编排器（vidgen.py）按规则阶梯挑下一个变体，不在服务器上再编译：
  露脸镜（≥1 张在画露脸）：v1 = 默认配方第 1 次；s2/s3/s4 = 默认配方第 2–4 次（换 seed；第 2 次起插官方锚点句）；
      b24 = 纯 Ref2VA 24 步（two_person_ref2va，换配方）；alt = 默认配方 + 换参考（设定图造型版里裁出的脸）；
      i2v = 只给首帧 PDD 两段式（保构图）
  无人露脸镜：v1/s2/s3/s4 = i2va_pdd2（只给首帧）；b24 = establishing（基模 24 只给首帧）
默认配方由 S10V-1 对照决定（config：data/pipeline/runs/series10_v1/video/recipe_choice.json，validate.py 写）。

输出 data/pipeline/runs/series10_v1/video/：jobs.json（全部变体）、specs/<shot>.spec.json、prompts/<shot>.<variant>.txt
    .venv/Scripts/python.exe tools/series10_video/build_jobs.py            # 全量 80 镜
    .venv/Scripts/python.exe tools/series10_video/build_jobs.py --validate  # 只编 S10V-1 对照作业 → validate_jobs.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("tools/pipeline", "services/recipes", "packages/schema", "services/render_router", "services/agent",
          "packages/qc"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import chainlib  # noqa: E402,F401  （补 sys.path）
from p4_adapter import check_p4  # noqa: E402
from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import registry as R  # noqa: E402

RUN = ROOT / "data/pipeline/runs/series10_v1"
VID = RUN / "video"
IMG_STATE = RUN / "images/state.json"
CHOICE = VID / "recipe_choice.json"
NAME2ID = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}
# 换参考（身份低时）：从本角色 series10 造型设定图（项目方流程出的四栏图）里裁出的正脸，只含头脸
ALT_SHEET = {"lin_wan": "images/sheets/lin_wan/lin_wan_lookA_s202.png", "gu_chen": "images/sheets/gu_chen/gu_chen_lookA_s101.png",
             "chen_yu": "images/sheets/chen_yu/chen_yu_lookA_s202.png", "ch_a_lan": "images/sheets/ch_a_lan/ch_a_lan_lookA_s1108.png"}
# 主机按整集分（成片在出片那台机器上合成，片段不跨机）；ep09 有 328 帧长镜头 → gpu36（长镜头道 gpu36:2）
HOST_OF_EP = {1: "gpu33", 2: "gpu36", 3: "gpu33", 4: "gpu36", 5: "gpu33", 6: "gpu36", 7: "gpu33", 8: "gpu36",
              9: "gpu36", 10: "gpu33"}
VALIDATE = {"shots": {"ep01-S5": "单人近景", "ep01-S6": "双人对白", "ep10-S5": "走动全身"},
            "seeds": [20261101, 20261102],
            "arms": {"pdd": "ref2va_pdd2", "b24": "two_person_ref2va"}}  # i2v 组撤掉：项目方判首帧不合格（10-31 夜），对照只走不依赖首帧的 Ref2VA
KITCHEN = {"sampling.attention": "comfy kitchen attention"}
# K-REN-302：“动作不足”的阶梯第一步——系统最低动作提示（只写物理，不写剧情）
MIN_MOTION_CUE = ("Throughout the shot every person keeps small continuous natural movement: visible breathing in the chest and "
                  "shoulders, slight weight shifts and blinks, and each described action is performed fully and clearly, never frozen.")
import re  # noqa: E402
BAD_LORA_RE = re.compile(r"lin_?wan|lnwan|_qi_|identity", re.I)
BAD_STYLE_RE = re.compile(r"creamy|f/1\.\d|oily|greasy|glossy skin|richly saturated|vivid saturated|奶油|油光|浓郁饱和", re.I)


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def load_specs(eps=range(1, 11), source: str | None = None) -> dict:
    """source = "import"（默认，10-31 23:50 起 series10 已整份导入 data/import/script_v2.json，ep09 镜号以导入为准）
    或 "p4"（runs 目录的 P4 稿经 p4_adapter.check_p4 生成）"""
    source = source or ("p4" if "--from-p4" in sys.argv else "import")
    out = {}
    if source == "import":
        from ns_recipes.spec_import import specs_from_import
        from ns_render import pipeline as P
        si = P.load_script()
        for n in eps:
            for s in specs_from_import(si, n):
                out[s.id] = s
        return out
    for n in eps:
        md = (RUN / f"ep{n:02d}" / f"P4_ep{n:02d}.md").read_text(encoding="utf-8")
        rep, _shots, specs, _raw = check_p4(md, n)
        for s in specs:
            out[s.id] = s
    return out


FRAMES_OK = VID / "frames_ok.json"


def _vq():
    try:
        sp = str(ROOT / "services" / "agent")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from ns_agent.vqa import contract as VQ
        return VQ
    except Exception:  # noqa: BLE001
        return None


def _q9_ok(pf: dict) -> bool:
    VQ = _vq()
    return True if VQ is None else VQ.q9_passed(pf)


def _q9_ok_file(file: str) -> bool:
    """frames_ok.json（ASSETMASTER 通知）的首帧没有 postflight：按图片查本地看图判定（data/vqa/index.json）"""
    VQ = _vq()
    if VQ is None or not VQ.enforced():
        return True
    st, _d, _ev = VQ.q9(VQ.cached_for(ROOT / file))
    return VQ.q9_passed({"items": [{"id": "Q9", "status": st}]})


def passed_frames() -> dict:
    """已过契约（GEN_CONTRACT §2 postflight）并设为当前的首帧 → {镜: {file, postflight}}。
    来源：① data/renders/epNN/SN/takes.json 的 active.image，且该版本带 postflight.ok（或 contract.ok）；
          ② video/frames_ok.json（ASSETMASTER 通知“契约通过并设为当前”的镜，notify.py 写入，记来源原话）。
    旧 IMGGEN 首帧（项目方 10-31 夜判不合格）不再使用。"""
    out = {}
    for tj in sorted((ROOT / "data/renders").glob("ep*/S*/takes.json")):
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n = (d.get("active") or {}).get("image")
        t = next((t for t in d.get("takes") or [] if t.get("stage") == "image" and t.get("n") == n), None)
        pf = (t or {}).get("postflight") or (t or {}).get("contract") or {}
        # 总调度亲审打回（PRODUCER 写 take.master_reject）= 视同撤销，不算过契约（K-OPS-304）
        # VQAGATE（项目方 11-01：“image 做出来后用本地图像模型检测……再跑视频”）：只给图片闸门（Q9）通过的首帧派视频；
        # 没有看图结果 = 未通过（config/vqa.json gate.video_requires_q9；enforce 关掉时 q9_passed 恒真）
        if t and t.get("file") and pf.get("ok") and not t.get("master_reject") and _q9_ok(pf) and (ROOT / "data" / t["file"]).exists():
            out[f"{tj.parent.parent.name}-{tj.parent.name}"] = {"file": "data/" + t["file"], "postflight": pf,
                                                               "status": "pass", "take": n}
    ok = json.loads(FRAMES_OK.read_text(encoding="utf-8")) if FRAMES_OK.exists() else {}
    for sid, v in ok.items():
        if not sid.startswith("_") and v.get("file") and (ROOT / v["file"]).exists() and _q9_ok_file(v["file"]):
            out.setdefault(sid, {"file": v["file"], "postflight": {"ok": True, "source": v.get("by")}, "status": "pass"})
    # 上传瘦身（K-OPS-302：笔记本上行很慢）：首帧转 JPEG q95 放 video/inputs/<镜>.jpg，原图路径记在 src
    from PIL import Image
    d = VID / "inputs"
    d.mkdir(parents=True, exist_ok=True)
    for sid, v in list(out.items()):
        src = ROOT / v["file"]
        dst = d / f"{sid}_{hashlib.sha256(src.read_bytes()).hexdigest()[:8]}.jpg"
        if not dst.exists():
            # K-OPS-306：首帧 PNG 还在写 / 拷了一半（离线 11-01 10:44 LOOP_ERR 'image file is truncated' 卡住整轮）
            # → 这一镜本轮不算就绪、下一轮再读；不放宽解码（LOAD_TRUNCATED_IMAGES 会把半张图当首帧送去出片）
            try:
                with Image.open(src) as im:
                    im.load()
                    im.convert("RGB").save(dst, "JPEG", quality=95)
            except (OSError, ValueError, SyntaxError) as e:
                dst.unlink(missing_ok=True)
                print(f"[passed_frames] 跳过 {sid}：首帧读不全（{v['file']}：{e}），下一轮重试", file=sys.stderr)
                out.pop(sid)
                continue
        v["src"] = v["file"]
        v["file"] = rel(dst)
    return out


def chosen_frames() -> dict:
    """IMGGEN 旧首帧（只给 S10V-1 对照的 i2v 组用过；正式出片用 passed_frames）"""
    st = json.loads(IMG_STATE.read_text(encoding="utf-8"))["jobs"]
    out = {}
    for k, v in st.items():
        if not k.startswith("frame:") or not v.get("chosen"):
            continue
        a = next((a for a in v["attempts"] if a["id"] == v["chosen"]), None)
        if a and a.get("file") and (ROOT / a["file"]).exists():
            out[v["shot"]] = {"file": a["file"], "status": v.get("status")}
    return out


def alt_crops() -> dict:
    """设定图左栏最大脸 → 头脸裁切（同 identity_refs manifest 的方法：上扩 0.75×脸高、下到 1.0×脸高、宽 = 高×1.05）"""
    import cv2
    from ns_qc import face as QF
    out = {}
    d = VID / "refs_alt"
    d.mkdir(parents=True, exist_ok=True)
    m = None
    for cid, sheet in ALT_SHEET.items():
        dst = d / f"{cid}_face_alt.png"
        if dst.exists():
            out[cid] = rel(dst)
            continue
        if m is False:
            continue
        if m is None:
            # K-OPS-307：人脸模型只在要新裁时才加载；找不到模型（离线服务器副本 11-01 10:46 FaceModels(*None) TypeError
            # 让 build_jobs 整个失败、全部集派不出）→ 已有裁切照用，缺的这几张跳过并报出，不拖垮编译
            paths = QF.find_models(ROOT)
            if not paths:
                print(f"[alt_crops] 找不到人脸模型（ns_qc.face.find_models），跳过新裁 {cid} 等；已有裁切照用", file=sys.stderr)
                m = False
                continue
            m = QF.FaceModels(*paths, score=0.6)
        img = cv2.imread(str(RUN / sheet))
        if img is None:
            continue
        H, W = img.shape[:2]
        f = QF.largest(m.faces(img[:, : W // 3]))     # 四栏图左栏 = 正面
        if f is None:
            f = QF.largest(m.faces(img))
        if f is None:
            continue
        x, y, w, h = (int(v) for v in f[:4])
        top, bot = max(0, int(y - 0.75 * h)), min(H, int(y + 2.0 * h))
        cw = int((bot - top) * 1.05)
        cx = x + w // 2
        l, r = max(0, cx - cw // 2), min(W, cx + cw // 2)
        cv2.imwrite(str(dst), img[top:bot, l:r])
        out[cid] = rel(dst)
    return out


def recipe_choice() -> dict:
    if CHOICE.exists():
        return json.loads(CHOICE.read_text(encoding="utf-8"))
    return {"face_default": "i2va_pdd2", "ref_default": "two_person_ref2va", "noface_default": "i2va_pdd2",
            "decided": True, "rule": "K-REN-301"}


def compile_variant(spec, reg, rid, attempt, variant, frames_of, *, seed=None, extra=None):
    ov = dict(KITCHEN)
    ov.update(extra or {})
    if seed is not None:
        ov["seed.value"] = int(seed)
    plan = C.compile_shot(spec, reg, attempt=attempt, recipe_id=rid, overrides=ov, allow_experimental={rid})
    if plan["status"] == "needs_writer":
        return {"status": "needs_writer", "reason": plan.get("reason")}
    # K-PRM-302：视频侧不挂会拉偏脸的身份 / 出图 LoRA；系统风格后缀不得带“奶油柔焦 / 浓郁饱和 / 油光”类词
    bad_lora = [n["inputs"].get("lora_name") for n in plan["graph"].values()
                if n["class_type"].startswith("LoraLoader") and BAD_LORA_RE.search(str(n["inputs"].get("lora_name")))]
    if bad_lora:
        return {"status": f"bad_lora:{bad_lora}"}
    sys_style = (reg.resolve(rid).get("prompt") or {}).get("style_lead", "")
    if BAD_STYLE_RE.search(sys_style):
        return {"status": f"bad_style_lead:{sys_style}"}
    inputs = {}
    ff = frames_of.get(spec.id)
    for n in plan["graph"].values():
        for v in (n.get("inputs") or {}).values():
            if not isinstance(v, str) or not v.startswith("@"):
                continue
            if v == "@first_frame":
                if not ff:
                    return {"status": "no_first_frame"}
                inputs[v] = ff["file"]
            elif v.startswith("@look:"):      # Ref2VA 造型槽（REFLOCK 审过的 look_refs，K-REN-303）
                name = v[6:]
                slot = next((s for s in plan["ref_slots"] if s.get("role") == "outfit" and s.get("character") == name
                             and s.get("path")), None)
                if not slot:
                    return {"status": f"no_look:{name}"}
                inputs[v] = slot["path"]
            elif v.startswith("@ref:"):
                name = v[5:]
                slot = next((s for s in plan["ref_slots"] if s.get("character") == name and s.get("role") == "identity"), None)
                if not slot or not slot.get("path"):
                    return {"status": f"no_ref:{name}"}
                inputs[v] = slot["path"]
    # GEN_CONTRACT §0 preflight（REFLOCK ns_agent.gen_contract）：结果随作业带走；vidgen 在非 validate 模式下 ok=False 不提交
    loras = [[n["inputs"].get("lora_name"), n["inputs"].get("strength_model")] for n in plan["graph"].values()
             if n["class_type"].startswith("LoraLoader")]
    ffp = (frames_of.get(spec.id) or {}).get("postflight")
    try:
        from ns_agent.gen_contract import preflight as PF
        pf = PF("video", {"model": rid, "project": "series10_v1", "shot_id": spec.id,
                          "cast": [{"name": c.name, "presence": c.presence, "x": c.screen_x, "depth": c.depth}
                                   for c in spec.characters_on_screen],
                          "prompt": plan["prompt"]["text"], "refs": list(inputs.values()), "loras": loras,
                          "compiled_by": "ns_recipes.compiler.compile_shot", "mode": plan["mode"],
                          "look_refs": bool(ov.get("ref2va.look_refs")),
                          "ref_slots": plan["ref_slots"],
                          "first_frame_postflight": ffp or {}})
        pf = {"ok": bool(pf.get("ok")), "reasons": pf.get("reasons") or [],
              "items": [{k: i.get(k) for k in ("id", "status", "detail")} for i in pf.get("items") or []]}
    except Exception as e:  # noqa: BLE001
        pf = {"ok": False, "reasons": [f"preflight 调用失败：{e}"], "items": []}
    return {
        "preflight": pf,
        "status": plan["status"], "recipe": rid, "mode": plan["mode"], "attempt": attempt, "variant": variant,
        "seed": plan["seed"], "frames": plan["frames"], "long": plan["lane"]["long"], "prompt": plan["prompt"]["text"],
        "prompt_notes": plan["prompt"]["notes"], "graph": plan["graph"], "inputs": inputs,
        "ref_slots": plan["ref_slots"], "acceptance": plan["acceptance"], "plan_hash": plan["plan_hash"],
        "lint_errors": [i for i in plan["lint"] if i["level"] == "error"],
        "lint_warns": [i["code"] for i in plan["lint"] if i["level"] != "error"],
        "compiled_by": "ns_recipes.compiler.compile_shot", "compiler_version": plan["compiler_version"],
    }


def shot_meta(spec) -> dict:
    return {"shot": spec.id, "ep": spec.episode, "idx": spec.index, "seconds": float(spec.duration_s),
            "frames": spec.frames, "size": spec.camera.size,
            "faces": [c.name for c in spec.faces], "visible": [c.name for c in spec.visible],
            "dialogue": [{"speaker": d.speaker, "text": d.text, "off": d.off_screen} for d in spec.audio.dialogue],
            "voiceover": ({"speaker": spec.audio.voiceover.speaker, "text": spec.audio.voiceover.text}
                          if spec.audio.voiceover else None),
            "explicit": bool(spec.rating.explicit), "spec_hash": spec.spec_hash()}


def score_refs(spec, reg) -> dict:
    crops = (reg.resolve("ref2va_pdd2").get("ref2va") or {}).get("identity_crops") or {}
    return {c.name: crops[c.name] for c in spec.faces if c.name in crops}


def build_all(validate_only=False) -> dict:
    reg = R.load()
    specs = load_specs()
    frames_of = chosen_frames() if validate_only else passed_frames()
    alts = alt_crops()
    VID.mkdir(parents=True, exist_ok=True)
    (VID / "specs").mkdir(exist_ok=True)
    (VID / "prompts").mkdir(exist_ok=True)
    ch = recipe_choice()
    crops = (reg.resolve("ref2va_pdd2").get("ref2va") or {}).get("identity_crops") or {}
    shots = []
    for sid, spec in specs.items():
        (VID / "specs" / f"{sid}.spec.json").write_text(spec.model_dump_json(indent=1, by_alias=True), encoding="utf-8")
        if validate_only and sid not in VALIDATE["shots"]:
            continue
        meta = shot_meta(spec)
        hosts = json.loads((VID / "hosts.json").read_text(encoding="utf-8")) if (VID / "hosts.json").exists() else {}
        meta["host"] = hosts.get(str(spec.episode)) or HOST_OF_EP[spec.episode]   # night.py 按卡空闲情况分集
        meta["first_frame"] = (frames_of.get(sid) or {}).get("file")
        meta["first_frame_status"] = (frames_of.get(sid) or {}).get("status")
        # DATAALIGN（register_takes from_first）：输入 JPEG 名里的 sha8 = 源 PNG 的 sha256 前 8 位；这里把源文件和版本号也写明
        meta["first_frame_src"] = (frames_of.get(sid) or {}).get("src")
        meta["first_frame_take"] = (frames_of.get(sid) or {}).get("take")
        meta["score_refs"] = score_refs(spec, reg)
        vs = {}
        if validate_only:
            for arm, rid in VALIDATE["arms"].items():
                for k, sd in enumerate(VALIDATE["seeds"], 1):
                    vs[f"{arm}_s{k}"] = compile_variant(spec, reg, rid, 1, f"{arm}_s{k}", frames_of, seed=sd)
        elif spec.faces:
            # S10V-1 结论（K-REN-301）：有通过的首帧 → 首帧路线 I2VA PDD 两段式（构图 / 景别跟首帧）；
            # 没有通过的首帧，或首帧路线身份不过 → 纯 Ref2VA 24 步（脸部裁切）。Ref2VA + PDD 两段式不用（景别 4/5 退成全景）
            ref = ch.get("ref_default", "two_person_ref2va")
            idc = {"ref2va.identity_crops": crops, "ref2va.look_refs": True}   # REFLOCK 11-01：Ref2VA 必带造型参考（I3）
            alt_map = {c.name: alts.get(NAME2ID.get(c.name, ""), crops.get(c.name)) for c in spec.faces}
            alt_crop = {"ref2va.identity_crops": {**crops, **{k: v for k, v in alt_map.items() if v}}, "ref2va.look_refs": True}
            if sid in frames_of:
                d = ch["face_default"]
                meta["route"] = "first_frame"
                vs["v1"] = compile_variant(spec, reg, d, 1, "v1", frames_of)
                for a in (2, 3, 4):
                    vs[f"s{a}"] = compile_variant(spec, reg, d, a, f"s{a}", frames_of)
                vs["mot"] = compile_variant(spec, reg, d, 2, "mot", frames_of, extra={"prompt.min_motion_cue": MIN_MOTION_CUE})
                vs["r24"] = compile_variant(spec, reg, ref, 1, "r24", frames_of, extra=idc)
                vs["alt"] = compile_variant(spec, reg, ref, 2, "alt", frames_of, extra=alt_crop)
            elif not validate_only:
                # 逐镜派单（总调度 11-01）：正式出片只给首帧已过契约的镜出变体；纯 Ref2VA 兜底要等造型参考槽（preflight I3）
                meta["route"] = "waiting_frame"
            else:
                meta["route"] = "ref2va"
                vs["v1"] = compile_variant(spec, reg, ref, 1, "v1", frames_of, extra=idc)
                for a in (2, 3, 4):
                    vs[f"s{a}"] = compile_variant(spec, reg, ref, a, f"s{a}", frames_of, extra=idc)
                vs["alt"] = compile_variant(spec, reg, ref, 2, "alt", frames_of, extra=alt_crop)
        elif sid not in frames_of:
            meta["route"] = "blocked_no_frame"      # 无人露脸镜只能走首帧；首帧没过契约 → 不出（资料不全不渲染）
        else:
            d = ch["noface_default"]
            vs["v1"] = compile_variant(spec, reg, d, 1, "v1", frames_of)
            for a in (2, 3, 4):
                vs[f"s{a}"] = compile_variant(spec, reg, d, a, f"s{a}", frames_of)
            vs["b24"] = compile_variant(spec, reg, "establishing", 1, "b24", frames_of)
            vs["mot"] = compile_variant(spec, reg, d, 2, "mot", frames_of, extra={"prompt.min_motion_cue": MIN_MOTION_CUE})
        for k, v in vs.items():
            if v.get("prompt"):
                (VID / "prompts" / f"{sid}.{k}.txt").write_text(v["prompt"], encoding="utf-8")
        meta["variants"] = vs
        meta["ladder_order"] = list(vs)
        shots.append(meta)
    if validate_only:   # 对照组按 seed 分到两台（seed1 → gpu33，seed2 → gpu36），6 道一起跑
        split = []
        for m in shots:
            for host, tag in (("gpu33", "_s1"), ("gpu36", "_s2")):
                mm = dict(m, host=host, variants={k: v for k, v in m["variants"].items() if k.endswith(tag)})
                mm["ladder_order"] = list(mm["variants"])
                split.append(mm)
        shots = split
    shots.sort(key=lambda m: (m["ep"], m["idx"]))
    out = {"schema": "series10_video.jobs/1", "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "built_by": "tools/series10_video/build_jobs.py", "recipe_choice": ch,
           "validate": VALIDATE if validate_only else None, "shots": shots}
    blob = json.dumps(out, ensure_ascii=False, indent=1)
    out_p = VID / ("validate_jobs.json" if validate_only else "jobs.json")
    out_p.write_text(blob, encoding="utf-8")
    bad = [(m["shot"], k, v.get("status"), [e["code"] for e in v.get("lint_errors", [])])
           for m in shots for k, v in m["variants"].items() if v.get("status") != "ready"]
    return {"file": rel(out_p), "shots": len(shots), "variants": sum(len(m["variants"]) for m in shots),
            "not_ready": bad, "sha": hashlib.sha256(blob.encode()).hexdigest()[:12]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(build_all("--validate" in sys.argv), ensure_ascii=False, indent=1))
