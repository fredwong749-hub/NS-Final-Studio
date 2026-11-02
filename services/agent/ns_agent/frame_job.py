"""全系统唯一的首帧 / 尾帧出图作业构建（K-REN-134“全系统只有一条出图路径”，总调度 2026-11-01 P0）。

项目方原话（11-01 01:13 截图）：“你现在生成的人物不是林晚真实的形象……肯定有 bug……修复 reference 图片的 bug”。
查实：画布“重出首帧”走 ns_render.pipeline.render_image 的旧换脸式两步（图1 = 旧首帧构图，图2 = 旧母版裁切
data/cache/refs/master_face_b8e7b00b6756 = ar-c2351c9dcf），完全绕开 v9 配方、asset_refs 槽位与生成契约。

现在所有入口（tools/pipeline/image_jobs.py、tools/assetmaster/frames_v2.py、画布 frame-jobs 重出 / 尾帧 / 编辑整图重出）
都用这里的 build_first / build_last 得到作业，再由 ns_render.unified_frame.build_graph 得到 ComfyUI 图：
    提示词 = asset_refs 槽位标注（“图N是…必须完全一致”）+ 编译器输出（角色锁去服装、S★ 后缀、禁用 LoRA 剔除）
    参考   = asset_refs 槽位（项目方挑定的身份脸 > 去头造型图 > 景别单品 / 参考板 > 场景底图）
    闸门   = ns_agent.gen_contract.preflight（不过不提交）/ postflight
"""
from __future__ import annotations

from ns_agent import asset_refs as AR
from ns_agent import compiler as C


def retrigger(shot, g):
    """P4 / 系统剧本里 img / motion 句首的触发词按系统触发词表标出（编译器据此剥离 / 保留）"""
    table = {t.trigger for t in g.lora_triggers}

    def split(text):
        out = []
        for t in [x.strip() for x in (text or "").split("，")]:
            if t in table or t.startswith("pose_"):
                out.append(t)
            else:
                break
        return out
    it, mt = split(shot.img_prompt), split(shot.motion_prompt)
    return shot.model_copy(update={"img_triggers": it or list(shot.img_triggers),
                                   "motion_triggers": mt or list(shot.motion_triggers)})


def compile_frame(ep, shot, g, project: str | None, *, bible=None, available=None, assets: bool | None = None,
                  model: str = "qwen_image_2.1", legacy_refs: list[str] | None = None, role_lines=None, **plan_kw):
    """→ (提示词, CompiledShot, ShotRefs | None, SlotPlan | None)。assets=False 只给对照实验（旧做法：只挂脸）"""
    from ns_agent.bible import load_bible
    from ns_agent.gen_contract import style as ST
    use_assets = bool(project and AR.project_cfg(project)) if assets is None else assets
    if use_assets:
        g, _removed = AR.locks_without_wardrobe(g)          # K-AST-232
    c = C.compile_shot(ep, retrigger(shot, g), g, set(available or ()), image_style=ST.image_suffix(),
                       bible=bible or load_bible(), framing_project=project)
    if not use_assets:
        return (role_lines(legacy_refs or []) if role_lines else "") + c.image_prompt, c, None, None
    # 资产规划用编译器真正保留的触发词判主体（LoRA 不可用被剥掉的鞋触发词不算证据），与编译器同口径（REFLOCK 11-01）
    plan_kw.setdefault("kept_triggers", [t for t in (AR.g(shot, "img_triggers") or []) if t not in (c.dropped_triggers or [])])
    sr, plan = AR.plan_for(project, ep, shot, model, **plan_kw)
    note = (plan.prompt_note + outer_items_note(project, ep, shot, sr, c.image_prompt) + eyeline_note(shot, sr, c.image_prompt)
            + garment_detail_note(project, ep, shot, sr, c.image_prompt))
    return plan.prompt_prefix + with_note(c.image_prompt, note), c, sr, plan


# K-REN-101（总调度 11-01 07:35，VIDEO10 查出 ep01 首帧丢了造型 A 的短款西装外套：剧本 img 行没写外套，图就照着出了）：
# 本镜景别可见的造型单品（与 asset_refs.resolve_shot 给设定图 / 单品排参考时同一份清单：本集造型 parts ∩ 景别可见区，
# 去掉 marker，备选单品按 part_active）里，正文没写到的，用一句固定说明补进出图正文（风格后缀之前，同 with_note）。
# 剧本原文不改。固定句式改了 → 同一次改动里让 ns_api.unified_stale.match_target 认得出（OUTER_NOTE_RE），否则新版本会被误标过期
OUTER_NOTE = AR.OUTER_ITEMS_NOTE          # 句式与识别式唯一来源：asset_refs（TEXT_NOTE_RES，DATAALIGN 11-01 合并）
OUTER_NOTE_RE = AR.OUTER_ITEMS_RE


