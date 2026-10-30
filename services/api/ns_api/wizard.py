"""
「新建剧」向导的后端逻辑（T42）：剧本三件套导入校验、风格 SOP → visual_bible.toml、示例提示词预览、
人物卡（参考图 / AI 生成虚构成年人确认 → face_reference.json / 造型 A-B-C 与排期 → data/looks）、LoRA 计划、成人开关。

只写项目目录（projects/<slug>/…），从不触发渲染。
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from ns_agent.compiler import classify_adult
from ns_agent.importer.script_md import SHOTS_PER_EPISODE, import_script
from ns_api.project_ctx import REPO, ProjectContext, now, read_json, write_json
from ns_schema.script import ScriptImport

TEMPLATE = REPO / "templates" / "visual_bible.template.toml"
SCRIPT_KINDS = {"script": "剧本和镜头", "image_doc": "image提示词", "corrector": "纠正器"}
DIALOGUE_CPS = 3.5          # SOP §2：对白每秒 ≤3.5 字
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
LORA_KINDS = {
    "identity_image": "身份 LoRA（图像，Qwen Image 2.1）",
    "identity_h3": "身份 LoRA（H3 视频）",
    "jewellery": "饰品 LoRA",
    "wardrobe": "服装 / 鞋 LoRA",
    "pose": "姿势 LoRA",
}
REALISM_LEVELS = {"low": 0.3, "mid": 0.5, "high": 0.7}   # 写实只作质感（krea2 胶片质感强度），不改人物长相


# ================================================================== 剧本导入与校验

def script_files(ctx: ProjectContext) -> dict[str, Path | None]:
    meta = ctx.settings().get("script_files", {})
    return {k: (ctx.root / meta[k]) if meta.get(k) and (ctx.root / meta[k]).is_file() else None for k in SCRIPT_KINDS}


def save_script_file(ctx: ProjectContext, kind: str, filename: str, data: bytes) -> str:
    if kind not in SCRIPT_KINDS:
        raise ValueError(f"kind 只能是 {list(SCRIPT_KINDS)}")
    if not filename.lower().endswith((".md", ".markdown", ".txt")):
        raise ValueError("剧本文件只接受 .md / .txt")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("文件不是 UTF-8 文本")
    safe = re.sub(r'[\\/:*?"<>|]+', "_", Path(filename).name)
    target = ctx.root / "script" / safe
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:      # 原件只读：同名不同内容时留备份
        target.rename(target.with_name(f"{target.name}.bak-{now().replace(':', '')}"))
    target.write_bytes(data)
    s = ctx.settings()
    s.setdefault("script_files", {})[kind] = f"script/{safe}"
    ctx.save_settings(s)
    return f"script/{safe}"


def _project_overrides(ctx: ProjectContext) -> dict:
    return read_json(ctx.adult_overrides, {}).get("force_adult", {})


def classify(ctx: ProjectContext, result: ScriptImport) -> None:
    """成人分类写进每镜（与 tools/import_script.py 相同的关键词判定）。人工指定只认本项目的 adult_overrides.json，
    不让《为他而骚》的人工名单串到新剧上。"""
    forced = _project_overrides(ctx) if not ctx.is_default else None
    for ep in result.episodes:
        for s in ep.shots:
            reasons = classify_adult(ep, s)
            if forced is not None:
                reasons = [r for r in reasons if not r.startswith("人工指定:")]
                if s.id in forced:
                    reasons.append(f"人工指定:{forced[s.id]}")
            s.adult_reasons, s.adult = reasons, bool(reasons)


def _corrector_summary(path: Path | None) -> dict | None:
    if not path:
        return None
    text = path.read_text(encoding="utf-8")
    rules = re.findall(r"^#{1,4}\s*(\d+(?:\.\d+)+)\s*(.*)$", text, re.M)
    return {"file": path.name, "chars": len(text), "rules": [f"{n} {t.strip()}"[:60] for n, t in rules][:40],
            "rule_count": len(rules)}


def validate_script(ctx: ProjectContext, write_import: bool = True) -> dict:
    """导入 + 校验，返回给向导的实时报告。fatal 非空 = 不能进入下一步。"""
    files = script_files(ctx)
    report: dict = {"files": {k: (p.name if p else None) for k, p in files.items()}, "fatal": [], "warnings": [],
                    "ok": False}
    if not files["script"]:
        report["fatal"].append("还没有上传《剧本和镜头》")
        return report
    try:
        result = import_script(files["script"], files["image_doc"])
    except Exception as e:                                   # 导入器只写 warning；这里防御格式彻底不对的文件
        report["fatal"].append(f"导入失败：{e}")
        return report
    classify(ctx, result)
    eps = result.episodes
    numbers = [e.number for e in eps]
    warnings = []
    for w in result.warnings:
        if w.startswith("缺少集数："):                       # 导入器按《为他而骚》60 集检查；新剧按实际最大集号重算
            continue
        warnings.append(w)
    if numbers:
        missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        if missing:
            warnings.append(f"缺少集数：{missing}")
    if not files["image_doc"]:
        warnings.append("没有上传《image提示词》：装饰状态表 / 基准图 / LoRA 注册表为空")
    if not files["corrector"]:
        warnings.append("没有上传《纠正器》：镜头类型规则用视觉圣经默认值")
    if not eps:
        report["fatal"].append("没有识别到任何一集（需要 “## ep01《标题》” 格式）")
    if not result.globals.character_locks:
        report["fatal"].append("没有找到角色锁（“每条prompt统一前缀”代码块里的【名字】描述）")

    declared = {t.trigger: t for t in result.globals.lora_triggers}
    used: dict[str, int] = {}
    per_ep, dur_src = [], {"script": 0, "default": 0}
    dlg_lines = dlg_shots = unparsed = adult = 0
    for ep in eps:
        issues = []
        total = sum(s.duration for s in ep.shots)
        ep_adult = sum(bool(s.adult) for s in ep.shots)
        adult += ep_adult
        if not SHOTS_PER_EPISODE[0] <= len(ep.shots) <= SHOTS_PER_EPISODE[1]:
            issues.append(f"{len(ep.shots)} 镜（应 {SHOTS_PER_EPISODE[0]}–{SHOTS_PER_EPISODE[1]}）")
        lines = 0
        for s in ep.shots:
            dur_src[s.duration_source if s.duration_source in dur_src else "default"] += 1
            for t in s.img_triggers + s.motion_triggers:
                used[t] = used.get(t, 0) + 1
            if s.dialogue:
                dlg_shots += 1
            lines += len(s.dialogue)
            unparsed += sum(1 for d in s.dialogue if d.speaker_note is None and d.stage is None and
                            not re.search(r"[“\"「]", s.dialogue_raw or ""))
            spoken = "".join(d.text for d in s.dialogue) + (s.voiceover.text if s.voiceover else "")
            chars = len(re.sub(r"[\s，。！？、…“”\"「」,.!?~～]", "", spoken))
            if s.duration and chars / s.duration > DIALOGUE_CPS:
                issues.append(f"S{s.index} 对白 {chars} 字 / {s.duration} 秒 > {DIALOGUE_CPS} 字/秒")
        dlg_lines += lines
        per_ep.append({"number": ep.number, "title": ep.title, "shots": len(ep.shots), "adult": ep_adult,
                       "seconds": total, "dialogue_lines": lines, "high_intensity": ep.high_intensity,
                       "decor": ep.shots[0].decor_state if ep.shots else None, "issues": issues})
        warnings += [f"ep{ep.number:02d} {i}" for i in issues if "字/秒" in i]
    unknown = sorted(t for t in used if t not in declared and not t.startswith("pose_"))
    report.update({
        "episodes": len(eps), "shots": sum(len(e.shots) for e in eps), "adult_shots": adult,
        "shots_rule": list(SHOTS_PER_EPISODE),
        "per_episode": per_ep,
        "durations": {**dur_src, "min": min((s.duration for e in eps for s in e.shots), default=0),
                      "max": max((s.duration for e in eps for s in e.shots), default=0)},
        "dialogue": {"lines": dlg_lines, "shots": dlg_shots, "unparsed": unparsed},
        "triggers": {"declared": sorted(declared), "used": used, "unknown": unknown,
                     "without_file": sorted(t for t, v in declared.items() if v.file is None)},
        "decor": {"ranges": len(result.globals.decor_schedule),
                  "states": sorted({r.state for r in result.globals.decor_schedule}),
                  "missing": [e.number for e in eps if result.globals.decor_schedule and
                              e.shots and e.shots[0].decor_state is None]},
        "character_locks": [c.model_dump() for c in result.globals.character_locks],
        "image_suffix": result.globals.image_suffix, "base_negative": result.globals.base_negative,
        "corrector": _corrector_summary(files["corrector"]),
    })
    report["warnings"] = warnings
    report["ok"] = not report["fatal"]
    if write_import and report["ok"]:
        ctx.import_dir.mkdir(parents=True, exist_ok=True)
        ctx.script_json.write_text(result.model_dump_json(indent=2), encoding="utf-8", newline="\n")
        report["import_file"] = ctx.rel(ctx.script_json)
        report["script_sha256"] = hashlib.sha256(files["script"].read_bytes()).hexdigest()
        _seed_characters(ctx, result)
        # 剧本变了 → 状态表 / 场景表重建（否则 SOP 读到旧表；sop.py 也会报 timeline_stale）
        from ns_agent.state_timeline import schedule_rebuild
        schedule_rebuild(ctx.root)
    write_json(ctx.import_dir / "validation.json", {**report, "at": now()})
    return report


def load_import(ctx: ProjectContext) -> ScriptImport | None:
    if not ctx.script_json.is_file():
        return None
    return ScriptImport.model_validate_json(ctx.script_json.read_text(encoding="utf-8"))


# ================================================================== 风格 SOP → visual_bible.toml

class Rule(BaseModel):
    id: str
    match: list[str]
    term: str


class StyleForm(BaseModel):
    lens: str = ""
    use_script_suffix: bool = True
    fallback_suffix: str = ""
    palette: str = ""                          # 调色描述（浓郁暖色……）
    style_negative: str = ""
    color_reference: str = ""                  # 项目内相对路径（上传后填）
    color_match_strength: float = Field(0.6, ge=0, le=1)
    realism_texture_strength: float = Field(0.5, ge=0, le=1)   # 写实只作质感
    materials: list[Rule] = Field(default_factory=list)
    shot_rules: list[Rule] = Field(default_factory=list)
    safe_term: str = ""
    safe_negative: str = ""
    soundscape_default: str = ""               # 每镜默认环境声（H3 overall_soundscape 兜底）
    voice_rule: str = ""                       # 主角固定声线
    single_voice: bool = True                  # 亲密/混合镜头只让一人发声（docs/intimate_audio.md）
    bgm_style: str = ""                        # 全剧配乐基调


def template_defaults() -> StyleForm:
    # 模板里的 [characters.<角色id>] 是占位写法（不是合法 TOML），解析前去掉人物段
    chunks = _chunks(TEMPLATE.read_text(encoding="utf-8"))
    t = tomllib.loads("\n".join(l for name, lines in chunks
                                if not (name or "").startswith("characters.") for l in lines))
    look, real = t.get("look", {}), t.get("realism", {})
    tex = next((l["strength"] for l in real.get("loras", []) if "krea2" in l.get("file", "")), 0.5)
    return StyleForm(
        lens=look.get("lens", ""), use_script_suffix=look.get("use_script_suffix", True),
        fallback_suffix=look.get("fallback_suffix", ""), style_negative=look.get("style_negative", ""),
        palette="浓郁饱和的暖色调电影调色，色彩丰富艳丽、通透明亮",
        color_match_strength=look.get("color_match_strength", 0.6), realism_texture_strength=tex,
        materials=[Rule(**m) for m in t.get("materials", [])],
        shot_rules=[Rule(**r) for r in t.get("shot_rules", [])],
        safe_term=t.get("shot_rules_safe", {}).get("term", ""),
        safe_negative=t.get("shot_rules_safe", {}).get("negative", ""),
        soundscape_default="安静室内环境音，轻微的衣料摩擦声与自然呼吸声，无人声对白",
        voice_rule="主角固定一条合成声线（普通话），全剧不变",
        bgm_style="克制的都市情感电子氛围，低频铺底，钢琴点缀，慢速",
    )


def style_form(ctx: ProjectContext) -> StyleForm:
    saved = ctx.settings().get("style")
    return StyleForm(**saved) if saved else template_defaults()


def tq(v) -> str:
    """Python 值 → TOML 字面量（JSON 字符串转义与 TOML basic string 兼容）"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(tq(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {tq(x)}" for k, x in v.items()) + " }"
    raise TypeError(type(v))


