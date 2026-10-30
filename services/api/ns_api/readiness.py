"""
镜头就绪闸门 + 一条链显示（docs/audit/shot_readiness_and_continuity.md §2–§4）。

每镜在 /api/episodes 摘要里带：
  owner          gpu3 | laptop   谁负责出首尾帧+视频。规则来自 config/shot_ownership.json（项目级），
                                 以及 data/renders_gpu3/epXX/SN/status.json 的 {owner:"gpu3"}（镜头级）
  frames_source  gpu3 | laptop | none   行内显示的首帧/尾帧/视频来自哪条链（永不混用）
  gpu3           gpu3 链（renders_gpu3 镜像；镜像缺文件时经桥 /api/gpu3-media 读取）
  laptop_history 笔记本旧版本（gpu3 负责时只作历史，「笔记本旧版本，未用于视频」）
  readiness      {ready, items:[{key,label,ok,level,reason,source}], blocked_reasons:[]}

ok 表示通过闸门；level 只管颜色（ok 绿 / warn 黄 / fail 红）。时长用默认 10s：ok=True、level=warn；
衔接未检查：ok=False、level=warn（闸门 §2.5 要求检查通过，但不是「缺东西」）。
"""
import calendar
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from ns_render import pipeline as P
from ns_api import project_ctx as PJC

OWNERSHIP_FILE = PJC.REPO / "config" / "shot_ownership.json"
BRIDGE_URL = os.environ.get("NS_GPU3_BRIDGE", "http://127.0.0.1:15180")
GPU3_ROOT: Path | None = None          # 测试用：覆盖 weita 的 renders_gpu3 镜像位置

HISTORY_NOTE = "笔记本旧版本，未用于视频"
GPU3_RERENDER_STAGES = ("image", "last", "video", "both")

ITEM_LABEL = {"first": "首帧", "last": "尾帧", "chain": "视频用此对", "img": "img", "motion": "motion",
              "duration": "时长", "sound": "sound/H3", "music_cue": "配乐 cue", "bgm": "本集 BGM",
              "continuity": "衔接"}


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- 项目 / 归属

def current_slug() -> str:
    """当前画布对应的项目：P.ROOT 是仓库根 = weita；子进程（NS_PROJECT_ROOT）按登记表的 root 反查"""
    try:
        root = P.ROOT.resolve()
        if root == PJC.REPO.resolve():
            return PJC.DEFAULT_SLUG
        for ctx in PJC.list_projects():
            if ctx.root.resolve() == root:
                return ctx.slug
    except Exception:
        pass
    return PJC.DEFAULT_SLUG


def project_owner(slug: str) -> tuple[str, str]:
    """项目级归属 → (gpu3|laptop, 依据)。新项目默认 laptop（非成人帧在笔记本），登记表条目写 owner 可改"""
    rule = (_read(OWNERSHIP_FILE, {}).get("projects") or {}).get(slug) or {}
    if rule.get("owner"):
        return str(rule["owner"]), f"config/shot_ownership.json：{slug} → {rule['owner']}"
    if slug != PJC.DEFAULT_SLUG:
        for e in PJC.load_registry().get("projects", []):
            if e.get("slug") == slug and e.get("owner"):
                return str(e["owner"]), f"项目登记表：{slug} → {e['owner']}"
    return "laptop", "默认（笔记本出非成人帧）"


def gpu3_root(slug: str) -> Path:
    if slug == PJC.DEFAULT_SLUG:
        return GPU3_ROOT or (P.DATA / "renders_gpu3")
    try:
        return PJC.get_project(slug).renders_gpu3
    except Exception:
        return P.DATA / "renders_gpu3" / slug


def shot_gpu3_dir(shot_id: str, slug: str) -> Path:
    ep, sn = shot_id.split("-")
    return gpu3_root(slug) / ep / sn


def _rel(p: Path) -> str | None:
    try:
        return p.resolve().relative_to(P.DATA.resolve()).as_posix()
    except ValueError:
        return None


def file_url(rel: str | None) -> str | None:
    """相对 data/ 的路径 → /files URL（带 mtime 防缓存）；镜像里没有 → None"""
    if not rel:
        return None
    p = P.DATA / rel
    return f"/files/{rel}?v={int(p.stat().st_mtime)}" if p.exists() else None


def bridge_url(rel: str) -> str:
    """镜像还没同步的 gpu3 文件：经 ns_api 同源代理到桥（/api/gpu3-media/<相对 data 的路径>）"""
    return f"/api/gpu3-media/{rel}"