# 造型登记名 → 出图时更明确的叫法（模型对“西装裙”常画成西裤；造型 A 的 EN 是 dark grey pencil skirt）
GARMENT_ALIAS = {"深灰西装裙": "深灰铅笔裙 / 深灰西装裙——及膝裙，不是长裤"}


def outer_items(project: str, ep, shot, sr=None, body: str | None = None) -> list[tuple[str, str, list[str]]]:
    """→ [(名字, 造型, [本镜景别可见、正文没写到的单品短名])]；与 asset_refs.resolve_shot 的可见单品同一套规则"""
    img = AR.g(shot, "img_prompt") or ""
    n_ep = int(AR.g(ep, "number") or 0)
    _size, subject, zones = AR.visible_zones(img)
    if subject in ("part", "object") or not (zones - {"face"}):
        return []
    looks = AR.load_looks(project)
    chars = (sr.characters if sr is not None else None) or []
    out = []
    for ch in chars:
        cid, lid, name = ch.get("character"), ch.get("look"), ch.get("name") or ch.get("character")
        L = (looks.get(cid) or {}).get(lid) if lid else None
        if L is None:
            continue
        # 服装件（outfit：上衣 / 外套 / 下装）不按景别裁：模型常把近景画宽，露出的下装若没被点名就会自己编（总调度 11-01：
        # ep01-S5 近景三次都画成黑长裤，造型 A 是深灰西装裙 / 铅笔裙）；鞋、饰品、指甲仍按景别可见区
        # ⤴ IMGFIX 11-01（总调度 fredw-2b 21:5x）：特写例外——特写只补景别内看得到的单品。ep01-S1 特写被补了“深灰铅笔裙——及膝裙”，
        # 模型为画出裙子把特写拉成中景（data/ab/imgfix 全部 S1 出图都是坐姿中景）；近景及更远照旧补全部服装件
        loose = _size != "特写"
        vis = [x for x in L.parts if (x.zone in zones or (loose and x.slot == "outfit")) and x.slot != "marker"
               and AR.part_active(x, n_ep, img)]
        # K-REN-707（开关 close_no_lower）：特写 / 近景 / 中近景不补看不见的下半身单品 / 描述（露出长腿、裙、鞋）
        if AR.FR.close_no_lower() and _size in AR.FR.CLOSE_NO_LOWER:
            vis = [x for x in vis if AR.FR.visible(AR._short(x.label), _size)]
        if any(x.extra and x.slot == "shoes" for x in vis):
            vis = [x for x in vis if not (x.slot == "shoes" and not x.extra)]
        names = []
        for x in sorted(vis, key=lambda x: AR.ZONE_ORDER.get(x.zone, 9)):
            orig = AR._short(x.label)
            lab = GARMENT_ALIAS.get(orig, orig)
            text = body if body is not None else img          # 出图正文（编译器会按景别删掉剧本里的服装词）没写到才补
            if orig and orig not in text and lab not in names:
                names.append(lab)
        if names:
            out.append((name, lid, names))
    return out


def outer_items_note(project: str, ep, shot, sr, body: str = "") -> str:
    items = outer_items(project, ep, shot, sr, body=body or None)
    return "".join(OUTER_NOTE.format(name=n, lid=lid, items="、".join(xs)) + "。" for n, lid, xs in items if xs)


# ACTING 11-01（R11-2 / R11-8）：出图正文没写视线（frame_spec.GAZE_WORDS 一个都没有）时，补一句固定视线说明；
# 句式唯一来源 asset_refs.EYELINE_NOTE（进 TEXT_NOTE_RES，ns_api.unified_stale.match_target 自动认）。落点取本镜第一拍 视线=（剧本原文），
# 没写就用“画面里的人或物”。剧本原文不改；局部 / 物件特写不加
GAZE_WORDS = ("看", "望", "瞥", "视线", "眼神", "盯", "目光", "迎上", "垂眼", "闭眼", "抬眼")


