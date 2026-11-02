"""全剧总览（UIRSI 2026-11-01，项目方：“之前更容易看到整部剧里每一个 episode、每一个镜头之间的关系……把它拉回来，也思考一下怎样做逻辑更好”）。

  GET /api/season   全季结构（只读剧本 + 版本表）：每集标题、场景；每镜 景别 · 场景 · 出场人物（在画 / 局部 / 画外）·
                    衔接（换场 / 同场换机位 / 接力 + 承接什么）· 换造型点 · 时长；没有当前首帧时给最新一张合格候选的图址（缩略用）。
状态（首帧 / 尾帧 / 视频 / 通过）由前端从集摘要（/api/episodes/summary，store 轮询）实时合上，不在这里重复算。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["season"])
SIZE_RE = re.compile(r"(大远景|远景|大全景|全景|中全景|中景|中近景|近景|大特写|特写)")
_cache: dict = {"key": None, "val": None}
# 卡片一句话内容去掉开头的机位短语（“侧面机位”“过肩”“固定机位”…）
CAM_RE = re.compile(r".{0,6}(机位|视角|角度)|过肩|侧面|正面|背面|固定|手持|跟拍|推镜|拉镜|摇镜|static shot.*|over.?the.?shoulder.*")


def _script() -> tuple[dict, float]:
    p = REPO / "data" / "import" / "script_v2.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")), p.stat().st_mtime
    except (OSError, ValueError):  # arch-ok: 导入稿不存在 = 还没导入剧本，空总览是真实状态（前端写“还没有剧本”）
        return {}, 0.0


def _cands(ep: int) -> dict:
    try:
        from ns_api import takes_ui  # noqa: PLC0415
        return takes_ui.candidates(ep).get("shots") or {}
    except Exception:  # noqa: BLE001
        return {}


def _img_line(t: str) -> str:
    """剧本 img 去掉开头的 LoRA 触发词 / 景别 / 机位短语（“lnwan01，特写，平视，”），留镜头内容本身；前端只显示前 20 字、悬停看全文"""
    parts = [x for x in re.split(r"[，,]", t) if x.strip()]
    while parts and (re.fullmatch(r"[A-Za-z0-9_\- ]+", parts[0].strip()) or SIZE_RE.fullmatch(parts[0].strip())
                     or parts[0].strip() in ("平视", "俯视", "仰视", "侧拍", "背拍", "正拍", "略俯", "略仰")
                     or CAM_RE.fullmatch(parts[0].strip())):
        parts.pop(0)
    return "，".join(x.strip() for x in parts)[:200]


LENS_RE = re.compile(r"(\d{2,3})\s*mm[^，,。]*?(f/?\s*\d+(?:\.\d+)?)?")


def lens_of_text(txt: str) -> str | None:
    """从提示词里解析镜头：“徕卡M 50mm f/2镜头”→“50mm f/2”；“85mm人像镜头f/1.2”→“85mm f/1.2”"""
    mm = LENS_RE.search(txt or "")
    if not mm:
        return None
    fa = re.search(r"f/\s*\d+(?:\.\d+)?", txt[mm.end(1): mm.end(1) + 16])
    return f"{mm.group(1)}mm{(' ' + fa.group(0).replace(' ', '')) if fa else ''}"


def _norm_lens(v) -> str | None:
    if not v:
        return None
    return lens_of_text(str(v)) or str(v)[:40]


def _style_suffix_lens() -> str | None:
    """还没出过图的镜：出图链统一加的 style_suffix 里的镜头（config/render_quality.json，现行“徕卡M 50mm f/2”）"""
    try:
        txt = (REPO / "config" / "render_quality.json").read_text(encoding="utf-8")
    except OSError:  # arch-ok: 配置读不到就只用计划值
        return None
    m = re.search(r'"style_suffix"\s*:\s*"([^"]*)"', txt)
    return lens_of_text(m.group(1)) if m else None


def lens_info(sid: str) -> dict:
    """一镜的镜头（总调度 r45：永远不显示“未标”）：
    实拍 = 本版 take 实际编译提示词（含 style_suffix）里解析出的镜头；没出过图 = 出图链 style_suffix 的镜头；
    计划 = takes.lens / visual_spec.lens / 作业提示词镜头句。显示：一致只写一个；不一致写“实拍 50mm f/2 · 计划 85mm f/1.2”。"""
    m = re.fullmatch(r"ep(\d+)-S(\d+)", sid)
    d = REPO / "data" / "renders" / f"ep{int(m.group(1)):02d}" / f"S{int(m.group(2))}" if m else None
    actual = plan = None
    tk = {}
    if d:
        try:
            tk = json.loads((d / "takes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):  # arch-ok: 这镜还没出过图，实拍按 style_suffix
            tk = {}
    act = (tk.get("active") or {}).get("image")
    ts = [t for t in tk.get("takes") or [] if t.get("stage") == "image"]
    t = next((x for x in ts if x.get("n") == act), ts[-1] if ts else None) or {}
    actual = lens_of_text(t.get("prompt") or "") or lens_of_text(str((t.get("params") or {}).get("prompt") or ""))
    plan = _norm_lens(t.get("lens") or (t.get("params") or {}).get("lens"))
    if not plan and d:
        try:
            cp = json.loads((d / "compiled.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):  # arch-ok: 没有编译稿就没有计划值
            cp = {}
        vs = cp.get("visual_spec") if isinstance(cp.get("visual_spec"), dict) else {}
        plan = _norm_lens(vs.get("lens")) or lens_of_text(cp.get("image_prompt") or "")
    source = "take" if actual else None
    if not actual:
        actual = _style_suffix_lens()
        source = "style_suffix" if actual else None
    if actual and plan and actual != plan:
        text = f"实拍 {actual} · 计划 {plan}"
    else:
        text = actual or plan or "镜头未标"
    return {"text": text, "actual": actual, "plan": plan, "actual_source": source}


def _furl(f: str | None) -> str | None:
    """takes.json 里的 file（相对 data/）→ /files 图址；文件不在笔记本上（服务器出的还没同步）→ None"""
    if not f:
        return None
    p = REPO / "data" / f
    try:
        v = int(p.stat().st_mtime)
    except OSError:  # arch-ok: 文件还没同步到笔记本 = 没有可播的视频，前端写“视频未出”
        return None
    return f"/files/{f}?v={v}"


def shot_extra(sid: str) -> dict:
    """r46（项目方 11:3x：“包裹镜头细节也上去……预览视频也需要”）：总览每帧下面的镜头细节 + 悬停预览视频。
    camera_move / lighting_sources 取 compiled.json visual_spec（接口真值）；lighting_name 现在没有字段 → None（前端用 mock 并标“示意”）；
    video = 当前版本视频；没有当前版本时 video_old = 最新一版（前端标“旧版”）。文件不在笔记本上的不给。"""
    m = re.fullmatch(r"ep(\d+)-S(\d+)", sid)
    out = {"camera_move": None, "lighting_sources": [], "lighting_name": None, "video": None, "video_old": None}
    if not m:
        return out
    d = REPO / "data" / "renders" / f"ep{int(m.group(1)):02d}" / f"S{int(m.group(2))}"
    try:
        vs = (json.loads((d / "compiled.json").read_text(encoding="utf-8")).get("visual_spec") or {})
    except (OSError, ValueError):  # arch-ok: 没有编译稿 = 运镜 / 灯光为空，前端写“—”
        vs = {}
    if isinstance(vs, dict):
        out["camera_move"] = vs.get("camera_move") or None
        lt = vs.get("lighting") if isinstance(vs.get("lighting"), dict) else {}
        out["lighting_sources"] = [str(x) for x in (lt.get("sources") or [])][:3]
        out["lighting_name"] = lt.get("name") or lt.get("scheme") or None
    try:
        tk = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 没出过 = 没视频
        return out
    vts = [t for t in tk.get("takes") or [] if t.get("stage") == "video"]
    act = (tk.get("active") or {}).get("video")
    cur = next((t for t in vts if t.get("n") == act), None)
    out["video"] = _furl((cur or {}).get("file")) if cur else None
    if not out["video"]:
        for t in reversed(vts):
            u = _furl(t.get("file"))
            if u:
                out["video_old"] = u
                break
    return out


def _faces(sc: dict) -> dict[str, str]:
    """出场人物名字 → 身份脸图址（asset_refs.face_of，与出图用的同一张；资产中心改了身份脸这里跟着变）"""
    out: dict[str, str] = {}
    try:
        from ns_agent import asset_refs as R  # noqa: PLC0415
        from ns_api.character_hub import current_project  # noqa: PLC0415
        proj = current_project()
        for c in (sc.get("globals") or {}).get("character_registry") or []:
            f = R.face_of(proj, c.get("char_id") or "") if c.get("char_id") else None
            if f and c.get("name"):
                out[c["name"]] = "/files/" + (f[len("data/"):] if f.startswith("data/") else f)
    except Exception:  # noqa: BLE001 — 读不到身份脸就只显示名字
        pass
    return out


def _structure(sc: dict) -> list[dict]:
    lib = {x.get("scene_id"): x.get("name") for x in (sc.get("globals") or {}).get("scene_library") or []}
    out = []
    for e in sc.get("episodes") or []:
        n = int(e.get("number") or 0)
        # 换造型点：剧本造型表里 from_shot = 这一镜起换装
        switch: dict[int, list[str]] = {}
        for lk in e.get("looks") or []:
            if lk.get("from_shot"):
                switch.setdefault(int(lk["from_shot"]), []).append(lk.get("character") or "")
        shots = []
        for s in e.get("shots") or []:
            i = int(s.get("index") or 0)
            m = SIZE_RE.search(s.get("img_prompt") or "")
            cast = []
            for c in s.get("cast") or []:
                if isinstance(c, dict):
                    cast.append({"name": c.get("name") or "", "presence": c.get("presence") or ""})
            shots.append({"id": f"ep{n:02d}-S{i}", "index": i, "size": m.group(1) if m else None,
                          "scene_id": s.get("scene_id"), "scene": lib.get(s.get("scene_id")) or s.get("scene_id"),
                          "link": s.get("link") or None, "carry": None if (s.get("link_carry") in (None, "", "无")) else s.get("link_carry"),
                          "cast": cast, "switch": switch.get(i, []),
                          # DATAALIGN（K-UI-D01）：与 /api/episodes 的 duration.seconds 同一规则（剧本没写 = 10 秒兜底，标 default），两页总秒数一致
                          "seconds": s.get("duration") if s.get("duration") is not None else 10,
                          "seconds_source": s.get("duration_source") or ("script" if s.get("duration") is not None else "default"),
                          "adult": bool(s.get("adult")),
                          # r43（项目方 02:4x：“缺乏很多细节，比如人物什么的”）：卡片第 3 行一句话镜头内容 = 剧本 img（去掉开头触发词）
                          "img": _img_line(s.get("img_prompt") or "")})
        out.append({"number": n, "title": e.get("title"), "scenes": [lib.get(x) or x for x in e.get("scene_ids") or []],
                    "shots": shots})
    return out


@router.get("/api/season")
def season():
    sc, mt = _script()
    if _cache["key"] != mt:
        _cache.update(key=mt, val=_structure(sc))
    eps = json.loads(json.dumps(_cache["val"]))
    for e in eps:
        c = _cands(e["number"])
        for s in e["shots"]:
            st = (c.get(s["id"]) or {}).get("image") or {}
            ok = [t for t in st.get("takes") or [] if t.get("ok") is not False and not t.get("bad")]
            s["cand_url"] = ok[-1]["url"] if ok and st.get("active") is None else None
            s["cand_n"] = len(ok) if st.get("active") is None else 0
            # UIRSI r40：旧剧本版本的图（剧本更新前出的）不作候选；有它们而没有新图时，格子写“未出（剧本已更新）”
            s["old_script_n"] = sum(1 for t in st.get("takes") or [] if t.get("script") == "old")
            s["status"] = (c.get(s["id"]) or {}).get("status") or {"main": None, "tags": []}
            # r45 胶卷片边下边码：镜头参数 takes.lens → compiled visual_spec.lens → 作业提示词里的镜头句（DIRECTOR 在给 takes 加 lens）
            li = lens_info(s["id"])
            s["lens"], s["lens_actual"], s["lens_plan"] = li["text"], li["actual"], li["plan"]
            s.update(shot_extra(s["id"]))
            # 当前版本本身是旧剧本出的（全量重做没撤掉的尾帧等）：前端不显示这张、按“未出（剧本已更新）”处理
            for stg, key in (("image", "first_old"), ("last", "last_old")):
                x = (c.get(s["id"]) or {}).get(stg) or {}
                a = x.get("active")
                s[key] = (a is not None and any(t.get("n") == a and t.get("script") == "old" for t in x.get("takes") or []))                     or x.get("active_quarantined") is not None   # r41：当前版本已隔离
        # UIRSI r40：板块层面（集 + 各阶段）已确认 / 进行中 / 过期 / 未开始，口径同镜头格标签
        try:
            from ns_api import shot_status  # noqa: PLC0415
            e["blocks"] = shot_status.episode_blocks(e["number"], e["shots"])
        except Exception:  # noqa: BLE001
            e["blocks"] = None
    return {"episodes": eps, "faces": _faces(sc)}


@router.get("/api/season/sheets")
def season_sheets(pairs: str = ""):
    """UIRSI r44（总调度：抽屉里林晚“本镜设定图”显示“无设定图”，可造型 A 明明有 sleevefix 那张）：
    详情抽屉“出场人物”的本镜造型设定图按 asset_refs.sheet_of 取（继承链：子季选定表优先，没有回落父季），与出图用的同一张。
    pairs = "lin_wan:A,gu_chen:A" → {"lin_wan:A": "/files/…png" | None}"""
    out: dict[str, str | None] = {}
    try:
        from ns_agent import asset_refs as R  # noqa: PLC0415
        from ns_api.character_hub import current_project  # noqa: PLC0415
        proj = current_project()
    except Exception:  # noqa: BLE001
        return {"sheets": out}
    for pr in [x.strip() for x in pairs.split(",") if ":" in x][:40]:
        cid, look = pr.split(":", 1)
        try:
            f = R.sheet_of(proj, cid, look)
        except Exception:  # noqa: BLE001
            f = None
        out[pr] = ("/files/" + (f[len("data/"):] if f.startswith("data/") else f)) if f else None
    return {"sheets": out}


@router.get("/api/ui/version")
def ui_version():
    """UIRSI r45（L-103：“页面停在旧状态”不能靠项目方自己按刷新）：前端页面过期检测用。
    src_at = apps/web/src（+ index.html）最新改动时间；dist_at = :8800 挂的 apps/web/dist/index.html 打包时间（秒级时间戳）。
    前端（v3/StaleBanner.tsx）定时比对：开发版（:5173）src 比本页最后一次加载 / 热更新新、且热更新没跟上 → 顶部提示“已更新，点此刷新”；
    打包版（:8800）dist 换了新的 → 同样提示；空闲 2 分钟自动刷新。"""
    web = REPO / "apps" / "web"
    src = 0.0
    for p in (web / "src").rglob("*"):
        if p.suffix in (".ts", ".tsx", ".css"):
            try:
                src = max(src, p.stat().st_mtime)
            except OSError:  # arch-ok: 单个文件读不到不影响整体版本号
                pass
    try:
        src = max(src, (web / "index.html").stat().st_mtime)
    except OSError:  # arch-ok: index.html 不存在时只看 src
        pass
    try:
        dist = (web / "dist" / "index.html").stat().st_mtime
    except OSError:  # arch-ok: dist 不存在 = 0，前端按“没有打包版”处理
        dist = 0.0
    return {"src_at": round(src, 1), "dist_at": round(dist, 1)}