# ---------------------------------------------------------------- gpu3 链

def _epoch(iso: str) -> float:
    try:
        return calendar.timegm(time.strptime(iso.rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 0.0


def _take(takes: dict, stage: str) -> dict | None:
    n = (takes.get("active") or {}).get(stage)
    if n is None:
        return None
    return next((t for t in takes.get("takes", []) if t.get("stage") == stage and t.get("n") == n), None)


def _pick(cands: list[tuple[str | None, str]]) -> dict:
    """候选 (相对 data 的路径, 说明)：镜像里有就用 /files；都没有时用第一个声明过的（经桥读取）"""
    for rel, why in cands:
        if rel and (P.DATA / rel).exists():
            return {"rel": rel, "url": file_url(rel), "mirrored": True, "why": why}
    for rel, why in cands:
        if rel and why.startswith("take"):
            return {"rel": rel, "url": bridge_url(rel), "mirrored": False, "why": why}
    return {"rel": None, "url": None, "mirrored": False, "why": ""}


def gpu3_chain(shot_id: str, slug: str) -> dict:
    d = shot_gpu3_dir(shot_id, slug)
    takes = _read(d / "takes.json", {"takes": [], "active": {}}) or {"takes": [], "active": {}}
    status = _read(d / "status.json", {}) or {}
    img, vid = _take(takes, "image"), _take(takes, "video")
    rel = lambda name: _rel(d / name)
    first = _pick([(img.get("file") if img else None, f"take image v{img['n']}" if img else ""),
                   (rel("frame.png"), "frame.png")])
    last = _pick([(rel("last.png"), "last.png"), (rel("last_target.png"), "last_target.png"),
                  (vid.get("last_frame") if vid else None, f"take video v{vid['n']} 尾帧" if vid else "")])
    video = _pick([(vid.get("file") if vid else None, f"take video v{vid['n']}" if vid else ""),
                   (rel("video.mp4"), "video.mp4")])
    active = {k: v for k, v in (takes.get("active") or {}).items() if v is not None}
    # 同一条链：尾帧由当前首帧编辑得到 → 尾帧文件不能早于当前首帧 take（镜像保留 gpu3 的 mtime）
    last_time = None
    if last["rel"] and last["mirrored"]:
        last_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((P.DATA / last["rel"]).stat().st_mtime))
    first_time = img.get("created_at") if img else None
    last_before_first = bool(last_time and first_time and _epoch(last_time) + 60 < _epoch(first_time))
    video_before_first = bool(img and vid and img.get("created_at") and vid.get("created_at")
                              and vid["created_at"] < img["created_at"])
    br = status.get("blocked_reasons") or []
    return {
        "present": bool(active or first["rel"] or last["rel"] or video["rel"]),
        "dir": _rel(d),
        "first_frame": first["url"], "first_mirrored": first["mirrored"], "first_from": first["why"],
        "last_frame": last["url"], "last_mirrored": last["mirrored"], "last_from": last["why"],
        "video": video["url"], "video_mirrored": video["mirrored"], "video_from": video["why"],
        "image_take": img["n"] if img else None, "video_take": vid["n"] if vid else None,
        "image_created": img.get("created_at") if img else None,
        "video_created": vid.get("created_at") if vid else None,
        "video_before_first": video_before_first,
        "last_time": last_time, "last_before_first": last_before_first,
        "takes_count": {st: sum(1 for t in takes.get("takes", []) if t.get("stage") == st) for st in ("image", "video")},
        "status": status.get("status"), "owner": status.get("owner"),
        "blocked_reasons": [str(x) for x in br] if isinstance(br, list) else [str(br)],
        "continuity": status.get("continuity"),
        "updated_at": status.get("updated_at"),
    }


def shot_owner(shot_id: str, slug: str, chain: dict) -> tuple[str, str]:
    owner, why = project_owner(slug)
    if owner != "gpu3" and str(chain.get("owner") or "").lower() == "gpu3":
        return "gpu3", f"{chain['dir']}/status.json owner=gpu3"
    return owner, why


# ---------------------------------------------------------------- 衔接

def continuity_item(chain: dict, prev_id: str | None) -> dict:
    """status.json 的 continuity（gpu3 帧闸门 §3.4）。格式宽松：字符串，或 {verdict|status|result|ok, reasons|fail|issues}"""
    c = chain.get("continuity")
    if not prev_id:
        return _item("continuity", True, "ok", "本集第一镜（不和上一镜比）", "rule")
    if c in (None, "", {}):
        return _item("continuity", False, "warn", f"未检查（与 {prev_id} 尾帧）", "none")
    if isinstance(c, str):
        verdict, reasons = c.lower(), []
    else:
        verdict = str(c.get("verdict") or c.get("status") or c.get("result") or "").lower()
        if not verdict and "ok" in c:
            verdict = "pass" if c["ok"] else "fail"
        reasons = c.get("reasons") or c.get("fail") or c.get("issues") or []
        reasons = [str(x) for x in (reasons if isinstance(reasons, list) else [reasons])]
    src = "gpu3 status.json"
    if verdict in ("pass", "ok", "passed", "true"):
        return _item("continuity", True, "ok", f"与 {prev_id} 衔接通过", src)
    if verdict in ("warn", "warning", "hold"):
        return _item("continuity", True, "warn", "衔接有提醒：" + ("；".join(reasons) or verdict), src)
    if verdict in ("pending", "unchecked", "skip", "skipped"):
        return _item("continuity", False, "warn", f"未检查（{verdict}）", src)
    return _item("continuity", False, "fail", f"与 {prev_id} 衔接不通过：" + ("；".join(reasons) or verdict or "未说明"), src)


# ---------------------------------------------------------------- 就绪闸门

def _item(key: str, ok: bool, level: str, reason: str, source: str) -> dict:
    return {"key": key, "label": ITEM_LABEL[key], "ok": ok, "level": level, "reason": reason, "source": source}


def _txt(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ""


def readiness(*, s, ep, adult: bool, edit, ep_edit: dict, owner: str, frames_source: str, chain: dict,
              laptop: dict, prev_id: str | None) -> dict:
    items: list[dict] = []
    by = "gpu3" if frames_source == "gpu3" or owner == "gpu3" else "laptop"
    # 1–2 首帧 / 尾帧（同一条链）
    if by == "gpu3":
        if chain["first_frame"]:
            items.append(_item("first", True, "ok" if chain["first_mirrored"] else "warn",
                               f"gpu3 {chain['first_from']}" + ("" if chain["first_mirrored"] else "（镜像未同步，经桥读取）"),
                               "gpu3"))
        else:
            items.append(_item("first", False, "fail", "gpu3 还没出首帧" if owner == "gpu3" else "没有首帧", "gpu3"))
        if chain["last_frame"] and chain.get("last_before_first"):
            items.append(_item("last", False, "fail",
                               f"尾帧 {chain['last_from']}（{chain['last_time']}）早于当前首帧 v{chain['image_take']}"
                               f"（{chain['image_created']}）：不是由这张首帧编辑得到，两帧不同链，要请 gpu3 重出尾帧",
                               "gpu3"))
        elif chain["last_frame"]:
            items.append(_item("last", True, "ok" if chain["last_mirrored"] else "warn",
                               f"gpu3 {chain['last_from']}（与首帧同一 take 链）", "gpu3"))
        else:
            items.append(_item("last", False, "fail", "gpu3 还没出尾帧（尾帧须由本链首帧编辑得到）", "gpu3"))
        if chain["video_take"] is not None and chain["video_before_first"]:
            items.append(_item("chain", False, "fail",
                               f"首帧 v{chain['image_take']} 是在视频 v{chain['video_take']} 之后出的："
                               "视频用的不是这张首帧，要请 gpu3 重出视频", "gpu3 takes.json"))
    else:
        items.append(_item("first", bool(laptop["first"]), "ok" if laptop["first"] else "fail",
                           f"笔记本首帧 v{laptop['first_take']}" if laptop["first"] else "没有首帧", "laptop"))
        if laptop["last"]:
            items.append(_item("last", True, "ok", f"笔记本尾帧（{laptop['last_from']}，与首帧同链）", "laptop"))
        else:
            items.append(_item("last", False, "fail", "没有尾帧（须由本镜首帧编辑得到）", "laptop"))
    # 3–5 剧本提示词
    items.append(_item("img", bool(_txt(s.img_prompt)), "ok" if _txt(s.img_prompt) else "fail",
                       "剧本 img" if _txt(s.img_prompt) else "剧本没有 img 画面提示词", "script"))
    items.append(_item("motion", bool(_txt(s.motion_prompt)), "ok" if _txt(s.motion_prompt) else "fail",
                       "剧本 motion" if _txt(s.motion_prompt) else "剧本没有 motion 镜头运动提示词", "script"))
    dur, dsrc = getattr(s, "duration", 10), getattr(s, "duration_source", "default")
    items.append(_item("duration", True, "ok" if dsrc == "script" else "warn",
                       f"{dur}s（剧本写明）" if dsrc == "script" else f"默认{dur}s（剧本没写 **时长**）", dsrc))
    # 6 声音：sound + H3（亲密镜头另要【亲密声】）
    sound, h3, intimate = _txt(s.sound), _txt(getattr(s, "sound_h3", "")), _txt(getattr(s, "sound_intimate", ""))
    sc_edit = _txt(getattr(edit, "soundscape", None))
    miss = []
    if not sound:
        miss.append("剧本没有 sound 行")
    if not h3 and not sc_edit:
        miss.append("缺【H3 audio】声音提示词（v3 剧本）")
    if adult and not intimate:
        miss.append("亲密镜头缺【亲密声】")
    src = "edit" if (sc_edit and not h3) else "script"
    items.append(_item("sound", not miss, "fail" if miss else "ok",
                       "；".join(miss) if miss else ("sound + H3" + (" + 亲密声" if adult else "") +
                                                     ("（H3 用人工环境声）" if src == "edit" else "")), src))
    # 7 本镜配乐 cue
    cue, cue_edit = _txt(getattr(s, "music_cue", "")), _txt(getattr(edit, "music", None))
    items.append(_item("music_cue", bool(cue or cue_edit), "ok" if (cue or cue_edit) else "fail",
                       ("人工配乐" if cue_edit else "剧本【配乐】") if (cue or cue_edit) else "缺本镜【配乐】cue（v3 剧本）",
                       "edit" if cue_edit else ("script" if cue else "none")))
    # 8 本集 BGM
    bgm, bgm_edit = _txt(getattr(ep, "music_bgm", "")), _txt(ep_edit.get("music"))
    raw = _txt(getattr(ep, "music", ""))
    items.append(_item("bgm", bool(bgm or bgm_edit), "ok" if (bgm or bgm_edit) else "fail",
                       ("本集人工 BGM" if bgm_edit else "剧本【BGM】") if (bgm or bgm_edit) else
                       ("剧本配乐行没有【BGM】英文提示" if raw else "缺本集 BGM 提示词（v3 剧本 **配乐** 行）"),
                       "edit" if bgm_edit else ("script" if bgm else "none")))
    # 9 衔接
    items.append(continuity_item(chain, prev_id))

    reasons = [f"{i['label']}：{i['reason']}" for i in items if not i["ok"]]
    gpu3_br = list(chain.get("blocked_reasons") or [])
    if str(chain.get("status") or "").lower() == "blocked" and not gpu3_br:
        gpu3_br = ["gpu3 status.json status=blocked"]
    return {"ready": not reasons and not gpu3_br, "items": items, "blocked_reasons": reasons + [
        f"gpu3：{r}" for r in gpu3_br], "gpu3_blocked_reasons": gpu3_br, "gpu3_status": chain.get("status"),
            "by": by}


def episode_extras(ep_number: int, slug: str) -> dict:
    """本集衔接表 continuity_sheet.jpg 与 qa.json（gpu3 镜像）"""
    d = gpu3_root(slug) / f"ep{ep_number:02d}"
    sheet = _rel(d / "continuity_sheet.jpg")
    return {"continuity_sheet": file_url(sheet) if sheet else None,
            "continuity_sheet_path": sheet,
            "qa": _read(d / "qa.json", None)}


# ---------------------------------------------------------------- 重渲请求 → gpu3（桥）

def post_rerender(req: dict, timeout: float = 8.0) -> dict:
    """POST /api/gpu3/rerender（桥写 gpu3 上的 rerender_queue.jsonl；笔记本镜像里的队列只读，不在本机追加）"""
    data = json.dumps(req, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(f"{BRIDGE_URL}/api/gpu3/rerender", data=data, method="POST",
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_media(rel: str, range_header: str | None, timeout: float = 20.0):
    """桥 /api/gpu3/media/<相对 data 的路径>（支持 Range）→ urllib 响应对象"""
    from urllib.parse import quote
    h = {"Range": range_header} if range_header else {}
    r = urllib.request.Request(f"{BRIDGE_URL}/api/gpu3/media/{quote(rel)}", headers=h)
    return urllib.request.urlopen(r, timeout=timeout)