def first_beat_gaze(shot) -> str:
    import re as _re
    for e in AR.g(shot, "extras") or []:
        if str(AR.g(e, "label") or "").startswith("分拍"):
            m = _re.search(r"视线\s*[=＝]\s*([^｜|；;]{1,30})", str(AR.g(e, "text") or ""))
            v = (m.group(1).strip() if m else "").strip("。，")
            if v and v not in ("—", "-", "无") and "镜头" not in v:
                return v
    # 导入后的系统剧本不带 分拍：退到 motion 行里第一处“视线 / 目光 + 转向 / 落在 / 停在 / 看向 …”的落点
    m = _re.search(r"(?:视线|目光)(?:转向|落在|停在|移向|看向|投向|盯着|锁在)([^，。；—]{1,20})", str(AR.g(shot, "motion_prompt") or ""))
    if m and "镜头" not in m.group(1):
        return m.group(1).strip()
    return ""


def _first_beat(shot) -> str:
    for e in AR.g(shot, "extras") or []:
        if str(AR.g(e, "label") or "").startswith("分拍"):
            return str(AR.g(e, "text") or "").split("；", 1)[0]
    return ""


def _react_gaze(beat: str, name: str) -> str:
    """第一拍 反应=“<名字>：视线落在…，…” → 落点（剧本原文）"""
    import re as _re
    m = _re.search(r"反应\s*[=＝][^｜|]*?" + _re.escape(name) + r"\s*[:：]?([^｜|；;]{1,40})", beat)
    if not m:
        return ""
    g = _re.search(r"(?:视线|目光)(?:落在|停在|移向|转向|看向|投向|锁在)?([^，。、]{1,20})|(?:看向|望向|看着|盯着|瞥向)([^，。、]{1,20})", m.group(1))
    v = ((g.group(1) or g.group(2)) if g else "").strip()
    return "" if (not v or "镜头" in v) else v


def _covered(body: str, names: list[str]) -> set:
    """正文按小句归人（同 QW-A7）：归给某人的小句里有视线词就算写了；写实套话“眼睛为真实人眼大小”不算"""
    import re as _re
    b = (body or "").replace("眼睛为真实人眼大小", "")
    here = [n for n in names if n in b]
    segs, cur = {n: "" for n in here}, None
    # 按逗号 / 分号切小句、按主语归人（与 tools/qa/acting_lints.person_clauses 同一套切法，改一处要同步另一处）
    for cl in _re.split(r"[，,；;。]", b):
        c = cl.strip()
        if not c:
            continue
        lead = next((n for n in here if c.startswith(n) or c[1:].startswith(n)), None)
        if lead:
            cur = lead
        for n in here:
            if _re.search(_re.escape(n) + r"(?:的)?(?:视线|目光|眼神|垂眼|垂眸|抬眼|闭眼|看|望|盯|瞥)", c):
                segs[n] += c + "，"
        if cur:
            segs[cur] += c + "，"
    return {n for n, seg in segs.items()
            if any(w in seg for w in GAZE_WORDS) or any(w in seg for w in ("背对", "背影", "背身"))}


def eyeline_note(shot, sr, body: str) -> str:
    """SCRIPT-RSI 11-01（D-SCR-07，项目方 18:2x“所有图片不要看镜头”）：⤴ 原先只给第一个人、且正文有任何视线词就整句不加——
    双人镜第二个人没写视线时照样默认看镜头。现在逐人判断：在画的人里谁那一段没写视线，就给谁补一句固定的正向落点句。
    落点：第一拍的主角取 视线=，其他人取第一拍 反应= 里自己的视线；都没有时，多人镜看另一个在画的人，单人镜写“画面里的人或物”。"""
    img = AR.g(shot, "img_prompt") or ""
    _size, subject, _zones = AR.visible_zones(img)
    if subject in ("part", "object"):
        return ""
    chars = (sr.characters if sr is not None else None) or []
    names = [n for n in (c.get("name") or c.get("character") for c in chars) if n] or [
        AR.g(c, "name") for c in AR.g(shot, "cast") or [] if AR.g(c, "presence") == "在画" and AR.g(c, "name")]
    names = list(dict.fromkeys(names))
    # K-REN-903（IMGLAB 11-02，ep05-S3/S6/S7 局部人物被补“视线落在对方的脸上”→ 画出整张脸）：视线句只给露脸的人补，
    # 落点也不写不露脸的人的脸
    if AR.FR.partial_only_enabled() and AR.g(shot, "cast") is not None:
        faced = set(AR.FR.faced_people(shot, names)[0])
        names = [n for n in names if n in faced]
    if not names:
        return ""
    if len(names) == 1:
        if any(w in (body or "").replace("眼睛为真实人眼大小", "") for w in GAZE_WORDS):
            return ""
        return AR.EYELINE_NOTE.format(name=names[0], target=(first_beat_gaze(shot) or "画面里的人或物")[:30]) + "。"
    done = _covered(body, names)
    beat = _first_beat(shot)
    act = beat.split("｜")[1] if beat.count("｜") >= 1 else ""
    hits = sorted((act.find(n), n) for n in names if n in act)
    lead = hits[0][1] if hits else names[0]
    out = []
    for n in names:
        if n in done:
            continue
        t = (first_beat_gaze(shot) if n == lead else _react_gaze(beat, n)) or next(
            (f"{o}的脸" for o in names if o != n), "画面里的人或物")
        t = t.strip()[:30]
        out.append(AR.EYELINE_NOTE.format(name=n, target=t[:-1] if t.endswith("上") and len(t) > 1 else t) + "。")
    return "".join(out)