HEADER_RE = re.compile(r"^\s*(\[\[?)([^\]]+)\]\]?\s*(#.*)?$")


def _chunks(text: str) -> list[tuple[str | None, list[str]]]:
    """按表头切块：[(表名或 None, 行)]；[[x]] 表名记作 "[[x]]" """
    out: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            name = m.group(2).strip()
            out.append((f"[[{name}]]" if m.group(1) == "[[" else name, [line]))
        else:
            out[-1][1].append(line)
    return out


def _set(lines: list[str], key: str, value) -> None:
    for i, line in enumerate(lines):
        m = re.match(rf"^(\s*{re.escape(key)}\s*=\s*)(.*?)(\s{{2,}}#.*)?$", line)
        if m:
            lines[i] = f"{key} = {tq(value)}{m.group(3) or ''}"
            # 多行数组：把后续行一起替换掉（按方括号配平，模板里数组元素不含字符串内方括号）
            depth = m.group(2).count("[") - m.group(2).count("]")
            while depth > 0 and i + 1 < len(lines):
                nxt = lines.pop(i + 1)
                depth += nxt.split("#")[0].count("[") - nxt.split("#")[0].count("]")
            return
    # 键不在模板里：加在表的末尾（空行和分隔注释之前）
    j = len(lines)
    while j > 1 and (not lines[j - 1].strip() or lines[j - 1].lstrip().startswith("#")):
        j -= 1
    lines.insert(j, f"{key} = {tq(value)}")


def _char_block(c: dict) -> list[str]:
    cid = c["id"]
    lines = [f"[characters.{cid}]", f"name = {tq(c['name'])}", f"detect = {tq([c['name']])}",
             'identity_source = "script_lock"', f"identity_lock = {tq(c.get('description', ''))}",
             f"reference_master = {tq(f'assets/characters/{cid}/plates/master.png')}",
             f"reference_uploads = {tq(c.get('references', []))}",
             'reference_role_line = "图1只提供面部与发型：保持同一人的脸型、五官与发型，不要沿用图1的姿势、服装、首饰和背景。"',
             'face_ref_approval = "config/face_reference.json"',
             f"realism_strength = {tq(REALISM_LEVELS.get(c.get('realism', 'mid'), 0.5))}   # 写实只作质感，不改长相",
             f"nails = {tq(c.get('nails', ''))}", f"hair = {tq(c.get('hair', ''))}",
             f"heels_default = {tq(c.get('shoes', ''))}", f"wardrobe_rule = {tq(c.get('wardrobe', ''))}",
             f"makeup_palette = {tq(c.get('makeup', ''))}",
             'makeup_principles = "每款只有一个视觉焦点；腮红、唇色、眼影同一色温；雾面与水光对比；唇线边缘柔化；粉底下可见毛孔"',
             "", f"[characters.{cid}.makeup_states]",
             f"default = {tq({'plate': f'items/makeup/{cid}_default', 'episodes': 'default', 'name': c.get('makeup') or '日常'})}",
             ""]
    return lines


