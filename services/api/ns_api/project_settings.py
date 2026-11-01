"""
项目设置页（K-UI-030 恢复：旧「新建剧」向导约 30 项设置不再静默消失）。

旧向导（data/_archive/20261031/code/apps_web/src/projects/Wizard.tsx）的每一项现在落在哪，这里逐项登记：
  - edit     已转成配置：显示当前值，可改。PUT 只改那一个键（文本局部替换，不整文件重写格式），
             改前把原文件整份备份到 data/assets/settings_backups/，改后重新解析核对“只有这个键变了”。
  - readonly 落在不归这里改的地方（写作规则 knowledge/rules 非 ui 文件、本人确认记录、代码常量）：只显示 + “要改请在 X 改”。
  - merged   旧项已并入别处：灰显 + “已并入 X”（X 写具体位置），能读到的当前值照样显示。

接口：
  GET /api/project-settings                 分组 + 每项 {id, group, label, legacy, status, source, value, …}
  PUT /api/project-settings/{item_id}       {value, by:"owner", expect?}  → {item, prev, backup}
      by 由登录中间件（ns_api.auth）按会话改写：不是登录的项目方会变成 "unauthenticated" → 403；写请求自动记审计。
      expect（可选）= 打开页面时看到的旧值；文件已被别人改过就 409，不覆盖。

只写 config/ 下的 JSON / TOML（局部改一个键）；不碰 knowledge/rules、剧本内容；不删任何文件。
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]          # 测试里 monkeypatch 成临时目录
router = APIRouter(prefix="/api/project-settings", tags=["project-settings"])
_lock = threading.Lock()

VB = "config/visual_bible.toml"
RQ = "config/render_quality.json"
KREA = "krea2_film_texture_qwen21.safetensors"


def backups_dir() -> Path:
    return ROOT / "data" / "assets" / "settings_backups"


# ================================================================== 读：按路径取值

def _load(rel: str) -> Any:
    p = ROOT / rel
    if not p.is_file():
        raise FileNotFoundError(rel)
    text = p.read_text(encoding="utf-8-sig")
    if rel.endswith(".toml"):
        return tomllib.loads(text)
    return json.loads(text)


def _match(el: Any, sel: dict) -> bool:
    return isinstance(el, dict) and all(el.get(k) == v for k, v in sel.items())


def _get(obj: Any, path: list) -> Any:
    cur = obj
    for k in path:
        if isinstance(k, dict):
            if not isinstance(cur, list):
                raise KeyError(str(k))
            cur = next((x for x in cur if _match(x, k)), None)
            if cur is None:
                raise KeyError(json.dumps(k, ensure_ascii=False))
        elif isinstance(k, int):
            cur = cur[k]
        else:
            if not isinstance(cur, dict) or k not in cur:
                raise KeyError(k)
            cur = cur[k]
    return cur


def _set(obj: Any, path: list, value: Any) -> Any:
    """返回改过的深拷贝（核对用）"""
    out = copy.deepcopy(obj)
    cur = out
    for k in path[:-1]:
        cur = next(x for x in cur if _match(x, k)) if isinstance(k, dict) else cur[k]
    last = path[-1]
    if isinstance(last, dict):
        raise ValueError("最后一级必须是键名")
    cur[last] = value
    return out


def _path_str(path: list) -> str:
    s = ""
    for k in path:
        if isinstance(k, dict):
            s += "[" + ",".join(f"{a}={b}" for a, b in k.items()) + "]"
        elif isinstance(k, int):
            s += f"[{k}]"
        else:
            s += ("." if s else "") + k
    return s


# ================================================================== 写：JSON 局部替换

_dec = json.JSONDecoder()
_WS = " \t\r\n"


def _ws(t: str, i: int) -> int:
    while i < len(t) and t[i] in _WS:
        i += 1
    return i


def _json_span(t: str, i: int, path: list) -> tuple[int, int]:
    """t[i:] 是一个 JSON 值；沿 path 往下找，返回目标值在原文里的 [start, end)"""
    i = _ws(t, i)
    if not path:
        return i, _dec.raw_decode(t, i)[1]
    k, rest = path[0], path[1:]
    if t[i] == "{":
        if not isinstance(k, str):
            raise KeyError(f"{k} 不是对象键")
        i += 1
        while True:
            i = _ws(t, i)
            if t[i] == "}":
                raise KeyError(k)
            key, i = _dec.raw_decode(t, i)
            i = _ws(t, i)
            assert t[i] == ":"
            v0 = _ws(t, i + 1)
            if key == k:
                return _json_span(t, v0, rest)
            i = _ws(t, _dec.raw_decode(t, v0)[1])
            if t[i] == ",":
                i += 1
    if t[i] == "[":
        i += 1
        idx = 0
        while True:
            i = _ws(t, i)
            if t[i] == "]":
                raise KeyError(str(k))
            v, end = _dec.raw_decode(t, i)
            if (isinstance(k, int) and k == idx) or (isinstance(k, dict) and _match(v, k)):
                return _json_span(t, i, rest)
            i = _ws(t, end)
            if t[i] == ",":
                i += 1
            idx += 1
    raise KeyError(str(k))


def _json_edit(text: str, path: list, value: Any) -> str:
    s, e = _json_span(text, 0, path)
    lit = json.dumps(value, ensure_ascii=False)
    return text[:s] + lit + text[e:]


# ================================================================== 写：TOML 局部替换（单行 key = value）

def _tq(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_tq(x) for x in v) + "]"
    raise TypeError(type(v))


_HDR = re.compile(r"^\s*(\[\[?)\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")


def _toml_block(lines: list[str], path: list) -> tuple[int, int, str]:
    """path = [表名..., (选择器), 键]；返回 (块起始行, 块结束行, 键名)。
    支持 [a.b] 普通表与 [[arr]] + {"id": x} 选择器。"""
    key = path[-1]
    tbl = path[:-1]
    if tbl and isinstance(tbl[-1], dict):
        name, sel = ".".join(tbl[:-1]), tbl[-1]
        arr = True
    else:
        name, sel, arr = ".".join(tbl), None, False
    heads = [(i, m) for i, l in enumerate(lines) if (m := _HDR.match(l.rstrip("\r\n")))]
    for n, (i, m) in enumerate(heads):
        is_arr = m.group(1) == "[["
        if m.group(2) != name or is_arr != arr:
            continue
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        if sel is not None:
            try:
                block = tomllib.loads("".join(lines[i + 1:end]))
            except tomllib.TOMLDecodeError:
                continue
            if not _match(block, sel):
                continue
        return i, end, key
    if not name:
        end = heads[0][0] if heads else len(lines)
        return -1, end, key
    raise KeyError(_path_str(tbl))


def _value_end(rest: str) -> int:
    """rest = 等号后的原文（不含换行）；返回值字面量结束的位置（之后只能是空白或注释）"""
    cands = [m.start() for m in re.finditer("#", rest)] + [len(rest)]
    for p in cands:
        try:
            tomllib.loads("x = " + rest[:p])
        except tomllib.TOMLDecodeError:
            continue
        return len(rest[:p].rstrip())
    raise ValueError("这一行的值跨多行，不能在这里改")


def _toml_edit(text: str, path: list, value: Any) -> str:
    lines = text.splitlines(keepends=True)
    start, end, key = _toml_block(lines, path)
    kre = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(.*?)(\r?\n)?$")
    for i in range(start + 1, end):
        m = kre.match(lines[i])
        if not m:
            continue
        rest = m.group(2)
        ve = _value_end(rest)
        lines[i] = m.group(1) + _tq(value) + rest[ve:] + (m.group(3) or "")
        return "".join(lines)
    raise KeyError(f"{_path_str(path)} 不在文件里")


# ================================================================== 设置项登记

def _it(id: str, group: str, label: str, legacy: str, status: str, *, file: str | None = None, path: list | None = None,
        type: str = "text", hint: str = "", merged_into: str = "", edit_where: str = "", options: list | None = None,
        vmin: float | None = None, vmax: float | None = None, reader=None, also: list | None = None) -> dict:
    return {"id": id, "group": group, "label": label, "legacy": legacy, "status": status, "file": file, "path": path,
            "type": type, "hint": hint, "merged_into": merged_into, "edit_where": edit_where, "options": options,
            "min": vmin, "max": vmax, "_reader": reader, "also": also or []}


def _first_line(rel: str, needle: str) -> Any:
    p = ROOT / rel
    if not p.is_file():
        raise FileNotFoundError(rel)
    for n, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if needle in l:
            return f"第 {n} 行：{l.strip()}"
    raise KeyError(needle)


def _rule(rel: str, rid: str) -> Any:
    """knowledge/rules/*.yaml 里一条规则的标题 + then（只读）"""
    import yaml
    p = ROOT / rel
    if not p.is_file():
        raise FileNotFoundError(rel)
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rules = d.get("rules") if isinstance(d, dict) else d
    for r in rules or []:
        if isinstance(r, dict) and r.get("id") == rid:
            return f"{rid}：{r.get('title', '')}\n{r.get('then', '')}".strip()
    raise KeyError(rid)


def _voices() -> Any:
    """每个角色一条：名字 → 音色编号（config/voices.json characters）"""
    chars = _load("config/voices.json").get("characters") or {}
    return {(v.get("name") or k): f"{v.get('voice', '')}（编号 {v.get('sid', '')}，语速 {v.get('speed', 1.0)}）"
            for k, v in chars.items() if isinstance(v, dict) and not k.startswith("_")}


def _preset_ids() -> list[list[str]]:
    try:
        d = _load(RQ)
    except (OSError, ValueError):
        return []
    return [[p["id"], p.get("label") or p["id"]] for p in (d.get("image_presets") or []) + (d.get("user_presets") or [])
            if isinstance(p, dict) and p.get("id")]


def _default_preset() -> str:
    try:
        return str(_load(RQ).get("default_preset") or "leica_sstar")
    except (OSError, ValueError):
        return "leica_sstar"


G_SCRIPT, G_LOOK, G_RULES, G_SOUND, G_PEOPLE, G_LORA = "剧名与剧本", "画面风格", "材质与镜头规则", "声音", "人物", "LoRA 与成人内容"
GROUPS = [G_SCRIPT, G_LOOK, G_RULES, G_SOUND, G_PEOPLE, G_LORA]


def items() -> list[dict]:
    dp = _default_preset()
    out = [
        # ---------------------------------------------------------- ① 剧名 / ② 剧本三件套
        _it("name", G_SCRIPT, "剧名", "① 剧名", "readonly", file=VB, path=["project", "name"],
            edit_where="剧名写在项目登记里（services/api/ns_api/project_ctx.py 的 DEFAULT_NAME），不在这里改"),
        _it("slug", G_SCRIPT, "项目代号", "① 项目代号", "readonly", reader=lambda: "weita",
            edit_where="现有项目的代号固定，不能改（改了会断开已有的出图 / 视频目录）"),
        _it("mainline", G_SCRIPT, "主线剧本（剧本和镜头）", "② 剧本三件套 · 剧本和镜头", "edit", file="config/script_mainline.json",
            path=["mainline"], type="paths", hint="剧本导入页把这里的文件当“主线”候选；一行一个仓库内相对路径，文件必须存在"),
        _it("image_doc", G_SCRIPT, "image 提示词文档", "② 剧本三件套 · image 提示词", "merged", file=VB, path=["project", "image_doc"],
            merged_into="剧本里每一镜的 img / H3提示词 字段（写作格式规则 config/script_chat_rules.md 第 2 节），不再单独上传一份 image 文档"),
        _it("corrector_doc", G_SCRIPT, "纠正器文档", "② 剧本三件套 · 纠正器", "merged", file=VB, path=["project", "corrector_doc"],
            merged_into="本页「材质与镜头规则」里的镜头类型规则（visual_bible.toml [[shot_rules]]），以及出图前的提示词保护（render_quality.json prompt_guard）"),

        # ---------------------------------------------------------- ③ 风格 SOP · 画面
        _it("lens", G_LOOK, "镜头感（徕卡句）", "③ 风格 · 镜头感", "edit", file=VB, path=["look", "lens_template"], type="longtext",
            hint="出图时追加的镜头句；{mm} {f} 会换成风格后缀里的焦段 / 光圈。旧版的 lens 字段已不再被读取，现在读的是这一条"),
        _it("palette", G_LOOK, "调色 / 色调", "③ 风格 · 调色 / 色调", "merged", reader=lambda: _get(_load(VB), ["look", "fallback_suffix"]),
            merged_into="本页「统一风格后缀」和「默认出图预设的风格后缀」——色调描述现在写在后缀里，不再单独一栏"),
        _it("use_script_suffix", G_LOOK, "剧本里有统一后缀时优先用剧本的", "③ 风格 · 剧本后缀优先", "merged", file=VB,
            path=["look", "use_script_suffix"], type="bool",
            merged_into="出图编译规则（固定：剧本写了“每条img统一后缀”就用剧本的，没写才用下面的统一风格后缀；services/agent/ns_agent/compiler.py）"),
        _it("fallback_suffix", G_LOOK, "统一风格后缀（剧本没写时）", "③ 风格 · 统一风格后缀", "edit", file=VB,
            path=["look", "fallback_suffix"], type="longtext"),
        _it("preset_suffix", G_LOOK, "默认出图预设的风格后缀", "③ 风格 · 统一风格后缀（出图预设里的那一份）", "edit", file=RQ,
            path=["image_presets", {"id": dp}, "params", "style_suffix"], type="longtext",
            hint=f"画布出图默认用预设「{dp}」，它自带这一句风格后缀"),
        _it("default_preset", G_LOOK, "默认出图预设", "③ 风格 · G1 风格定稿", "edit", file=RQ, path=["default_preset"], type="select",
            options=_preset_ids(), hint="旧版的“风格定稿确认”现在就是选定默认出图预设；画布出图不另选时用它"),
        _it("style_negative", G_LOOK, "风格负面词", "③ 风格 · 风格负面词", "edit", file=VB, path=["look", "style_negative"],
            hint="注意：快速出图（cfg 1）下负面词不生效，只在定稿档起作用"),
        _it("color_reference", G_LOOK, "色调参考图", "③ 风格 · 色调参考图", "edit", file=RQ, path=["tiers", "final", "grade", "reference"],
            type="path", hint="定稿出图后向这张图做色调迁移；填仓库内相对路径，文件必须存在",
            also=[{"label": "视觉圣经里的旧记录", "file": VB, "path": ["look", "color_reference"]}]),
        _it("color_match_strength", G_LOOK, "色调匹配力度", "③ 风格 · 色调匹配力度", "edit", file=RQ,
            path=["tiers", "final", "grade", "strength"], type="number", vmin=0, vmax=1,
            hint="0–1；夜景 / 暗场会自动减弱"),
        _it("realism_texture", G_LOOK, "写实质感强度（默认出图预设）", "③ 风格 · 写实（只作质感）", "edit", file=RQ,
            path=["image_presets", {"id": dp}, "params", "loras", {"name": KREA}, "strength"], type="number", vmin=0, vmax=1,
            hint="胶片质感 LoRA 的强度，只加质感、不改长相；推荐 0.3–0.5"),
        _it("realism_texture_final", G_LOOK, "写实质感强度（定稿档）", "③ 风格 · 写实（只作质感）", "edit", file=RQ,
            path=["tiers", "final", "realism_loras", 0, 1], type="number", vmin=0, vmax=1),

        # ---------------------------------------------------------- 非成人镜头 / 规则
        _it("safe_term", G_RULES, "非成人镜头追加", "③ 风格 · 非成人镜头追加", "edit", file=VB, path=["shot_rules_safe", "term"]),
        _it("safe_negative", G_RULES, "非成人镜头负面", "③ 风格 · 非成人镜头负面", "edit", file=VB, path=["shot_rules_safe", "negative"]),

        # ---------------------------------------------------------- 声音
        _it("soundscape_default", G_SOUND, "默认环境声", "③ 声音 · 默认环境声", "merged",
            reader=lambda: _first_line("config/script_chat_rules.md", "必备要素"),
            merged_into="剧本每一镜必写的【H3 audio】声音（写作格式规则 config/script_chat_rules.md），没有全剧兜底环境声了"),
        _it("voice_rule", G_SOUND, "主角声线", "③ 声音 · 主角固定声线", "merged", reader=_voices,
            merged_into="「声音 → 角色音色 · 旁白」页：每个角色一条固定音色（config/voices.json），在那里试听、换音色"),
        _it("single_voice", G_SOUND, "亲密 / 多人镜头只让一人发声", "③ 声音 · 只让一人发声", "merged",
            reader=lambda: _first_line("services/api/ns_api/script_chat.py", '"H3-D7": ('),
            merged_into="剧本自动校验 H3-D7（每镜只有一个说话人，亲密镜只让林晚发声；校验不过不能导入）"),
        _it("bgm_style", G_SOUND, "全剧配乐风格（BGM）", "③ 声音 · 全剧配乐风格", "merged",
            reader=lambda: _first_line("config/script_chat_rules.md", "**配乐**："),
            merged_into="每集剧本开头的「配乐」字段（中文说明 +【BGM】英文提示），整集一条 BGM；不再有全剧统一一句"),
        _it("h3_music", G_SOUND, "视频自带的配乐怎么处理", "③ 声音 · 全剧配乐风格（成片时）", "edit", file=RQ,
            path=["post", "h3_music", "default"], type="select",
            options=[["duck_under_bgm", "压到整集配乐下面（只留对白和环境声）"], ["keep", "保留视频原有配乐"]]),
        _it("dialogue_source", G_SOUND, "成片对白用哪种声音", "③ 声音 · 主角声线（成片时）", "edit", file=RQ,
            path=["post", "dialogue_source", "default"], type="select",
            options=[["h3", "视频原声（和嘴型同步）"], ["tts", "配音"]]),

        # ---------------------------------------------------------- ④ 人物
        _it("references", G_PEOPLE, "人物参考图", "④ 人物 · 参考图", "merged",
            merged_into="「资产中心 → 人物」：每个人一页，身份脸 / 参考照片在那里上传、选定（data/looks/face_overrides.json）"),
        _it("adult_ai_confirm", G_PEOPLE, "此角色为 AI 生成的虚构成年人（确认记录）", "④ 人物 · AI 生成虚构成年人确认", "readonly",
            file="config/face_reference.json", path=["approved_for_adult"], type="bool",
            also=[{"label": "确认人", "file": "config/face_reference.json", "path": ["approved_by"]},
                  {"label": "确认日期", "file": "config/face_reference.json", "path": ["approved_at"]},
                  {"label": "参考图", "file": "config/face_reference.json", "path": ["reference"]}],
            edit_where="这是你本人的确认记录，只显示不在这里改；记录在 config/face_reference.json"),
        _it("realism_per_char", G_PEOPLE, "每个人的写实强度", "④ 人物 · 写实强度（轻 / 中 / 强）", "merged",
            merged_into="本页「画面风格 → 写实质感强度」：全剧统一一个强度，不再按人物分档"),
        _it("hair", G_PEOPLE, "发型", "④ 人物 · 发型", "merged", file=VB, path=["characters", "lin_wan", "hair_color"],
            merged_into="「资产中心 → 人物 → 形象 A/B/C」的发型部件；下面是视觉圣经里的旧记录（只在状态时间线里显示）"),
        _it("makeup", G_PEOPLE, "妆容", "④ 人物 · 妆容", "merged", file=VB, path=["characters", "lin_wan", "makeup_palette"],
            merged_into="「资产中心 → 人物 → 形象 A/B/C」的妆容部件"),
        _it("nails", G_PEOPLE, "美甲", "④ 人物 · 美甲", "merged", file=VB, path=["characters", "lin_wan", "nails"],
            merged_into="「资产中心 → 人物 → 形象 A/B/C」的美甲部件；脚趾甲的追加句在本页「材质与镜头规则」"),
        _it("wardrobe", G_PEOPLE, "日常穿搭规则", "④ 人物 · 日常穿搭规则", "merged", file=VB, path=["characters", "lin_wan", "wardrobe_rule"],
            merged_into="「资产中心 → 人物 → 形象 A/B/C」的服装部件和衣橱单品"),
        _it("shoes", G_PEOPLE, "默认鞋", "④ 人物 · 鞋（默认）", "merged", file=VB, path=["characters", "lin_wan", "heels_default"],
            merged_into="「资产中心 → 人物 → 形象 A/B/C」的鞋部件"),
        _it("looks", G_PEOPLE, "造型 A / B / C", "④ 人物 · 造型 A/B/C", "merged",
            merged_into="「资产中心 → 人物 → 形象 A/B/C」（可新建形象、挂单品、选设定图）"),
        _it("schedule", G_PEOPLE, "造型排期（哪几集用哪套）", "④ 人物 · 造型排期", "merged",
            merged_into="「资产中心 → 人物」的按集排期，以及每集剧本开头的「造型｜角色名」行（data/looks/schedule.json）"),

        # ---------------------------------------------------------- ⑤ LoRA / ⑥ 成人 / ⑦ 创建
        _it("lora_plan", G_LORA, "LoRA 计划", "⑤ LoRA 计划", "merged",
            reader=lambda: _get(_load("config/gen_contract.json"), ["lora_allow"]),
            merged_into="出图允许使用的 LoRA 清单（config/gen_contract.json lora_allow）和导入时自动补的人物触发词（config/auto_lora_triggers.json）；"
                        "训练排期不再在设置里勾选"),
        _it("adult_judge", G_LORA, "成人镜头怎么判定", "⑥ 成人内容（判定方式）", "edit", file="config/adult_overrides.json",
            path=["per_shot"], type="select", options=[[False, "按集：集标题带 🔴 的整集都算"], [True, "逐镜判定（亲密声 / 关键词 / 强制名单）"]]),
        _it("adult_filter", G_LORA, "非成人镜头的裸露检查", "⑥ 成人内容（开关）", "readonly", file=VB,
            path=["generation", "nudity_qc_non_adult"],
            edit_where="2026-10-30 起取消成人过滤器：只记录不否决（你本人的决定）；要改请先在决定记录里改，再改 config/visual_bible.toml [generation]"),
        _it("adult_local", G_LORA, "成人镜头只在本地生成", "⑥ 成人内容（生成位置）", "readonly",
            reader=lambda: _rule("knowledge/rules/research.yaml", "K-OPS-R07"),
            edit_where="这是写作 / 生产规则（knowledge/rules/research.yaml K-OPS-R07、writer_series10.yaml K-WRT-205），不在设置页改"),
        _it("readiness", G_LORA, "创建前检查清单", "⑦ 创建", "merged",
            merged_into="顶栏的本集制作步骤（剧本 → 资产 → 出图 → 视频 → 成片），每一步的完成情况在那里看"),
    ]
    # 材质 / 镜头类型规则：每条一项，只改 term（追加的措辞）
    try:
        vb = _load(VB)
    except (OSError, ValueError):
        vb = {}
    for arr, label, legacy in (("materials", "材质规则", "③ 风格 · 材质规则"), ("shot_rules", "镜头类型规则", "③ 风格 · 镜头类型规则（纠正器）")):
        for r in vb.get(arr) or []:
            if not isinstance(r, dict) or not r.get("id"):
                continue
            out.append(_it(f"{arr}:{r['id']}", G_RULES, f"{label} · {r['id']}", legacy, "edit", file=VB,
                           path=[arr, {"id": r["id"]}, "term"], type="longtext",
                           hint="镜头原文出现关键词就追加这句（原文已有就跳过）；关键词：" + "、".join(map(str, r.get("match") or []))))
    return out


def _find(item_id: str) -> dict:
    it = next((x for x in items() if x["id"] == item_id), None)
    if it is None:
        raise HTTPException(404, f"没有这个设置项：{item_id}")
    return it


def _read_item(it: dict) -> dict:
    out = {k: v for k, v in it.items() if not k.startswith("_") and k != "also"}
    out["source"] = (f"{it['file']} · {_path_str(it['path'])}" if it["file"] else None)
    try:
        if it["_reader"]:
            out["value"] = it["_reader"]()
        elif it["file"]:
            out["value"] = _get(_load(it["file"]), it["path"])
        else:
            out["value"] = None
        out["error"] = None
    except FileNotFoundError as e:
        out["value"], out["error"] = None, f"文件不在：{e}"
    except (KeyError, IndexError, TypeError) as e:
        out["value"], out["error"] = None, f"文件里没有这一项：{e}"
    except ValueError as e:
        out["value"], out["error"] = None, f"文件读不了：{e}"
    out["also"] = []
    for a in it["also"]:
        try:
            v = _get(_load(a["file"]), a["path"])
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            v = None
        out["also"].append({"label": a["label"], "source": f"{a['file']} · {_path_str(a['path'])}", "value": v})
    if out["status"] == "edit" and out["error"]:
        out["status"] = "readonly"
        out["edit_where"] = f"现在改不了（{out['error']}）"
    return out


@router.get("")
def list_settings():
    return {"groups": GROUPS, "items": [_read_item(it) for it in items()], "backups": "data/assets/settings_backups/"}


class PutBody(BaseModel):
    value: Any = None
    by: str = ""
    key: str | None = None          # 只为审计记录对象（中间件取 body.key）
    expect: Any = None
    has_expect: bool = False


def _coerce(it: dict, v: Any) -> Any:
    t = it["type"]
    if t == "number":
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise HTTPException(422, "要填数字")
        if (it["min"] is not None and x < it["min"]) or (it["max"] is not None and x > it["max"]):
            raise HTTPException(422, f"要在 {it['min']}–{it['max']} 之间")
        return round(x, 4)
    if t == "bool":
        if not isinstance(v, bool):
            raise HTTPException(422, "只能是 是 / 否")
        return v
    if t == "select":
        opts = [o[0] for o in it["options"] or []]
        if v not in opts:
            raise HTTPException(422, f"只能选：{opts}")
        return v
    if t == "paths":
        if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
            raise HTTPException(422, "至少一行路径")
        v = [x.strip() for x in v]
        for x in v:
            _check_path(x)
        return v
    if not isinstance(v, str):
        raise HTTPException(422, "要填文字")
    if t == "path":
        v = v.strip()
        _check_path(v)
    return v


def _check_path(rel: str) -> None:
    p = (ROOT / rel).resolve()
    if not p.is_relative_to(ROOT.resolve()):
        raise HTTPException(422, f"路径越界：{rel}")
    if not p.is_file():
        raise HTTPException(422, f"文件不存在：{rel}")


def _backup(src: Path) -> Path:
    d = backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    rel = src.relative_to(ROOT).as_posix().replace("/", "__")
    dst = d / f"{time.strftime('%Y%m%d-%H%M%S')}_{rel}"
    n = 1
    while dst.exists():
        dst = d / f"{time.strftime('%Y%m%d-%H%M%S')}_{n}_{rel}"
        n += 1
    shutil.copy2(src, dst)
    return dst


@router.put("/{item_id:path}")
def put_setting(item_id: str, body: PutBody):
    if body.by != "owner":
        raise HTTPException(403, "只有登录的项目方能改设置")
    it = _find(item_id)
    if it["status"] != "edit" or not it["file"]:
        raise HTTPException(409, "这一项不在这里改：" + (it["edit_where"] or it["merged_into"] or "只读"))
    new = _coerce(it, body.value)
    rel, path = it["file"], it["path"]
    p = ROOT / rel
    with _lock:
        raw = p.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        old_obj = tomllib.loads(text) if rel.endswith(".toml") else json.loads(text)
        try:
            prev = _get(old_obj, path)
        except (KeyError, IndexError, TypeError) as e:
            raise HTTPException(409, f"文件里没有这一项：{e}")
        if body.has_expect and body.expect != prev:
            raise HTTPException(409, "这一项在你打开页面之后被改过了，刷新看最新值再改")
        if prev == new:
            return {"item": _read_item(it), "prev": prev, "backup": None, "unchanged": True}
        try:
            new_text = _toml_edit(text, path, new) if rel.endswith(".toml") else _json_edit(text, path, new)
            new_obj = tomllib.loads(new_text) if rel.endswith(".toml") else json.loads(new_text)
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(409, f"没能只改这一项，文件没动：{e}")
        if new_obj != _set(old_obj, path, new):
            raise HTTPException(409, "改完核对发现别的内容也变了，已放弃，文件没动")
        bk = _backup(p)
        tmp = p.with_name(p.name + ".settings_tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new_text.encode("utf-8"))
        tmp.replace(p)
        log = backups_dir() / "changes.jsonl"
        with log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "item": item_id, "file": rel,
                                "path": _path_str(path), "prev": prev, "value": new,
                                "backup": bk.relative_to(ROOT).as_posix()}, ensure_ascii=False) + "\n")
    return {"item": _read_item(it), "prev": prev, "backup": bk.relative_to(ROOT).as_posix()}