def garment_detail_note(project: str, ep, shot, sr, body: str = "") -> str:
    """IMGFIX r5（总调度 fredw-2b 11-02）：在画（或局部背影）且上身入画的人，本造型外层单品的衣橱登记描述补一句
    （例：“林晚的短款西装外套：两只袖子都是深灰西装袖，露米白衬衫袖口”）。局部 / 物件特写、上身不入画不加；正文已有这句不重复"""
    img = AR.g(shot, "img_prompt") or ""
    _size, subject, zones = AR.visible_zones(img)
    if subject in ("part", "object"):
        return ""
    out = []
    for ch in (sr.characters if sr is not None else None) or []:
        name, cid, lid, pr = ch.get("name"), ch.get("character"), ch.get("look"), ch.get("presence", "在画")
        back = pr == "局部" and AR.back_part(shot, name)
        if not (pr == "在画" or ch.get("face_described") or back):
            continue
        if not back and not (zones & {"upper", "body"}):
            continue
        for label, desc in AR.garment_details(project, cid, lid):
            s = AR.GARMENT_DETAIL_NOTE.format(name=name, label=label, desc=desc)
            if s not in (body or "") and desc not in (body or ""):
                out.append(s + "。")
    return "".join(out)


def with_note(body: str, note: str) -> str:
    """槽位不足的文字说明放在正文末尾、系统风格后缀之前：景别句永远是参考标注之后的第一句（K-REN-101）"""
    if not note:
        return body
    from ns_agent.gen_contract import style as ST
    suf = ST.image_suffix()
    i = body.rfind(suf) if suf else -1
    if i > 0:
        head = body[:i].rstrip("，, ")
        return f"{head}，{note.rstrip('。')}，{body[i:]}"
    return f"{body.rstrip('。')}。{note}"


def cast_of(shot) -> list[dict]:
    return [{"name": AR.g(c, "name"), "presence": AR.g(c, "presence"), "x": AR.g(c, "x"), "depth": AR.g(c, "depth")}
            for c in (AR.g(shot, "cast") or [])]


def build_first(project: str, ep, shot, g, *, bible=None, model: str = "qwen_image_2.1", prompt_override: str | None = None,
                **plan_kw) -> dict:
    """首帧作业（= 生成契约请求的超集）。prompt_override：画布一次性整段替换的正文（槽位标注照加在前面）"""
    from ns_agent.gen_contract import style as ST
    n = int(AR.g(ep, "number"))
    sid = f"ep{n:02d}-S{AR.g(shot, 'index')}"
    full, c, sr, plan = compile_frame(ep, shot, g, project, bible=bible, model=model, **plan_kw)
    body = full[len(plan.prompt_prefix):]
    if prompt_override:
        body = prompt_override if ST.preset_suffix() in prompt_override else f"{prompt_override}，{ST.image_suffix()}"
        body = with_note(body, plan.prompt_note + outer_items_note(project, ep, shot, sr, body) + eyeline_note(shot, sr, body)
                         + garment_detail_note(project, ep, shot, sr, body))
    return {"id": sid, "shot": sid, "ep": n, "index": AR.g(shot, "index"), "stage": "image", "model": model,
            "prompt": plan.prompt_prefix + body, "refs": plan.files, "asset_refs": AR.record(sr, plan), "cast": cast_of(shot),
            "loras": [["krea2_film_texture_qwen21.safetensors", 0.5]],
            "compiled_by": "ns_agent.frame_job.build_first → ns_agent.compiler.compile_shot", "framing_project": project,
            "recipe": "frame_v9（K-REN-134 唯一出图路径）", "last_prompt": c.last_prompt,
            "face_files": [s.file for s in plan.slots if s.kind == "face"], "compiler_inputs_sha": c.inputs_sha}


def build_last(first_job: dict, first_file: str, *, prompt_override: str | None = None) -> dict:
    """尾帧：通过契约的首帧作图1、项目方挑定的身份脸作图2；提示词 = 编译器 last_prompt（与 ASSETMASTER frames_v2 同法）"""
    faces = list(first_job.get("face_files") or [])[:1]
    lines = ""
    if faces:
        lead = next((s.get("character") for s in (first_job["asset_refs"].get("slots") or []) if s.get("kind") == "face"), "主角")
        lines = f"图2是{AR.ID_NAME.get(lead, lead)}的脸部参考（只取脸和发型，必须一致）。"
    return {**first_job, "id": first_job["id"] + ":last", "stage": "last",
            "prompt": lines + (prompt_override or first_job.get("last_prompt") or ""), "refs": [first_file] + faces}


# =====================================================================================================
# IMGMASTER 分段编译（L-118，docs/imgmaster/DESIGN.md；开关 config/compile/imgmaster.yaml imgmaster.enabled，默认关）
# 固定五段：[景别·镜头] [场景连续性块] [人物块] [本镜动作] [约束句]，前面是“参考标注头”（槽位分配函数产出，不是一段）。
# 其它规则只能登记成插件（config/compile/plugins.yaml）改本段；插件签名 (segment_text, shot, continuity) -> segment_text。
# P1 只提供只读试编（compile_frame_v2），build_first / build_last 在开关关闭时一字不改。
# =====================================================================================================
import hashlib as _hl
import json as _json
import re as _re
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[3]
SEGMENTS = ("framing", "continuity", "characters", "action", "constraints")
_ENV_WORDS = _re.compile(r"光|灯|窗|墙|背景|虚化|霓虹|光斑|夜色|天色|地板|地面|走廊|楼道|街")
_SIDE_OBJ = ("台灯", "走廊", "窗", "门", "电梯", "屏幕")


class CompileError(RuntimeError):
    """分段编译失败关闭：未登记插件 / 段名不对 / 规则不存在或没有 check / continuity 缺失"""


def _sha(s) -> str:
    return _hl.sha256((s if isinstance(s, bytes) else str(s).encode("utf-8"))).hexdigest()[:12]


def imgmaster_cfg() -> dict:
    import yaml
    p = _ROOT / "config/compile/imgmaster.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("imgmaster", {}) if p.is_file() else {}


def imgmaster_enabled() -> bool:
    return bool(imgmaster_cfg().get("enabled", False))


def _rules_with_check() -> dict:
    import yaml
    out = {}
    for f in sorted((_ROOT / "knowledge/rules").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for r in (d.get("rules") if isinstance(d, dict) else d) or []:
            if isinstance(r, dict) and r.get("id"):
                out[r["id"]] = {"check": r.get("check"), "file": f.relative_to(_ROOT).as_posix()}
    return out


PLUGIN_IMPL: dict = {}


def plugin(pid: str):
    """登记插件实现；必须在 plugins.yaml 有 enabled 条目（load_plugins 校验）"""
    def deco(fn):
        PLUGIN_IMPL[pid] = fn
        return fn
    return deco


def load_plugins(path=None, rules: dict | None = None, impl: dict | None = None) -> list[dict]:
    """读登记表并校验（失败关闭）；→ 按 (段顺序, order) 排好的条目（含 enabled=false 的，调用方自己筛）"""
    import yaml
    p = _Path(path) if path else _ROOT / "config/compile/plugins.yaml"
    rows = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("plugins") or []
    rules = _rules_with_check() if rules is None else rules
    impl = PLUGIN_IMPL if impl is None else impl
    seen = set()
    for r in rows:
        pid = r.get("id")
        if not pid or pid in seen:
            raise CompileError(f"插件 id 缺失或重复：{pid}")
        seen.add(pid)
        if r.get("segment") not in SEGMENTS:
            raise CompileError(f"插件 {pid} 的 segment={r.get('segment')} 不是五段之一 {SEGMENTS}")
        if not r.get("enabled"):
            continue
        rid = r.get("rule_id")
        if not rid or rid not in rules:
            raise CompileError(f"插件 {pid} 的 rule_id={rid} 在 knowledge/rules 里不存在")
        if not rules[rid]["check"]:
            raise CompileError(f"插件 {pid} 的规则 {rid} 没有 check（G1：每个判断有 decider 和 check）")
        if pid not in impl:
            raise CompileError(f"插件 {pid} 已登记但代码里没有 @plugin 实现")
    on = {r["id"] for r in rows if r.get("enabled")}
    for pid in impl:
        if pid not in on:
            raise CompileError(f"代码里有插件 {pid} 但 plugins.yaml 没登记为 enabled（未登记插件不许跑）")
    return sorted(rows, key=lambda r: (SEGMENTS.index(r["segment"]), r.get("order", 0)))


# ---- continuity（HOLLYWOOD 导出，schema nsfs.scene_locks/1）
def load_continuity(path) -> dict:
    p = _Path(path)
    if not p.is_file():
        raise CompileError(f"continuity 文件不存在：{path}（失败关闭，不按“没有连续性块”出图）")
    raw = p.read_bytes()
    d = _json.loads(raw.decode("utf-8"))
    if d.get("schema") != "nsfs.scene_locks/1":
        raise CompileError(f"continuity schema 不对：{d.get('schema')}")
    d["_sha"] = _hl.sha256(raw).hexdigest()
    d["_file"] = str(path)
    return d


def scene_lock(cont: dict, scene_id: str) -> dict:
    sc = (cont.get("scenes") or {}).get(scene_id)
    if not sc:
        raise CompileError(f"continuity 里没有场景 {scene_id}")
    miss = [k for k in ("fixtures", "key_light", "blocking", "screen_direction") if not sc.get(k)]
    if miss:
        raise CompileError(f"场景 {scene_id} 定稿缺 {miss}")
    return sc


def continuity_sentence(sc: dict) -> str:
    """整场固定句式（同一场所有镜逐字相同）：主光 / 站位 / 屏幕方向"""
    return f"主光：{sc['key_light']}；站位与屏幕方向：{sc['screen_direction']}"


def _add_note(text: str, note: str | None) -> str:
    return text if not note else (text.rstrip("，。 ") + "，" if text else "") + note.rstrip("。")


_ACTION_WORDS = _re.compile(r"视线|目光|眼神|看|望|盯|朝|转|落在|张开|搭|扣|放|抖|握|拿|走向|走去|走到|走进|背对|坐在|站在|伸|按|敲|停|靠|抬|低头|垂")
_LIGHT_RE = _re.compile(r"台灯|屏幕.{0,3}光|霓虹|逆光|侧光|光斑")      # continuity 主光句涵盖的光源词；其它光源（例：安全出口绿光）不算重复


def _bigrams(t: str) -> set:
    t = _re.sub(r"[\s，。；、：|｜（）()“”\"*]", "", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


@plugin("cont_scene_block")
def _p_cont_scene_block(text, shot, cont):
    """场景表字段（去掉“光线：”，光由 continuity 主光统一给）+ 固定句 → 整场相同的【场景】块"""
    items = [x for x in text.replace("【场景】", "", 1).split("；") if x and not x.startswith(("光线：", "本镜场景："))]
    return "【场景】" + "；".join(items + [continuity_sentence(cont["lock"])])


@plugin("env_dedupe")
def _p_env_dedupe(text, shot, cont):
    """K-WRT-H25 的编译侧：正文里不带人名、不是人物动作 / 视线、且和 continuity（主光 + 站位 + 场景表）重复的环境 / 灯光分句删掉，
    环境只由 continuity 说一次；continuity 没说到的环境细节（例：安全出口绿光）保留"""
    names = cont.get("names") or []
    ref = _bigrams(continuity_sentence(cont["lock"]) + cont.get("scene_base", ""))
    keep = []
    for cl in text.split("，"):
        bc = _bigrams(cl)
        if (cl and _ENV_WORDS.search(cl) and not any(n in cl for n in names) and not _ACTION_WORDS.search(cl)
                and bc and (len(bc & ref) / len(bc) >= 0.5 or _LIGHT_RE.search(cl))):
            cont["dropped"].append({"plugin": "env_dedupe", "clause": cl})
            continue
        keep.append(cl)
    return "，".join(keep)


def _sides(txt: str) -> dict:
    """{物件: {轴: 值}}，轴 = lateral（左 / 右）| depth（后方 / 前方）；只在同一物件同一轴上比较"""
    out = {}
    for o in _SIDE_OBJ:
        for m in _re.finditer(r"(?:画面|在)(左|右)侧?的?" + _re.escape(o), txt or ""):          # “画面左侧走廊方向…”
            out.setdefault(o, {})["lateral"] = m.group(1)
        for m in _re.finditer(_re.escape(o) + r"(?:方向|暗处|尽头)?(?:在|位于|从|朝)?(?:画面)?([^，；。]{0,6})", txt or ""):
            seg = m.group(1)
            lat = _re.search(r"(左|右)", seg)
            dep = _re.search(r"(后方|身后|前方|后)", seg)
            if lat:
                out.setdefault(o, {})["lateral"] = lat.group(1)
            if dep:
                out.setdefault(o, {})["depth"] = "后" if dep.group(1) in ("后方", "身后", "后") else "前"
    return out


def _side_conflicts(detail: str, ref: dict) -> dict:
    got = _sides(detail)
    return {o: {ax: (v, ref[o][ax]) for ax, v in axes.items() if ax in ref.get(o, {}) and ref[o][ax] != v}
            for o, axes in got.items() if o in ref and any(ax in ref[o] and ref[o][ax] != v for ax, v in axes.items())}


@plugin("scene_detail_guard")
def _p_scene_detail_guard(text, shot, cont):
    """“本镜场景：…”里某物件的左右 / 前后和 continuity（主光 + 屏幕方向）不一致 → 删这个分句并记 trace"""
    ref = _sides(cont["lock"]["key_light"] + "。" + cont["lock"]["screen_direction"])
    keep = []
    for cl in _re.split(r"(?<=[，；])", text):
        c = cl.strip("，；")
        bad = _side_conflicts(c, ref)
        if bad and not _ACTION_WORDS.search(c):
            cont["dropped"].append({"plugin": "scene_detail_guard", "clause": c, "conflict": bad})
            continue
        if bad:
            cont.setdefault("warn", []).append({"plugin": "scene_detail_guard", "clause": c, "conflict": bad, "why": "含动作 / 视线，不自动删，需写作侧改"})
        keep.append(cl)
    return "".join(keep)


@plugin("outer_items")
def _p_outer_items(text, shot, cont):
    return _add_note(text, cont.get("outer_note"))


@plugin("eyeline")
def _p_eyeline(text, shot, cont):
    return _add_note(text, cont.get("eyeline_note"))


@plugin("garment_detail")
def _p_garment_detail(text, shot, cont):
    return _add_note(text, cont.get("garment_note"))


@plugin("text_fallback")
def _p_text_fallback(text, shot, cont):
    return _add_note(text, cont.get("fallback_note"))


def _split_old(c, shot, g) -> dict:
    """把现行编译输出（c.image_prompt，不含参考标注头和补句）按锚点拆回五段的原料"""
    from ns_agent.gen_contract import style as ST
    full = c.image_prompt
    scene = C.scene_segment(shot, g)
    i = full.find(scene) if scene else -1
    pre, post = (full[:i], full[i + len(scene):]) if i >= 0 else (full, "")
    j = pre.find("【")
    framing, rest = (pre[:j], pre[j:]) if j >= 0 else (pre, "")
    body_set = {x.strip() for x in (c.image_body or "").split("，") if x.strip()}
    frag_set = {x.strip() for f in (c.look_fragments or []) for x in f.split("，")}
    clauses = rest.split("，")
    # 人物块 / 动作段的分界 = 最后一个角色锁（“【名】”开头的分句）之后、剧本 img 原文第一个分句（景别词）出现处
    first_body = ((c.image_body or "").split("，")[0]).strip()
    start = max([n for n, x in enumerate(clauses) if x.strip().startswith("【")] + [0])
    k = next((n for n in range(start, len(clauses)) if first_body and clauses[n].strip() == first_body), None)
    if k is None:
        k = next((n for n in range(start, len(clauses)) if clauses[n].strip() in body_set and clauses[n].strip() not in frag_set), len(clauses))
    base, detail = scene.rsplit("；本镜场景：", 1) if "；本镜场景：" in scene else (scene, "")
    return {"framing": framing.strip("，"), "scene_base": base, "scene_detail": detail,
            "characters": "，".join(clauses[:k]).strip("，"), "action": "，".join(clauses[k:]).strip("，"),
            "constraints": post.strip("，"), "suffix": ST.image_suffix()}


def sid_of(ep, shot) -> str:
    return f"ep{int(AR.g(ep, 'number')):02d}-S{AR.g(shot, 'index')}"


def compile_frame_v2(ep, shot, g, project: str, cont: dict, *, bible=None, available=None, model: str = "qwen_image_2.1",
                     scene_looks=None, plugins_path=None, **plan_kw) -> dict:
    """分段编译（只读，不写任何文件）。→ {prompt, preamble, segments, trace, plan, sr, ctx}
    """
    from ns_agent.bible import load_bible
    from ns_agent.gen_contract import style as ST
    rows = load_plugins(plugins_path)
    g2, _removed = AR.locks_without_wardrobe(g)
    c = C.compile_shot(ep, retrigger(shot, g2), g2, set(available or ()), image_style=ST.image_suffix(),
                       bible=bible or load_bible(), framing_project=project)
    kept = plan_kw.get("kept_triggers") or [t for t in (AR.g(shot, "img_triggers") or []) if t not in (c.dropped_triggers or [])]
    sr = AR.resolve_shot(project, ep, shot, kept_triggers=kept, two_person=plan_kw.get("two_person"))
    plan = AR.plan_slots_v2(sr, model, plan_kw.get("capacity"), scene_looks)
    AR._apply_single_turn(plan, AR.single_turn_line(sr, shot))
    raw = _split_old(c, shot, g2)
    lock = scene_lock(cont, AR.g(shot, "scene_id"))
    names = [x.get("name") for x in sr.characters or [] if x.get("name")] + [AR.g(x, "name") for x in AR.g(shot, "cast") or []]
    ctx = {"lock": lock, "scene_base": raw["scene_base"], "names": [n for n in dict.fromkeys(names) if n], "dropped": [],
           "outer_note": outer_items_note(project, ep, shot, sr, c.image_prompt), "fallback_note": plan.prompt_note,
           "eyeline_note": eyeline_note(shot, sr, c.image_prompt), "garment_note": garment_detail_note(project, ep, shot, sr, c.image_prompt)}
    seg = {"framing": raw["framing"], "continuity": raw["scene_base"], "characters": raw["characters"],
           "action": raw["action"] + (("，本镜场景：" + raw["scene_detail"]) if raw["scene_detail"] else ""),
           "constraints": raw["constraints"]}
    suf = raw["suffix"]                       # S★ 风格后缀固定放全文最后（L-087 不动），不进任何插件的视野
    if suf and seg["constraints"].endswith(suf):
        seg["constraints"] = seg["constraints"][:-len(suf)].rstrip("，, ")
    sources = {k: [{"rule": "compiler.compile_shot", "file": "services/agent/ns_agent/compiler.py", "kind": "base"}] for k in SEGMENTS}
    sources["framing"][0]["rule_id"] = "K-REN-101"          # 景别首句原样透传（含 K-REN-123/902/903/705）
    applied = []
    for r in rows:
        if not r.get("enabled"):
            continue
        before = seg[r["segment"]]
        seg[r["segment"]] = PLUGIN_IMPL[r["id"]](before, shot, ctx)
        if seg[r["segment"]] != before:
            applied.append(r["id"])
            sources[r["segment"]].append({"plugin": r["id"], "rule_id": r["rule_id"], "order": r.get("order")})
    seg["constraints"] = "，".join(x for x in (seg["constraints"], suf) if x)
    prompt = plan.prompt_prefix + "，".join(seg[k].strip("，") for k in SEGMENTS if seg[k].strip("，"))
    pf = _Path(plugins_path) if plugins_path else _ROOT / "config/compile/plugins.yaml"
    trace = {"schema": "nsfs.compile_trace/1", "shot": sid_of(ep, shot), "model": model,
             "continuity": {"file": cont.get("_file"), "sha256": cont.get("_sha"), "scene": AR.g(shot, "scene_id")},
             "plugins_sha": _sha(pf.read_bytes()), "compiler_inputs_sha": c.inputs_sha, "bible_version": c.bible_version,
             "segments": [{"name": k, "sha": _sha(seg[k]), "chars": len(seg[k]), "sources": sources[k]} for k in SEGMENTS],
             "preamble": {"sha": _sha(plan.prompt_prefix),
                          "slots": [{"index": s.index, "kind": s.kind, "file": s.file, "character": s.character} for s in plan.slots],
                          "dropped": plan.dropped, "rule": "asset_refs.plan_slots_v2（身份脸 > 场景 > 本场造型 > 其它）"},
             "look_refs_via_text": [{"character": d.get("character"), "file": d["file"], "why": "造型参考因槽满走文字（总调度 11-02：双人镜不合成脸板，L-086 保真优先）"}
                                    for d in plan.dropped if d.get("role") != "scene"],
             "dropped_clauses": ctx["dropped"], "warnings": ctx.get("warn", []), "applied_plugins": applied, "prompt_sha": _sha(prompt)}
    return {"prompt": prompt, "preamble": plan.prompt_prefix, "segments": seg, "trace": trace, "plan": plan, "sr": sr, "ctx": ctx}


def write_compile_trace(trace: dict, out_dir) -> dict:
    """随 take 落账：trace 写成 <out_dir>/<shot>_<prompt_sha>.json，返回 {file, sha}（take 记录的 compile_trace 字段）。
    P1 不被任何出图路径调用；开关打开后由 build_first 返回作业时附带"""
    raw = _json.dumps(trace, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    d = _Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{trace['shot']}_{trace['prompt_sha']}.json"
    f.write_bytes(raw)
    return {"file": str(f), "sha": _hl.sha256(raw).hexdigest()}