def render_visual_bible(ctx: ProjectContext, form: StyleForm, characters: list[dict], approved: dict | None) -> str:
    files = ctx.settings().get("script_files", {})
    chunks = _chunks(TEMPLATE.read_text(encoding="utf-8"))
    out: list[str] = [f"# 由「新建剧」向导生成（{now()}，T42）。规则含义见 docs/VISUAL_BIBLE.md；改规则只改本文件。", ""]
    done_mat = done_rule = done_char = False
    for name, lines in chunks:
        lines = list(lines)
        if name == "project":
            _set(lines, "name", ctx.name)
            _set(lines, "script", files.get("script", ""))
            _set(lines, "image_doc", files.get("image_doc", ""))
            _set(lines, "corrector_doc", files.get("corrector", ""))
            _set(lines, "slug", ctx.slug)
        elif name == "look":
            _set(lines, "use_script_suffix", form.use_script_suffix)
            _set(lines, "fallback_suffix", form.fallback_suffix)
            _set(lines, "lens", form.lens)
            _set(lines, "palette", form.palette)
            _set(lines, "style_negative", form.style_negative)
            _set(lines, "color_reference", form.color_reference)
            _set(lines, "color_match_strength", form.color_match_strength)
        elif name == "realism":
            _set(lines, "loras", [{"file": "krea2_film_texture_qwen21.safetensors", "strength": form.realism_texture_strength}])
            _set(lines, "realism_as_texture_only", True)
        elif name == "shot_rules_safe":
            _set(lines, "term", form.safe_term)
            _set(lines, "negative", form.safe_negative)
        elif name == "[[materials]]":
            if not done_mat:
                done_mat = True
                for m in form.materials:
                    out += ["[[materials]]", f"id = {tq(m.id)}", f"match = {tq(m.match)}", f"term = {tq(m.term)}", ""]
            continue
        elif name == "[[shot_rules]]":
            if not done_rule:
                done_rule = True
                for r in form.shot_rules:
                    out += ["[[shot_rules]]", f"id = {tq(r.id)}", f"match = {tq(r.match)}", f"term = {tq(r.term)}", ""]
            continue
        elif name and name.startswith("characters."):
            if not done_char:
                done_char = True
                for c in characters:
                    out += _char_block(c)
            continue
        out += lines
    out += ["", "# -------------------------------------------------------------------",
            "# 九、声音（docs/intimate_audio.md；向导生成）",
            "# -------------------------------------------------------------------", "[audio]",
            f"soundscape_default = {tq(form.soundscape_default)}", f"voice_rule = {tq(form.voice_rule)}",
            f"single_voice = {tq(form.single_voice)}", f"bgm_style = {tq(form.bgm_style)}", ""]
    if approved:
        out += ["[approval]", f"style_approved_by = {tq(approved.get('by', ''))}",
                f"style_approved_at = {tq(approved.get('at', ''))}", ""]
    text = "\n".join(out)
    tomllib.loads(text)                                   # 生成的文件必须能被解析
    return text


