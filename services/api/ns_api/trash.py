"""
删除与回收站（EDITDEL 2026-10-31，项目方原话：“有些地方需要增加删除功能。比如一些过往的剧本我不喜欢，就需要有个 delete 按钮让我把它 delete 掉。”）

软删除：对象（文件 / 目录 + 它在 JSON 里的记录）移到 data/_trash/<日期>/<entry_id>/，并记 data/_trash/<日期>/MANIFEST.json；
一键还原 = 文件挪回原处 + 记录放回原位置。永久删除只由后端执行：操作人从登录会话取（项目方本人），界面二次确认（confirm=true）。
已定稿 / 正在出片 / 正在写作的对象：先给影响面；正在跑的一律阻止（blocked），已定稿的要 confirm=true 才删。

对象类型 type / id：
  story_run        <run_id>                       写过的剧本 / 运行记录 data/pipeline/runs/<run_id>/
  import_candidate <相对项目根的 .md 路径>         导入候选稿（data/staging_v3、data/staging_input、Qwen 交付物）
  take             <镜头>/<image|last|video>/<n>  镜头版本（首帧 / 尾帧 / 视频 take）
  cut              <相对 data/ 的 mp4 路径>        成片版本（data/episodes/…，连同 .timeline.json）
  asset_version    <asset_id>/<version>[@<文件名>]  资产版本（data/assets/asset_versions.json）
  asset_ref        <asset_id>/<ref_id>             资产参考图（asset_refs.json + 图片文件）
  asset_gen        <asset_id>/<gen_id>             资产生成记录（asset_gens.json + 图片文件）
  asset            <wardrobe 单品 id | look id>    整个资产（只允许没被造型 / 排期引用的）
  edit_version     <对象 id>|<v>                   编辑版本链里的一版（data/edits/versions，非当前版）
  sheet_candidate  <相对项目根的 png 路径>          设定图候选：data/pipeline/runs/<run>/images/sheets/<cid>/<cid>_look<X>_s<seed>.png
                                                   或人物页上传 assets/characters/<cid>/looks/<cid>_look<X>_up*.png；
                                                   各运行 assets/sheets_chosen.json 里选定的那张不能删
  prop             <prop_id>                       自建道具（data/props.json，/api/props）；衣橱映射的条目只读、不在这里删

接口：
  GET    /api/trash                               回收站列表（未永久删除的在前）
  GET    /api/trash/impact?type=&id=              删除影响面（不写任何东西）
  DELETE /api/trash/object?type=&id=&confirm=&by=&reason=   软删除
  POST   /api/trash/{entry_id}/restore            还原
  POST   /api/trash/{entry_id}/purge              {confirm:true} 永久删除（不可恢复；登录的项目方本人 + 二次确认按钮）
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ns_api import jobs as J
from ns_render import pipeline as P

router = APIRouter(tags=["trash"])
REPO = Path(__file__).resolve().parents[3]
TYPES = {"story_run": "剧本运行", "import_candidate": "导入候选稿", "take": "镜头版本", "cut": "成片版本",
         "asset_version": "资产版本", "asset_ref": "资产参考图", "asset_gen": "资产生成记录", "asset": "资产",
         "edit_version": "编辑版本", "sheet_candidate": "设定图候选", "prop": "道具"}
STAGE_LABEL = {"image": "首帧", "last": "尾帧", "video": "视频"}
CANDIDATE_ROOTS = ("data/staging_v3/", "data/staging_input/", "data/script_chat/", "data/qwen/", "projects/")
_lock = threading.RLock()


def trash_root() -> Path:
    return P.DATA / "_trash"


# ============================================================ 路径
def _abs(rel: str) -> Path:
    r = rel.replace("\\", "/")
    return P.DATA / r[5:] if r.startswith("data/") else REPO / r


def _rel(p: Path) -> str:
    p = Path(p)
    try:
        return "data/" + p.resolve().relative_to(P.DATA.resolve()).as_posix()
    except ValueError:
        return p.resolve().relative_to(REPO.resolve()).as_posix()


def _safe(raw: str) -> str:
    raw = (raw or "").replace("\\", "/").strip()
    if not raw or ":" in raw or raw.startswith("/") or ".." in raw.split("/"):
        raise HTTPException(422, f"路径不合法：{raw!r}")
    return raw


# ============================================================ 影响面
def _impact(type_: str, id_: str) -> dict:
    """→ {name, files:[相对路径], records:[…], blocked:[原因], confirm:[原因], notes:[…]}"""
    if type_ not in TYPES:
        raise HTTPException(422, f"type 只能是 {' | '.join(TYPES)}")
    out = {"type": type_, "id": id_, "type_label": TYPES[type_], "files": [], "records": [], "blocked": [],
           "confirm": [], "notes": []}
    fn = globals()[f"_impact_{type_}"]
    fn(id_, out)
    out["needs_confirm"] = bool(out["confirm"])
    out["can_delete"] = not out["blocked"]
    return out


def _impact_story_run(id_: str, out: dict) -> None:
    from ns_api import story_runs as SR
    d = SR._run_dir(id_)
    out["name"] = id_
    out["files"] = [_rel(d)]
    if SR._alive(id_):
        out["blocked"].append("这个剧本正在写作，写完或停下后再删")
    st = SR._read(d / SR.STATE) or {}
    if st.get("sent_to_import"):
        out["confirm"].append("这次运行的 P4 已送去导入（导入候选稿另算，不会一起删）")
    if SR.series_eps(d):
        out["confirm"].append("这是整季运行（SERIES 写作线的生产目录），里面有设定图 / 首帧作业等")
    try:
        main = (REPO / "config" / "script_mainline.json").read_text(encoding="utf-8")
        if id_ in main:
            out["confirm"].append("config/script_mainline.json 把它当主线引用")
    except OSError:
        pass
    try:
        src = json.dumps(json.loads((P.DATA / "import" / "script_v2.json").read_text(encoding="utf-8")).get("sources"),
                         ensure_ascii=False)
        if id_ in src:
            out["confirm"].append("当前已导入的生产剧本来自这次运行")
    except (OSError, ValueError):
        pass


def _impact_import_candidate(id_: str, out: dict) -> None:
    rel = _safe(id_)
    if not rel.lower().endswith((".md", ".txt")) or not any(rel.startswith(r) for r in CANDIDATE_ROOTS):
        raise HTTPException(422, "导入候选稿只能是 data/staging_v3、data/staging_input、Qwen 交付物下的 .md / .txt")
    p = _abs(rel)
    if not p.is_file():
        raise HTTPException(404, f"没有这个候选稿：{rel}")
    out["name"] = p.name
    out["files"] = [rel]
    try:
        last = [json.loads(x) for x in (P.DATA / "import" / "import_log.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        last = []
    used = [r for r in last if str(r.get("path", "")).replace("\\", "/").endswith(rel.split("/", 1)[-1])]
    if used:
        out["confirm"].append(f"这份稿曾被导入为生产剧本（{used[-1].get('at')}）；删掉不影响已导入的剧本，但以后不能再从它导入")


def _parse_take(id_: str) -> tuple[str, str, int]:
    m = re.fullmatch(r"(ep\d{2,3}-S\d+)/(image|first|last|video)/(\d+)", id_ or "")
    if not m:
        raise HTTPException(422, "镜头版本 id 写法：<镜头>/<image|last|video>/<n>")
    return m.group(1), {"first": "image"}.get(m.group(2), m.group(2)), int(m.group(3))


def _impact_take(id_: str, out: dict) -> None:
    shot, stage, n = _parse_take(id_)
    data = P.load_takes(shot)
    t = next((x for x in data.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
    if not t:
        raise HTTPException(404, f"{shot} 没有{STAGE_LABEL[stage]} v{n}")
    out["name"] = f"{shot} {STAGE_LABEL[stage]} v{n}"
    out["files"] = [f"data/{f}" for f in (t.get("file"), t.get("last_frame"), t.get("raw_file")) if f
                    and (P.DATA / f).is_file()]
    run = [j for j in J.pending(shot) if j.get("state") == "running"
           and {"first": "image"}.get(j.get("stage"), j.get("stage")) in (stage, None, "edit")]
    if run:
        out["blocked"].append(f"本镜正在出{STAGE_LABEL[stage]}（任务 {run[0]['id']}），跑完再删")
    if (data.get("locked") or {}).get(stage) == n:
        down = {"image": "尾帧和视频会标过期", "last": "视频会标过期", "video": "成片里用到的这条视频会缺"}[stage]
        out["confirm"].append(f"这是已定稿的{STAGE_LABEL[stage]}：删掉会取消定稿，{down}")
    if (data.get("active") or {}).get(stage) == n:
        rest = [x["n"] for x in data["takes"] if x.get("stage") == stage and x["n"] != n]
        out["notes"].append(f"这是当前版本：删后当前改为 v{max(rest)}" if rest else "这是唯一版本：删后本镜没有这一格")
    kids = [x["n"] for x in data["takes"] if x.get("stage") == stage and x.get("parent") == n]
    if kids:
        out["notes"].append(f"v{', v'.join(map(str, kids))} 是在它上面改出来的（修改链会断开一环，版本本身不受影响）")


def _impact_cut(id_: str, out: dict) -> None:
    rel = _safe(id_)
    rel = rel[5:] if rel.startswith("data/") else rel
    if not rel.startswith("episodes/") or not rel.endswith(".mp4"):
        raise HTTPException(422, "成片版本 id = data/episodes/ 下的 .mp4 路径")
    p = P.DATA / rel
    if not p.is_file():
        raise HTTPException(404, f"没有这个成片：{rel}")
    out["name"] = p.name
    out["files"] = [f"data/{rel}"] + [_rel(x) for x in (p.with_suffix(".timeline.json"),) if x.is_file()]
    m = re.search(r"ep(\d{2,3})", p.name)
    if m:
        from ns_api import cuts as CU
        j = CU._job_view(int(m.group(1)))
        if j and j.get("state") == "running":
            out["blocked"].append(f"第 {int(m.group(1))} 集正在合成，跑完再删")
    if not re.search(r"(PREVIEW|未完成|勿用|UI\d)", p.name, re.I):
        out["confirm"].append("这不是预览 / 对照版（文件名没有 PREVIEW / UI 标记），可能是交付成片")


def _split2(id_: str, what: str) -> tuple[str, str]:
    a, _, b = (id_ or "").partition("/")
    if not a or not b:
        raise HTTPException(422, f"{what} id 写法：<asset_id>/<…>")
    return a, b


def _aread(name: str) -> dict:
    from ns_api import asset_edit as AE
    return AE._read(name)


def _impact_asset_ref(id_: str, out: dict) -> None:
    aid, rid = _split2(id_, "资产参考图")
    r = next((x for x in _aread("asset_refs").get(aid) or [] if x.get("ref_id") == rid), None)
    if not r:
        raise HTTPException(404, f"没有参考图 {rid}")
    out["name"] = f"{aid} 参考图 {rid}"
    f = r.get("file")
    shared = [k for k, lst in _aread("asset_refs").items() for x in lst if x.get("file") == f and x.get("ref_id") != rid]
    out["files"] = [f] if f and _abs(f).is_file() and not shared else []
    if shared:
        out["notes"].append("同一张图还被别的资产引用：只删这条记录，图片文件保留")
    if r.get("role") == "identity":
        out["confirm"].append("这是身份参考（定妆确认）：删掉后出图不再用它锁脸")


def _impact_asset_gen(id_: str, out: dict) -> None:
    aid, gid = _split2(id_, "资产生成记录")
    g = next((x for x in _aread("asset_gens").get(aid) or [] if x.get("gen_id") == gid), None)
    if not g:
        raise HTTPException(404, f"没有生成记录 {gid}")
    out["name"] = f"{aid} 生成 {gid}"
    out["files"] = [f for f in (g.get("file"),) if f and _abs(f).is_file()]
    if g.get("state") in ("queued", "running"):
        out["blocked"].append("这条生成还在跑")


def _version_rec(id_: str) -> tuple[str, dict]:
    aid, rest = _split2(id_, "资产版本")
    ver, _, fname = rest.partition("@")
    lst = _aread("asset_versions").get(aid) or []
    cand = [v for v in lst if str(v.get("version")) == ver and (not fname or Path(str(v.get("file"))).name == fname)]
    if not cand:
        raise HTTPException(404, f"{aid} 没有版本 {rest}")
    return aid, cand[-1]


def _impact_asset_version(id_: str, out: dict) -> None:
    aid, v = _version_rec(id_)
    out["name"] = f"{aid} v{v.get('version')}"
    f = v.get("file")
    out["files"] = [f] if f and _abs(f).is_file() else []
    if f and _is_current_asset_image(v.get("asset_id") or aid, f):
        out["blocked"].append("这是该资产现在用的图（主图 / 预览 / 定稿底图）：先把当前版本换成别的再删")


def _is_current_asset_image(aid: str, f: str) -> bool:
    try:
        from ns_api.looks import get_store
        st = get_store()
        lk = st.get_look(aid)
        if lk is not None:
            return lk.preview_image == f
        it = next((i for i in st.wardrobe().items if i.id == aid), None)
        if it is not None:
            return bool(it.reference_images) and it.reference_images[0] == f
    except Exception:  # noqa: BLE001
        pass
    try:
        scenes = json.loads((P.DATA / "scenes.json").read_text(encoding="utf-8"))
        return f in json.dumps(scenes.get(aid) if isinstance(scenes, dict) else None, ensure_ascii=False)
    except (OSError, ValueError):
        return False


def _impact_asset(id_: str, out: dict) -> None:
    from ns_api.looks import get_store
    st = get_store()
    lk = st.get_look(id_)
    it = next((i for i in st.wardrobe().items if i.id == id_), None)
    if lk is None and it is None:
        raise HTTPException(404, f"没有资产 {id_}（整件删除只支持衣橱单品和造型）")
    out["name"] = (lk.name if lk else it.name) or id_
    look_txt = st._path("looks").read_text(encoding="utf-8") if st._path("looks").is_file() else ""
    sched = st._path("schedule").read_text(encoding="utf-8") if st._path("schedule").is_file() else ""
    if it is not None and re.search(rf'"{re.escape(id_)}"', look_txt):
        out["blocked"].append("这件单品还在造型里用着：先从造型里去掉再删")
    if re.search(rf'"{re.escape(id_)}"', sched):
        out["blocked"].append("排期（某集 / 某镜默认造型）还引用它：先换掉再删")
    out["notes"].append("整件资产删除：资产库里不再显示（图片文件保留在原处，还原后照常可用）")


def _impact_edit_version(id_: str, out: dict) -> None:
    from ns_api import edits as ED
    obj, _, v = (id_ or "").rpartition("|")
    if not obj or not v.isdigit():
        raise HTTPException(422, "编辑版本 id 写法：<对象 id>|<v>")
    ch = ED.load_chain(obj)
    rec = next((x for x in ch["versions"] if x["v"] == int(v)), None)
    if not rec or int(v) == 0:
        raise HTTPException(404 if not rec else 422, "没有这一版" if not rec else "原版不在编辑链里删（原版属于来源对象）")
    out["name"] = f"{Path(str(ch.get('original'))).name} 编辑 v{v}"
    out["files"] = [f for f in (rec.get("file"), rec.get("raw_file")) if f and _abs(f).is_file()]
    if ch["current"] == int(v):
        out["blocked"].append("这是当前采用的版本：先回滚或采用别的版本再删")


_SHEET_RE = re.compile(r"(data/pipeline/runs/[A-Za-z0-9_.\-]+/images/sheets/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+_look[A-Za-z0-9]+_s\d+\.png"
                       r"|assets/characters/[A-Za-z0-9_\-]+/looks/[A-Za-z0-9_\-]+_look[A-Za-z0-9]+_up[A-Za-z0-9_\-]*\.png)")


def _chosen_sheets() -> dict[str, str]:
    """各运行 assets/sheets_chosen.json 里选定的设定图：文件 → 键"""
    out = {}
    for f in (P.DATA / "pipeline" / "runs").glob("*/assets/sheets_chosen.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k, v in (d.items() if isinstance(d, dict) else []):
            if isinstance(v, dict) and v.get("file"):
                out[str(v["file"]).replace("\\", "/")] = f"{f.parent.parent.name}:{k}"
    return out


def _impact_sheet_candidate(id_: str, out: dict) -> None:
    rel = _safe(id_)
    if not _SHEET_RE.fullmatch(rel):
        raise HTTPException(422, "设定图候选 id = data/pipeline/runs/<run>/images/sheets/<cid>/<cid>_look<X>_s<seed>.png "
                                 "或 assets/characters/<cid>/looks/<cid>_look<X>_up*.png")
    p = _abs(rel)
    if not p.is_file():
        raise HTTPException(404, f"没有这张设定图：{rel}")
    out["name"] = p.name
    out["files"] = [rel]
    chosen = _chosen_sheets()
    if rel in chosen:
        out["blocked"].append(f"这是当前选定的设定图（{chosen[rel]}）：先在资产中心选另一张再删")
    thumb = p.parent.parent.parent / "_thumbs" / (p.stem + ".jpg")
    if thumb.is_file():
        out["files"].append(_rel(thumb))


def _props_file() -> Path:
    return P.DATA / "props.json"


def _impact_prop(id_: str, out: dict) -> None:
    try:
        d = json.loads(_props_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    row = next((x for x in d.get("props") or [] if isinstance(x, dict) and x.get("id") == id_), None)
    if not row:
        raise HTTPException(404, f"没有这个自建道具：{id_}（衣橱映射的条目只读）")
    out["name"] = row.get("name") or id_
    out["notes"].append("只删道具条目；它引用的图片 / LoRA 文件保留")


# ============================================================ 删除 / 还原
def _move_in(entry_dir: Path, rels: list[str]) -> list[dict]:
    moved = []
    for rel in rels:
        src = _abs(rel)
        if not src.exists():
            continue
        dest = entry_dir / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append({"from": rel, "to": _rel(dest)})
    return moved


def _detach(type_: str, id_: str) -> dict:
    """把对象的 JSON 记录摘下来（返回还原所需信息）；文件由调用方移动"""
    if type_ == "take":
        shot, stage, n = _parse_take(id_)
        from ns_render import frame_edit as FE
        info = {"shot": shot, "stage": stage}
        data = P.load_takes(shot)
        if (data.get("locked") or {}).get(stage) == n:
            FE.unlock(shot, stage)
            info["was_locked"] = True
        with P.shot_lock(shot):
            data = P.load_takes(shot)
            idx = next(i for i, x in enumerate(data["takes"]) if x.get("stage") == stage and x.get("n") == n)
            info["record"], info["index"] = data["takes"].pop(idx), idx
            info["was_active"] = (data.get("active") or {}).get(stage) == n
            P._save_takes(shot, data)
        if info["was_active"]:
            rest = [x["n"] for x in data["takes"] if x.get("stage") == stage]
            if rest:
                try:
                    P.set_active(shot, stage, max(rest))
                except Exception:  # noqa: BLE001  坏图不能设为当前 → 就让这一格空着
                    _clear_active(shot, stage)
            else:
                _clear_active(shot, stage)
        return info
    if type_ in ("asset_ref", "asset_gen", "asset_version"):
        from ns_api import asset_edit as AE
        name = {"asset_ref": "asset_refs", "asset_gen": "asset_gens", "asset_version": "asset_versions"}[type_]
        key = {"asset_ref": "ref_id", "asset_gen": "gen_id"}.get(type_)
        aid, rest = _split2(id_, type_)
        with AE._lock:
            allr = AE._read(name)
            removed = []
            if type_ == "asset_version":
                _a, rec = _version_rec(id_)
                for k, lst in allr.items():
                    for i, x in enumerate(list(lst)):
                        if x == rec:
                            removed.append({"key": k, "index": i, "record": x})
                for r in sorted(removed, key=lambda r: -r["index"]):
                    allr[r["key"]].pop(r["index"])
            else:
                lst = allr.get(aid) or []
                i = next(i for i, x in enumerate(lst) if x.get(key) == rest)
                removed.append({"key": aid, "index": i, "record": lst.pop(i)})
            AE._write(name, allr)
        info = {"store": name, "removed": removed}
        if type_ == "asset_version":
            info["detached_images"] = _detach_version_image(removed[0]["record"] if removed else {})
        return info
    if type_ == "asset":
        from ns_api.looks import get_store
        st = get_store()
        info = {}

        def fn():
            w = st.wardrobe()
            i = next((k for k, x in enumerate(w.items) if x.id == id_), None)
            if i is not None:
                info.update(kind="item", index=i, record=w.items.pop(i).model_dump(mode="json"))
                st._write("wardrobe", w)
                return
            b = st.lookbook()
            i = next(k for k, x in enumerate(b.looks) if x.id == id_)
            info.update(kind="look", index=i, record=b.looks.pop(i).model_dump(mode="json"))
            st._write("looks", b)
        st._mutate(fn)
        return info
    if type_ == "prop":
        from ns_api import asset_center_p1 as ACP
        with ACP._lock:
            d = json.loads(_props_file().read_text(encoding="utf-8"))
            i = next(k for k, x in enumerate(d.get("props") or []) if isinstance(x, dict) and x.get("id") == id_)
            rec = d["props"].pop(i)
            ACP._wjson(_props_file(), d)
        return {"index": i, "record": rec}
    if type_ == "edit_version":
        from ns_api import edits as ED
        obj, _, v = id_.rpartition("|")
        with ED._lock:
            ch = ED.load_chain(obj)
            i = next(k for k, x in enumerate(ch["versions"]) if x["v"] == int(v))
            rec = ch["versions"].pop(i)
            ED.save_chain(ch)
        return {"object": obj, "index": i, "record": rec}
    return {}


def _detach_version_image(rec: dict) -> list:
    """in_place 单品版本：从单品 images / reference_images 里去掉这张；造型版本：从 reference_images 去掉"""
    f = rec.get("file")
    if not f or not rec.get("in_place"):
        return []
    from ns_api.looks import get_store
    st = get_store()
    done = []

    def fn():
        w = st.wardrobe()
        for it in w.items:
            if it.id == rec.get("asset_id"):
                imgs = [im for im in it.images if im.file == f]
                if imgs or f in it.reference_images:
                    done.append({"kind": "item", "id": it.id, "images": [im.model_dump(mode="json") for im in imgs],
                                 "ref_index": it.reference_images.index(f) if f in it.reference_images else None})
                    it.images = [im for im in it.images if im.file != f]
                    it.reference_images = [r for r in it.reference_images if r != f]
                    st._write("wardrobe", w)
        b = st.lookbook()
        for lk in b.looks:
            if lk.id == rec.get("asset_id") and f in lk.reference_images:
                done.append({"kind": "look", "id": lk.id, "ref_index": lk.reference_images.index(f)})
                lk.reference_images = [r for r in lk.reference_images if r != f]
                st._write("looks", b)
    try:
        st._mutate(fn)
    except Exception:  # noqa: BLE001
        pass
    return done


def _clear_active(shot: str, stage: str) -> None:
    with P.shot_lock(shot):
        data = P.load_takes(shot)
        before = (data.get("active") or {}).pop(stage, None)
        P._save_takes(shot, data)
    P.audit_active(shot, stage, before, None, "删进回收站，当前清空", "trash._clear_active")   # K-OPS-Q23
    d = P.shot_dir(shot)
    for f in {"image": ["frame.png"], "last": ["last.png"], "video": ["video.mp4", "video_last.png"]}[stage]:
        p = d / f
        if p.is_file():
            bak = d / "_cleared"
            bak.mkdir(exist_ok=True)
            shutil.move(str(p), str(bak / f"{time.strftime('%Y%m%d-%H%M%S')}_{f}"))


def _manifest_path(day: str) -> Path:
    return trash_root() / day / "MANIFEST.json"


def _write_manifest(entry: dict) -> None:
    p = _manifest_path(entry["day"])
    try:
        man = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {"schema": "nsfs.trash/1", "entries": []}
    man["entries"] = [e for e in man["entries"] if e.get("entry_id") != entry["entry_id"]] + [
        {k: entry.get(k) for k in ("entry_id", "type", "id", "name", "deleted_at", "by", "reason", "state", "files",
                                   "restored_at", "purged_at")}]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


def _save_entry(entry: dict) -> None:
    d = trash_root() / entry["day"] / entry["entry_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "entry.json").write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_manifest(entry)


def _find_entry(entry_id: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"tr-[0-9a-f]{10}", entry_id or ""):
        raise HTTPException(404, f"回收站里没有 {entry_id}")
    for p in trash_root().glob(f"*/{entry_id}/entry.json"):
        return p.parent, json.loads(p.read_text(encoding="utf-8"))
    for man in trash_root().glob("*/MANIFEST.json"):   # 已永久删除：目录没了，只剩 MANIFEST
        for e in json.loads(man.read_text(encoding="utf-8")).get("entries") or []:
            if e.get("entry_id") == entry_id:
                return man.parent / entry_id, {**e, "day": man.parent.name}
    raise HTTPException(404, f"回收站里没有 {entry_id}")


@router.get("/api/trash/impact")
def impact(type: str, id: str):
    return _impact(type, id)


@router.delete("/api/trash/object")
def delete_object(request: Request, type: str, id: str, confirm: bool = False, by: str | None = None, reason: str = ""):
    from ns_api.edits import actor
    who = actor(request, by)
    by = who["user"] or who["by"]
    with _lock:
        imp = _impact(type, id)
        if imp["blocked"]:
            raise HTTPException(409, {"message": "现在不能删", "impact": imp})
        if imp["needs_confirm"] and not confirm:
            raise HTTPException(409, {"message": "要确认才删（confirm=true）", "impact": imp, "needs_confirm": True})
        day = time.strftime("%Y-%m-%d")
        entry_id = "tr-" + uuid.uuid4().hex[:10]
        d = trash_root() / day / entry_id
        d.mkdir(parents=True, exist_ok=True)
        info = _detach(type, id)
        moved = _move_in(d, imp["files"])
        entry = {"entry_id": entry_id, "day": day, "type": type, "type_label": TYPES[type], "id": id,
                 "name": imp["name"], "deleted_at": P.now(), "by": by, "reason": reason, "state": "trashed",
                 "files": moved, "detach": info, "impact": {k: imp[k] for k in ("confirm", "notes")}}
        _save_entry(entry)
    _invalidate()
    return entry


@router.get("/api/trash")
def list_trash(include_purged: bool = False, type: str | None = None):
    out = []
    for man in sorted(trash_root().glob("*/MANIFEST.json"), reverse=True):
        try:
            entries = json.loads(man.read_text(encoding="utf-8")).get("entries") or []
        except (OSError, ValueError):
            continue
        for e in entries:
            if (e.get("state") == "purged" and not include_purged) or e.get("state") == "restored":
                continue
            if type and e.get("type") != type:
                continue
            out.append({**e, "day": man.parent.name, "type_label": TYPES.get(e.get("type"), e.get("type")),
                        "preview": _preview(man.parent / e["entry_id"], e)})
    out.sort(key=lambda e: str(e.get("deleted_at") or ""), reverse=True)
    return {"entries": out, "root": "data/_trash"}


def _preview(d: Path, e: dict) -> str | None:
    for f in e.get("files") or []:
        if str(f.get("to", "")).lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and _abs(f["to"]).is_file():
            return "/files/" + f["to"][5:] if f["to"].startswith("data/") else None
    return None


@router.post("/api/trash/{entry_id}/restore")
def restore(entry_id: str):
    with _lock:
        d, e = _find_entry(entry_id)
        if e.get("state") != "trashed":
            raise HTTPException(409, f"这一项现在是“{e.get('state')}”，不能还原")
        clash = [f["from"] for f in e.get("files") or [] if _abs(f["from"]).exists()]
        if clash:
            raise HTTPException(409, f"原位置已有同名文件，不能覆盖：{clash}")
        for f in e.get("files") or []:
            dest = _abs(f["from"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(_abs(f["to"])), str(dest))
        _reattach(e["type"], e["id"], e.get("detach") or {})
        e.update(state="restored", restored_at=P.now())
        _save_entry(e)
    _invalidate()
    return e


def _reattach(type_: str, id_: str, info: dict) -> None:
    if type_ == "take" and info.get("record"):
        shot, stage = info["shot"], info["stage"]
        with P.shot_lock(shot):
            data = P.load_takes(shot)
            data["takes"].insert(min(info["index"], len(data["takes"])), info["record"])
            P._save_takes(shot, data)
        if info.get("was_active"):
            try:
                P.set_active(shot, stage, info["record"]["n"])
            except Exception:  # noqa: BLE001
                pass
        if info.get("was_locked"):
            from ns_render import frame_edit as FE
            try:
                FE.lock(shot, stage, info["record"]["n"])
            except Exception:  # noqa: BLE001  尾帧的定稿前提变了 → 只还原版本，不恢复定稿
                pass
    elif type_ in ("asset_ref", "asset_gen", "asset_version"):
        from ns_api import asset_edit as AE
        with AE._lock:
            allr = AE._read(info["store"])
            for r in sorted(info.get("removed") or [], key=lambda r: r["index"]):
                lst = allr.setdefault(r["key"], [])
                lst.insert(min(r["index"], len(lst)), r["record"])
            AE._write(info["store"], allr)
        if info.get("detached_images"):
            from ns_api.looks import get_store
            from ns_schema.looks import ItemImage
            st = get_store()

            def fn():
                w, b = st.wardrobe(), st.lookbook()
                for x in info["detached_images"]:
                    f = (info.get("removed") or [{}])[0].get("record", {}).get("file")
                    if x["kind"] == "item":
                        it = next((i for i in w.items if i.id == x["id"]), None)
                        if it:
                            it.images += [ItemImage.model_validate(im) for im in x.get("images") or []]
                            if x.get("ref_index") is not None and f not in it.reference_images:
                                it.reference_images.insert(x["ref_index"], f)
                    else:
                        lk = next((k for k in b.looks if k.id == x["id"]), None)
                        if lk and f not in lk.reference_images:
                            lk.reference_images.insert(x.get("ref_index") or 0, f)
                st._write("wardrobe", w)
                st._write("looks", b)
            st._mutate(fn)
    elif type_ == "asset" and info.get("record"):
        from ns_api.looks import get_store
        from ns_schema.looks import Look, WardrobeItem
        st = get_store()

        def fn():
            if info["kind"] == "item":
                w = st.wardrobe()
                w.items.insert(min(info["index"], len(w.items)), WardrobeItem.model_validate(info["record"]))
                st._write("wardrobe", w)
            else:
                b = st.lookbook()
                b.looks.insert(min(info["index"], len(b.looks)), Look.model_validate(info["record"]))
                st._write("looks", b)
        st._mutate(fn)
    elif type_ == "prop" and info.get("record"):
        from ns_api import asset_center_p1 as ACP
        with ACP._lock:
            try:
                d = json.loads(_props_file().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                d = {"props": []}
            lst = d.setdefault("props", [])
            if not any(isinstance(x, dict) and x.get("id") == info["record"].get("id") for x in lst):
                lst.insert(min(info["index"], len(lst)), info["record"])
            ACP._wjson(_props_file(), d)
    elif type_ == "edit_version" and info.get("record"):
        from ns_api import edits as ED
        with ED._lock:
            ch = ED.load_chain(info["object"])
            ch["versions"].insert(min(info["index"], len(ch["versions"])), info["record"])
            ED.save_chain(ch)


class PurgeBody(BaseModel):
    confirm: bool = False      # 二次确认按钮（项目方 2026-10-31：登录即本人，不再要求输入短语 / 名称）
    by: str | None = None


@router.post("/api/trash/{entry_id}/purge")
def purge(entry_id: str, request: Request, body: PurgeBody | None = None):
    from ns_api.edits import actor
    body = body or PurgeBody()
    who = actor(request, body.by)
    if who["by"] != "owner":
        raise HTTPException(403, "永久删除只接受登录的项目方本人")
    if not body.confirm:
        raise HTTPException(422, "永久删除要二次确认（confirm=true）")
    with _lock:
        d, e = _find_entry(entry_id)
        if e.get("state") != "trashed":
            raise HTTPException(409, f"这一项现在是“{e.get('state')}”，不能永久删除")
        root = trash_root().resolve()
        if not d.resolve().is_relative_to(root) or d.resolve() == root:
            raise HTTPException(500, "回收站路径异常，拒绝删除")
        shutil.rmtree(d, ignore_errors=False)
        e.update(state="purged", purged_at=P.now(), purged_by=who["user"] or who["by"])
        _write_manifest(e)
    return {"ok": True, "entry_id": entry_id, "name": e.get("name"), "purged_at": e["purged_at"]}


def _invalidate():
    try:
        from ns_api import app as A
        A._summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass
