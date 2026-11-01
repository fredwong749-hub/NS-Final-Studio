"""Preflight（提交前，确定性代码）：docs/GEN_CONTRACT.md §1 I1–I10。任何一项 fail → 拒绝提交。

请求格式（各提交入口统一组装；image_jobs.contract_request(job) 已实现首帧作业的组装）：
    {
      "kind": "image" | "video",
      "model": "qwen_image_2.1" | "qwen_image_edit_2511" | "flux2_klein" | <视频配方名>,
      "project": "series10_v1", "shot_id": "ep01-S3",
      "cast": [{"name", "presence": 在画|局部|画外, "x", "depth", "pose"}],      # I1
      "prompt": "<送进模型的完整提示词>",
      "refs": ["<相对项目根>", ...],                                           # 实际进模型的参考图，按槽位顺序
      "asset_refs": ns_agent.asset_refs.record(...)，                          # I2–I5、I9
      "loras": [[file, strength], ...],
      "compiled_by": "...ns_agent.compiler...",                               # I6
      "first_frame_postflight": {...}                                         # 视频：首帧 postflight 结果（ok）
    }
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from . import ROOT, ContractResult, ContractViolation, Item, cfg
from . import style as ST

TITLES = {
    "I1": "在画角色清单 + 朝向 / 站位", "I2": "身份脸部参考", "I3": "本镜造型 id + 造型设定图",
    "I4": "景别可见的单品资产图", "I5": "场景参考底图", "I6": "提示词 = 系统编译器输出（含景别首句、参考图逐一标注）",
    "I7": "系统后缀 = 默认出图预设，无旧柔焦 / 奶油 / 浓郁饱和 / 油光", "I8": "LoRA 白名单（禁已证伪）",
    "I9": "模型槽位规划（优先级、参考板、双人脸不同槽）", "I10": "成年人与锁定外貌（HC-07）",
}
REF_LINE = re.compile(r"图(\d+)是")
IMG_TAG = re.compile(r"<image(\d+)>是")


def _hc():
    p = str(ROOT / "tools" / "pipeline")
    if p not in sys.path:
        sys.path.insert(0, p)
    import hard_constraints as HC
    return HC


def _relpath(p) -> str:
    from pathlib import Path
    q = Path(str(p))
    try:
        return (q if q.is_absolute() else ROOT / q).resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p).replace("\\", "/")


def registered_sheet_files(project: str | None) -> set[str]:
    """已选定的造型设定图：项目 sheets_file（sheets_chosen.json）里登记的 file"""
    import json
    from ns_agent import asset_refs as AR
    out: set[str] = set()
    projs = [project] if project else list((AR._cfg().get("projects") or {}))
    for pj in projs:
        try:
            d = json.loads((ROOT / AR.project_cfg(pj).get("sheets_file", "")).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        out.update(_relpath(e["file"]) for e in d.values() if isinstance(e, dict) and e.get("file"))
    return out


def look_file_registered(slot: dict, chosen: set[str]) -> bool:
    """造型槽文件 = 已选定设定图本身，或它在 crop_dir 下的系统裁切（asset_refs.sheet_crop 命名：<设定图名>_<栏>[_区域].png）"""
    from ns_agent import asset_refs as AR
    p = _relpath(slot.get("path") or "")
    if p in chosen:
        return True
    sheet = _relpath(slot.get("sheet") or "")
    if sheet not in chosen:
        return False
    crop_dirs = {_relpath(AR.project_cfg(pj).get("crop_dir", "data/refcrops")) for pj in (AR._cfg().get("projects") or {})}
    pp = Path(p)
    return pp.parent.as_posix() in crop_dirs and pp.stem.startswith(Path(sheet).stem + "_") and (ROOT / p).is_file()


def registered_identity_files() -> set[str]:
    """已登记身份图：data/assets/identity_refs/manifest.json 里的文件 + 资产参考配置的身份脸 + 资产中心身份脸覆盖"""
    import json
    out: set[str] = set()
    try:
        m = json.loads((ROOT / "data/assets/identity_refs/manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            out.add(_relpath(x if "/" in x or "\\" in x else f"data/assets/identity_refs/{x}"))
    walk(m)
    from ns_agent import asset_refs as AR
    for pc in (AR._cfg().get("projects") or {}).values():
        for fs in (pc.get("faces") or {}).values():
            out.update(_relpath(f) for f in fs)
    try:
        ov = json.loads(AR.FACE_OVERRIDES.read_text(encoding="utf-8"))
        walk(ov)
    except (OSError, ValueError):
        pass
    return out


def _kinds(rec: dict, *kinds) -> list[dict]:
    return [m for m in (rec.get("missing") or []) if m.get("kind") in kinds]


def check(req: dict) -> ContractResult:
    c = cfg()
    kind = req.get("kind", "image")
    rec = req.get("asset_refs") or {}
    prompt = req.get("prompt") or ""
    refs = list(req.get("refs") or [])
    items: list[Item] = []

    def add(i, status, detail="", **ev):
        items.append(Item(i, TITLES[i], status, detail, ev))

    # I1 在画角色 + 站位
    cast = req.get("cast")
    if cast is None:
        add("I1", "fail", "作业里没有在画角色清单（Shot Spec 人物）")
    else:
        on = [x for x in cast if x.get("presence") in ("在画", "局部")]
        nopos = [x.get("name") for x in on if x.get("presence") == "在画" and not (x.get("x") or x.get("pose"))]
        add("I1", "fail" if nopos else ("pass" if on else "na"),
            f"缺站位：{nopos}" if nopos else f"{len(on)} 人在画", on_screen=[x.get("name") for x in on])

    if kind == "image":
        if not rec:
            for i in ("I2", "I3", "I4", "I5", "I9"):
                add(i, "fail", "作业没有资产参考解析结果（ns_agent.asset_refs）——服装 / 鞋 / 饰品只靠文字，禁止提交")
        else:
            slots = rec.get("slots") or []
            files_in_slots = [s.get("file") for s in slots]
            # I2
            m = _kinds(rec, "身份脸缺图")
            faces = [s for s in slots if s.get("kind") == "face"]
            need_face = rec.get("subject") not in ("part", "object") and bool(rec.get("primary")) and any(
                c.get("character") == rec.get("primary") and (c.get("presence", "在画") == "在画" or c.get("face_described"))
                for c in rec.get("characters") or [{"character": rec.get("primary")}])
            # K-AST-263（IMGFIX 11-02，项目方 00:05“很多人物face都出了问题”）：每个露脸的人（在画，或局部但原文写到脸）都要有自己的
            # 身份脸（单独的 face 槽，或脸板里标了名字的一格）；提示词写了“两张脸都清晰入画”，身份脸至少两张
            face_ids = {s.get("character") for s in faces} | {mm.get("character") for s in slots if s.get("kind") == "faceboard"
                                                             for mm in s.get("members") or [] if mm.get("role") == "face"}
            faced = [c.get("character") for c in rec.get("characters") or []
                     if c.get("presence") == "在画" or c.get("face_described")] if rec.get("subject") not in ("part", "object") else []
            lack = [c for c in faced if c and c not in face_ids]
            two = "两张脸都清晰入画" in str(req.get("prompt") or "")
            # K-REN-708 矛盾 lint（阻断）：同一个人既写“只露出…，不露脸”，又是露脸人物 / 提示词有脸部占比（特写脸部构图）
            import re as _re
            hidden = set(_re.findall(r"([^，。、；（）]{1,12}?)(?:只露出[^，。]{1,30}，)?不露脸", str(req.get("prompt") or "")))
            names = {c.get("name"): c for c in rec.get("characters") or []}
            clash = [n for n in hidden if n in names and (names[n].get("presence") == "在画" or names[n].get("face_described")
                                                          or ("脸部占画面" in str(req.get("prompt") or "") and len(names) == 1))]
            if m:
                add("I2", "fail", "；".join(x["detail"] for x in m))
            elif clash:
                add("I2", "fail", f"提示词矛盾：{'、'.join(clash)} 写了“不露脸”，但本镜他是露脸人物 / 脸部特写构图（K-REN-708，写作 / 导入格式问题）")
            elif lack:
                add("I2", "fail", f"露脸的人没有身份脸参考槽：{'、'.join(lack)}（K-AST-263）")
            elif two and len(face_ids) < 2:
                add("I2", "fail", f"提示词写了两张脸都入画，但身份脸参考只有 {len(face_ids)} 张（K-AST-263 / K-REN-705）")
            elif need_face and not faces:
                add("I2", "fail", f"主体角色 {rec.get('primary')} 脸可见，但没有身份脸参考槽")
            else:
                add("I2", "pass" if faces else "na", f"{len(faces)} 张身份脸参考", files=[s["file"] for s in faces])
            # I3
            m = _kinds(rec, "造型未登记") + [x for x in _kinds(rec, "资产缺图") if x.get("detail", "").endswith("没有设定图")]
            sheets = [mm for s in slots for mm in s.get("members") or [] if mm.get("role") == "sheet"]
            if m:
                add("I3", "fail", "；".join(x["detail"] for x in m))
            else:
                looks = {ch["name"]: ch.get("look") for ch in rec.get("characters") or []}
                add("I3", "pass", f"造型：{looks}；设定图 {len(sheets)} 张", looks=looks)
            # I4
            m = [x for x in _kinds(rec, "资产缺图") if not x.get("detail", "").endswith("没有设定图")]
            items_used = [mm for s in slots for mm in s.get("members") or [] if mm.get("role") == "item"]
            if m:
                add("I4", "fail", "资产缺图：" + "；".join(x["detail"] for x in m))
            elif "feet" in (rec.get("zones") or []) and rec.get("primary") and not any(mm.get("zone") == "feet" for mm in items_used) \
                    and not any("鞋" in d.get("label", "") for d in rec.get("dropped") or []):
                add("I4", "fail", "鞋在画面里可见，但参考里没有鞋的单品图")
            else:
                sheet_only = [w for w in rec.get("warnings") or [] if w.get("kind") == "仅设定图"]
                add("I4", "pass", f"单品参考 {len(items_used)} 件" + (f"（{len(sheet_only)} 件只有设定图，建议补单品图）" if sheet_only else ""),
                    items=[mm.get("label") for mm in items_used])
            # I5
            m = _kinds(rec, "场景缺图")
            add("I5", "fail" if m else "pass", "；".join(x["detail"] for x in m) if m else "场景参考已登记（槽位不足时走文字，见 I9）")
            # I9
            bad = []
            cap = int(rec.get("capacity") or 0)
            if cap and len(slots) > cap:
                bad.append(f"参考 {len(slots)} 张 > {rec.get('model')} 槽位 {cap}")
            if refs != files_in_slots:
                bad.append("实际送进模型的参考图与槽位规划不一致")
            if any(int(s.get("faces") or 0) > 1 for s in slots):
                bad.append("同一参考槽里有两张脸")
            n_face_slots = sum(1 for s in slots if s.get("kind") == "face")
            two_mode = rec.get("two_person") or (__import__("ns_agent.asset_refs", fromlist=["x"])._cfg().get("two_person") or "primary_face_only")
            if n_face_slots > 1 and two_mode == "primary_face_only":
                bad.append("双人镜给了两张身份脸参考（契约：只给主体角色脸，第二人用造型设定图）")
            if faces and slots and slots[0].get("kind") != "face":
                bad.append("身份脸不在第 1 槽（优先级 身份脸 > 造型设定图 > 单品 > 场景）")
            add("I9", "fail" if bad else "pass", "；".join(bad) if bad else f"{len(slots)}/{cap} 槽",
                slots=[(s.get("kind"), s.get("labels")) for s in slots])
        # I6
        bad = []
        if "ns_agent.compiler" not in str(req.get("compiled_by") or ""):
            bad.append("提示词不是系统编译器输出（compiled_by 缺 ns_agent.compiler）")
        bakeoff = req.get("scope") == "bakeoff"       # BAKEOFF R11-12 A/B（只限 scope=bakeoff，不进生产）：认官方 <imageN> 写法
        nums = sorted({int(x) for x in REF_LINE.findall(prompt)} |
                      ({int(x) for x in IMG_TAG.findall(prompt)} if bakeoff else set()))
        if refs and nums != list(range(1, len(refs) + 1)):
            bad.append(f"参考图 {len(refs)} 张，但提示词里“图N是…”标注为 {nums}")
        for s in (rec.get("slots") or []):
            line = s.get("line") or ""
            alt = re.sub(r"图(\d+)", r"<image\1>", line) if bakeoff else line
            if s.get("kind") != "face" and line and line not in prompt and alt not in prompt:
                bad.append(f"图{s.get('index')} 的“必须一致”标注不在提示词里")
                break
        from ns_agent import framing as _FR
        if _FR.framing_clash(prompt):     # K-REN-902（IMGLAB 11-02）：特写“脸占六成”与“两张脸都入画”同时出现 = 构图矛盾
            bad.append("构图矛盾：同时写了“脸部占画面约六成”和“两张脸都清晰入画”（特写 + ≥2 人露脸，K-REN-902）")
        add("I6", "fail" if bad else "pass", "；".join(bad) if bad else "编译器输出 + 参考逐一标注")
        # I7
        suf = ST.preset_suffix()
        hits = ST.banned_hits(prompt)
        bad = []
        if hits:
            bad.append(f"出现禁用后缀词：{hits}")
        if suf and suf not in prompt and not (bakeoff and req.get("suffix_variant")):
            # BAKEOFF A/B（scope=bakeoff 且声明 suffix_variant）可换后缀，禁用词照查；生产不放
            bad.append(f"没有默认出图预设（{c.get('suffix_preset')}）的系统后缀")
        add("I7", "fail" if bad else "pass", "；".join(bad) if bad else f"预设 {c.get('suffix_preset')} 后缀")
    else:
        ref2va = "ref2va" in str(req.get("mode") or "").lower() or "ref2va" in str(req.get("model") or "").lower()
        ff = req.get("first_frame_postflight") or {}
        if ref2va:
            # 契约 §3“或 Ref2VA 的身份 + 造型参考”（VIDEO10 提议、REFLOCK 定）：每个在画露脸角色都要有已登记身份图
            slots = req.get("ref_slots") or []
            have = {s.get("character"): s.get("path") for s in slots if s.get("role") == "identity"}
            on = [x.get("name") for x in (req.get("cast") or []) if x.get("presence") == "在画"]
            reg = registered_identity_files()
            miss = [n for n in on if n not in have]
            unreg = [f"{n}:{p}" for n, p in have.items() if n in on and _relpath(p) not in reg]
            bad = ([f"缺身份参考：{miss}"] if miss else []) + ([f"不是已登记身份图：{unreg}"] if unreg else [])
            add("I2", "fail" if bad else "pass", "；".join(bad) if bad else f"Ref2VA 身份参考覆盖 {len(on)} 人（已登记）",
                refs=have)
            looks = [s for s in slots if s.get("role") in ("outfit", "sheet", "look")]
            if req.get("look_refs") or any(s.get("role") == "outfit" for s in slots):
                # VIDEO10 造型槽（11-01 REFLOCK 审）：每个在画角色一张，且必须是已选定设定图或它的系统裁切（refcrops/<设定图名>_<栏>.png）
                chosen = registered_sheet_files(req.get("project"))
                by = {s.get("character"): s for s in looks}
                miss = [n for n in on if n not in by]
                unreg = [f"{n}:{s.get('path')}" for n, s in by.items() if n in on and not look_file_registered(s, chosen)]
                bad = ([f"缺造型参考：{miss}"] if miss else []) + ([f"不是已选定设定图 / 其裁切：{unreg}"] if unreg else [])
                add("I3", "fail" if bad else "pass", "；".join(bad) if bad else f"Ref2VA 造型参考覆盖 {len(on)} 人（已选定设定图裁切）",
                    looks={n: s.get("path") for n, s in by.items()})
            else:
                add("I3", "pass" if looks or not on else "fail",
                    f"造型参考 {len(looks)} 张" if looks or not on else "Ref2VA 没有造型参考（造型设定图 / 单品），服装只靠文字")
            for i in ("I4", "I5", "I9"):
                add(i, "na", "Ref2VA：单品 / 场景由造型参考与提示词承载（视频 postflight 查一致）")
        else:
            for i in ("I2", "I3", "I4", "I5", "I9"):
                if i == "I2":
                    add(i, "pass" if ff.get("ok") else "fail",
                        "首帧已过 postflight（身份 / 造型 / 场景由首帧承载）" if ff.get("ok") else "视频必须用已通过 Q1–Q7 的首帧")
                else:
                    add(i, "na", "视频：由首帧 postflight 承载")
        add("I6", "pass" if "compiler" in str(req.get("compiled_by") or "") else "fail", "视频提示词须系统编译（官方格式）")
        add("I7", "na", "视频后缀按视频配方")

    # I8 LoRA
    allow = set(c.get("lora_allow") or {})
    scope = req.get("scope")
    if scope:                                       # 作用范围白名单（例：bakeoff 的步数蒸馏 LoRA，不进生产）
        allow |= {k for k in ((c.get("lora_allow_scoped") or {}).get(scope) or {}) if not k.startswith("_")}
    banned = c.get("lora_banned") or {}
    bad = []
    for f, _w in [tuple(x)[:2] for x in req.get("loras") or []]:
        if f in banned:
            bad.append(f"{f} 已禁用（{banned[f][:40]}…）")
        elif kind == "image" and allow and f not in allow:
            bad.append(f"{f} 不在白名单（knowledge 已确认有效的出图 LoRA：{sorted(allow)}）")
    for t, why in (c.get("trigger_banned_in_image") or {}).items():
        if kind == "image" and re.search(rf"(^|[，,\s]){re.escape(t)}([，,\s]|$)", prompt):
            bad.append(f"提示词里有禁用触发词 {t}（{why}）")
    add("I8", "fail" if bad else "pass", "；".join(bad) if bad else "LoRA 都在白名单", loras=req.get("loras") or [])
    # I10
    HC = _hc()
    iss = [x for x in HC.check_text(prompt) + HC.check_look_lock(prompt) if x.get("level") == "block"]
    add("I10", "fail" if iss else "pass", "；".join(x["message"] for x in iss) if iss else "成年人 / 锁定外貌检查通过")
    order = {k: n for n, k in enumerate(TITLES)}
    items.sort(key=lambda i: order.get(i.id, 99))
    return ContractResult("preflight", str(req.get("shot_id") or req.get("id") or "?"), items, c.get("version", ""))


def enforce(req: dict) -> ContractResult:
    """提交入口调用：不过就抛 ContractViolation（拒交）"""
    r = check(req)
    if not r.ok:
        raise ContractViolation(r)
    return r


def run(kind: str, payload: dict) -> dict:
    """统一签名（EDITDEL / VIDEO10 / BAKEOFF 等调用）：preflight(kind, payload) → {ok, items, blocking, reasons, ...}"""
    req = dict(payload or {})
    req.setdefault("kind", kind)
    r = check(req)
    d = r.to_dict()
    d["reasons"] = r.reasons()
    return d


class _Callable(__import__("types").ModuleType):
    def __call__(self, kind: str, payload: dict) -> dict:
        return run(kind, payload)


sys.modules[__name__].__class__ = _Callable