def save_style(ctx: ProjectContext, form: StyleForm) -> dict:
    s = ctx.settings()
    s["style"] = form.model_dump()
    s.setdefault("gates", {}).pop("G1", None)            # 改了风格就要重新确认
    ctx.save_settings(s)
    text = render_visual_bible(ctx, form, characters_list(ctx), None)
    ctx.visual_bible.parent.mkdir(parents=True, exist_ok=True)
    ctx.visual_bible.write_text(text, encoding="utf-8")
    return {"toml": text, "preview": style_preview(ctx, form)}


def confirm_style(ctx: ProjectContext, by: str) -> dict:
    s = ctx.settings()
    if "style" not in s:
        raise ValueError("先保存风格表单")
    rec = {"by": by or "项目方", "at": now()}
    s.setdefault("gates", {})["G1"] = rec
    ctx.save_settings(s)
    ctx.visual_bible.write_text(render_visual_bible(ctx, StyleForm(**s["style"]), characters_list(ctx), rec),
                                encoding="utf-8")
    return rec


def _pick_sample_shots(result: ScriptImport, n: int = 2):
    """两个真实镜头：优先不同集、非成人、带角色锁人物的镜头"""
    picked, eps_used = [], set()
    names = [c.name for c in result.globals.character_locks]
    for prefer_char in (True, False):
        for ep in result.episodes:
            for s in ep.shots:
                if len(picked) >= n:
                    return picked
                if s.adult or ep.number in eps_used or (s.id in {p[1].id for p in picked}):
                    continue
                if prefer_char and not any(nm in s.img_prompt for nm in names):
                    continue
                picked.append((ep, s))
                eps_used.add(ep.number)
    return picked


def assemble_preview(result: ScriptImport, ep, s, form: StyleForm, characters: list[dict]) -> dict:
    """按视觉圣经 [assembly] 顺序拼一条示例首帧提示词（预览；最终以编译器为准）"""
    g = result.globals
    body = s.img_prompt
    for t in s.img_triggers:
        body = re.sub(rf"^{re.escape(t)}[，,]\s*", "", body)
    dna = [f"【{c.name}】{c.description}" for c in g.character_locks if c.name in body]
    cards = {c["name"]: c for c in characters}
    looks = []
    for c in g.character_locks:
        card = cards.get(c.name)
        if card and c.name in body:
            bits = [card.get(k) for k in ("hair", "makeup", "nails") if card.get(k)]
            if bits:
                looks.append(f"{c.name}：" + "，".join(bits))
    text_all = s.img_prompt
    mats = [m.term for m in form.materials if any(w in text_all for w in m.match) and m.term not in text_all]
    rules = [r.term for r in form.shot_rules if any(w in body for w in r.match)]
    if not s.adult and form.safe_term:
        rules.append(form.safe_term)
    suffix = g.image_suffix if (form.use_script_suffix and g.image_suffix) else form.fallback_suffix
    lens = "" if ("Leica" in suffix or "徕卡" in suffix) else form.lens
    parts = [("触发词", "，".join(s.img_triggers)), ("角色锁", "；".join(dna)), ("人物造型", "；".join(looks)),
             ("剧本原文", body), ("材质规则", "，".join(mats)), ("镜头规则", "，".join(rules)),
             ("镜头", lens), ("风格后缀", suffix), ("调色", form.palette if form.palette not in suffix else "")]
    neg_terms = [t.strip() for x in [g.base_negative, form.style_negative, "" if s.adult else form.safe_negative]
                 for t in re.split(r"[、，,]", x or "") if t.strip()]
    neg = "、".join(dict.fromkeys(neg_terms))                # 去重，保留顺序
    return {"shot": s.id, "episode_title": ep.title, "parts": [{"label": k, "text": v} for k, v in parts if v],
            "prompt": "，".join(v for _, v in parts if v), "negative": neg,
            "color_reference": form.color_reference, "realism_texture_strength": form.realism_texture_strength}


def style_preview(ctx: ProjectContext, form: StyleForm | None = None) -> list[dict]:
    result = load_import(ctx)
    if not result:
        return []
    form = form or style_form(ctx)
    chars = characters_list(ctx)
    return [assemble_preview(result, ep, s, form, chars) for ep, s in _pick_sample_shots(result)]


# ================================================================== 人物

class LookForm(BaseModel):
    label: str                                 # A / B / C
    name: str = ""
    outfit: str = ""
    shoes: str = ""
    makeup: str = ""
    hair: str = ""
    nails: str = ""
    accessory: str = ""


class ScheduleRow(BaseModel):
    look: str                                  # A / B / C
    episodes: str                              # "1-10, 12"


class CharacterForm(BaseModel):
    name: str | None = None
    realism: str = "mid"                       # low | mid | high
    makeup: str = ""
    nails: str = ""
    hair: str = ""
    shoes: str = ""
    wardrobe: str = ""
    looks: list[LookForm] = Field(default_factory=list)
    schedule: list[ScheduleRow] = Field(default_factory=list)


def _seed_characters(ctx: ProjectContext, result: ScriptImport) -> None:
    """按角色锁建人物卡（已有的保留人工内容，只补新角色）"""
    s = ctx.settings()
    chars: dict = s.setdefault("characters", {})
    known = {c["name"]: cid for cid, c in chars.items()}
    for lock in result.globals.character_locks:
        if lock.name in known:
            chars[known[lock.name]]["description"] = lock.description
            continue
        cid = f"char{len(chars) + 1:02d}"
        chars[cid] = {"id": cid, "name": lock.name, "description": lock.description, "references": [],
                      "realism": "mid", "looks": [{"label": "A", "name": "日常"}],
                      "schedule": [], "confirmed": False}
    ctx.save_settings(s)


def characters_list(ctx: ProjectContext) -> list[dict]:
    return list(ctx.settings().get("characters", {}).values())


def _char(ctx: ProjectContext, cid: str) -> tuple[dict, dict]:
    s = ctx.settings()
    if cid not in s.get("characters", {}):
        raise KeyError(cid)
    return s, s["characters"][cid]


def update_character(ctx: ProjectContext, cid: str, form: CharacterForm) -> dict:
    s, c = _char(ctx, cid)
    data = form.model_dump(exclude_none=True)
    labels = [lk["label"] for lk in data.get("looks", [])]
    if len(set(labels)) != len(labels):
        raise ValueError("造型字母重复")
    for row in data.get("schedule", []):
        if row["look"] not in labels:
            raise ValueError(f"排期里的造型 {row['look']} 不存在")
        parse_episodes(row["episodes"])
    c.update(data)
    ctx.save_settings(s)
    write_looks(ctx)
    return c


def add_reference(ctx: ProjectContext, cid: str, filename: str, data: bytes) -> dict:
    s, c = _char(ctx, cid)
    ext = Path(filename).suffix.lower()
    if ext not in IMG_EXT:
        raise ValueError("参考图只接受 png / jpg / webp")
    d = ctx.assets_dir / "characters" / cid / "refs"
    d.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    p = d / f"ref_{sha[:10]}{ext}"
    p.write_bytes(data)
    rel = ctx.rel(p)
    if rel not in c["references"]:
        c["references"].append(rel)
    # 参考图变了：原确认作废，需要项目方重新确认
    if c.get("confirmed"):
        c.update(confirmed=False, approved_by=None, approved_at=None)
    ctx.save_settings(s)
    write_face_reference(ctx)
    return c


def remove_reference(ctx: ProjectContext, cid: str, rel: str) -> dict:
    s, c = _char(ctx, cid)
    if rel in c["references"]:
        c["references"].remove(rel)
        c.update(confirmed=False, approved_by=None, approved_at=None)
    ctx.save_settings(s)
    write_face_reference(ctx)
    return c


def confirm_character(ctx: ProjectContext, cid: str, confirmed: bool, by: str) -> dict:
    """「此角色为 AI 生成的虚构成年人」——只能由项目方本人在界面勾选（请求体 confirmed=true）"""
    s, c = _char(ctx, cid)
    if confirmed:
        if not c["references"]:
            raise ValueError("先上传至少一张参考图再确认")
        c.update(confirmed=True, approved_by=by or "项目方", approved_at=now())
    else:
        c.update(confirmed=False, approved_by=None, approved_at=None)
    ctx.save_settings(s)
    write_face_reference(ctx)
    return c


def write_face_reference(ctx: ProjectContext) -> dict:
    """config/face_reference.json：每个角色一条；顶层字段兼容 ns_render.pipeline.face_ref_approved（全部确认才为 true）"""
    chars = characters_list(ctx)
    entries = {c["id"]: {"name": c["name"], "ai_generated_fictional_adult": bool(c.get("confirmed")),
                         "approved_for_adult": bool(c.get("confirmed")), "approved_by": c.get("approved_by"),
                         "approved_at": c.get("approved_at"), "references": c.get("references", [])}
               for c in chars}
    confirmed = [c for c in chars if c.get("confirmed")]
    all_ok = bool(chars) and len(confirmed) == len(chars)
    latest = max(confirmed, key=lambda c: c.get("approved_at") or "", default=None)
    first_ref = next((r for c in chars for r in c.get("references", [])), None)
    rec = {"approved_for_adult": all_ok, "approved_by": latest.get("approved_by") if all_ok and latest else None,
           "approved_at": latest.get("approved_at") if all_ok and latest else None, "reference": first_ref,
           "note": "「新建剧」向导写入：每个角色由项目方在人物卡上勾选「此角色为 AI 生成的虚构成年人」。",
           "characters": entries}
    write_json(ctx.face_reference, rec)
    return rec


def parse_episodes(spec: str) -> list[int]:
    out: set[int] = set()
    for part in re.split(r"[,，\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(?:ep)?(\d+)(?:\s*[-–~]\s*(?:ep)?(\d+))?", part, re.I)
        if not m:
            raise ValueError(f"集段格式不对：{part}（例：1-10, 12）")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if b < a:
            raise ValueError(f"集段倒序：{part}")
        out.update(range(a, b + 1))
    return sorted(out)


def write_looks(ctx: ProjectContext) -> None:
    """人物卡的造型 A/B/C + 排期 → data/looks/{wardrobe,looks,schedule}.json（ns_schema.looks 格式，资产页可直接读）"""
    from ns_schema.looks import Look, LookBook, LookPatch, LookSchedule, Wardrobe, WardrobeItem
    items, looks, sched = [], [], LookSchedule()
    slot_of = {"outfit": "outfit", "shoes": "shoes", "makeup": "makeup", "hair": "hair", "nails": "nails",
               "accessory": "accessory"}
    for c in characters_list(ctx):
        cid = c["id"]
        for lk in c.get("looks", []):
            lid = f"{cid}-look-{lk['label'].lower()}"
            slots: dict[str, list[str]] = {}
            for field_, slot in slot_of.items():
                text = (lk.get(field_) or c.get({"outfit": "wardrobe"}.get(field_, field_)) or "").strip()
                if not text:
                    continue
                iid = f"{cid}-{slot}-{hashlib.sha1(text.encode()).hexdigest()[:6]}"
                if not any(i.id == iid for i in items):
                    items.append(WardrobeItem(id=iid, slot=slot, name=text[:24], description=text, character=cid,
                                              source="manual", needs_review=True))
                slots[slot] = [iid]
            looks.append(Look(id=lid, character=cid, name=lk.get("name") or f"造型{lk['label']}", items=slots,
                              label=lk["label"]))
        if c.get("looks"):
            sched.character_defaults[cid] = f"{cid}-look-{c['looks'][0]['label'].lower()}"
        for row in c.get("schedule", []):
            for ep in parse_episodes(row["episodes"]):
                sched.episodes.setdefault(str(ep), {})[cid] = LookPatch(look_id=f"{cid}-look-{row['look'].lower()}")
    ctx.looks_dir.mkdir(parents=True, exist_ok=True)
    write_json(ctx.looks_dir / "wardrobe.json", Wardrobe(items=items).model_dump())
    write_json(ctx.looks_dir / "looks.json", LookBook(looks=looks).model_dump())
    write_json(ctx.looks_dir / "schedule.json", sched.model_dump())


# ================================================================== LoRA 计划 / 成人开关 / 建项目

class SettingsForm(BaseModel):
    lora_plan: dict[str, bool] | None = None
    adult_content: bool | None = None


def update_settings(ctx: ProjectContext, form: SettingsForm) -> dict:
    s = ctx.settings()
    if form.lora_plan is not None:
        bad = set(form.lora_plan) - set(LORA_KINDS)
        if bad:
            raise ValueError(f"未知 LoRA 类别：{sorted(bad)}")
        s["lora_plan"] = {k: bool(form.lora_plan.get(k)) for k in LORA_KINDS}
    if form.adult_content is not None:
        s["adult_content"] = bool(form.adult_content)
    return ctx.save_settings(s)


def readiness(ctx: ProjectContext) -> dict:
    """建项目前的检查清单"""
    s = ctx.settings()
    val = read_json(ctx.import_dir / "validation.json", {})
    chars = characters_list(ctx)
    checks = [
        {"key": "script", "label": "剧本已导入且无致命错误", "ok": bool(val.get("ok")) and ctx.script_json.is_file()},
        {"key": "style", "label": "风格已确认（G1）", "ok": bool(s.get("gates", {}).get("G1"))},
        {"key": "characters", "label": "每个角色已上传参考图并确认为 AI 生成的虚构成年人",
         "ok": bool(chars) and all(c.get("confirmed") for c in chars)},
        {"key": "lora", "label": "LoRA 计划已填写", "ok": "lora_plan" in s and bool(s.get("lora_plan") is not None)},
    ]
    return {"checks": checks, "ok": all(c["ok"] for c in checks)}


def finalize(ctx: ProjectContext) -> dict:
    r = readiness(ctx)
    if not r["ok"]:
        raise ValueError("还有未完成的项：" + "、".join(c["label"] for c in r["checks"] if not c["ok"]))
    s = ctx.settings()
    form = StyleForm(**s["style"])
    ctx.visual_bible.write_text(render_visual_bible(ctx, form, characters_list(ctx), s["gates"]["G1"]), encoding="utf-8")
    if not ctx.adult_overrides.exists():
        write_json(ctx.adult_overrides, {"_comment": "强制判为成人的镜头（本剧）。值为原因。", "force_adult": {}})
    voices = ctx.config_dir / "voices.json"
    if not voices.exists():
        base = read_json(REPO / "config" / "voices.json", {})
        base["characters"] = {c["id"]: {"name": c["name"], "note": "待选音色（T38）"} for c in characters_list(ctx)}
        base["line_overrides"] = {}
        write_json(voices, base)
    write_face_reference(ctx)
    write_looks(ctx)
    s["status"] = "ready"
    s["created_ready_at"] = now()
    ctx.save_settings(s)
    from ns_api.project_ctx import set_status
    set_status(ctx.slug, "ready")
    return s
