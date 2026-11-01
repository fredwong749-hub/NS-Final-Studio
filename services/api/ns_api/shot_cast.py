"""DATAALIGN 2026-11-01：镜头卡“人物与造型”与出图同源（对齐契约 docs/DATA_MAP.md · K-DATA-001）。

项目方原话（11-01）：“S1、S2、S3、S4 的每一个 scene 里面，对应的剧本、对应的人头都不太一样，但我发现你都是一模一样”。

根因：/api/episodes/{n} 的 shots[].characters 原来只走旧造型库（ns_agent.looks.Resolver）：
  · 谁在画 = 正文关键词猜（“顾沉”两个字出现在动作里就算在画；“阿岚”不在关键词表里就永远不出现）；
  · 造型 = 旧库唯一一套 “<角色>-default”，look_label 为空 → 前端 letterOf 兜底成 “A”，所有镜头都是“林晚 A”；
  · 脸 = 旧库 plates/id_front_s0.png（顾沉没有 → 空头像），不是出图用的身份脸。
而出图（ns_render.unified_frame → ns_agent.asset_refs.resolve_shot）用的是：
  · 谁在画 = 剧本本镜 **人物** 行（shot.cast，presence 在画 / 局部；画外不算）；
  · 造型 = 资产中心整集排期 > 逐镜登记 <run>/assets/shot_looks.json > 剧本造型行匹配（A / B / C）；
  · 脸 = asset_refs.face_of（资产中心当前身份脸 > config 登记）。

本模块按出图同一口径给每镜算 cast，并合并进镜头卡的 characters（旧库的插槽 / 冲突 / 本镜覆盖信息照旧保留，
只是人选、造型字母、脸图改成与出图一致）。剧本不属于登记了资产的项目（例 weita 旧剧）→ 返回 None，保持旧行为。
只读：不写任何文件、不改剧本、不触发出图。
"""
from __future__ import annotations


def project_for(script) -> str | None:
    """与 unified_frame.project_for 同一规则（剧本来源路径里出现 asset_refs 登记的项目键）"""
    try:
        from ns_agent import asset_refs as AR
    except Exception:  # noqa: BLE001
        return None
    keys = list((AR._cfg().get("projects") or {}))
    for s in getattr(script, "sources", None) or []:
        path = str(getattr(s, "path", None) or (s.get("path") if isinstance(s, dict) else "") or "")
        k = next((k for k in keys if k in path), None)
        if k:
            return k
    return None


class CastCtx:
    """一次请求共享：项目键、逐镜登记、造型表（只在登记缺时才读）"""

    def __init__(self, script):
        self.project = project_for(script)
        self._reg: dict | None = None
        self._looks: dict | None = None
        self._face: dict[str, str | None] = {}

    def reg(self) -> dict:
        if self._reg is None:
            from ns_agent import asset_refs as AR
            self._reg = AR.registry_looks(self.project) if self.project else {}
        return self._reg

    def looks(self) -> dict:
        if self._looks is None:
            from ns_agent import asset_refs as AR
            self._looks = AR.load_looks(self.project) if self.project else {}
        return self._looks

    def face(self, cid: str) -> str | None:
        if cid not in self._face:
            from ns_agent import asset_refs as AR
            self._face[cid] = AR.face_of(self.project, cid) if self.project else None
        return self._face[cid]


def _url(rel: str | None) -> str | None:
    from ns_api import character_hub as CH
    return CH.url(rel)


def shot_cast(cc: CastCtx, ep, shot) -> list[dict] | None:
    """本镜在画角色（剧本 **人物** 行）+ 造型字母（与出图同一优先级）+ 身份脸。项目没登记资产 → None"""
    if not cc.project:
        return None
    from ns_agent import asset_refs as AR
    n_ep = int(AR.g(ep, "number") or AR.g(shot, "episode") or 0)
    idx = int(AR.g(shot, "index"))
    sid = f"ep{n_ep:02d}-S{idx}"
    reg = cc.reg().get(sid, {}) or {}
    out = []
    for name, pr in AR.cast_on_screen(shot):
        cid = AR.NAME_ID.get(name, name)
        lid = AR.episode_look_override(cc.project, cid, n_ep)
        how = "hub_episode" if lid else ""
        if not lid:
            v = reg.get(cid)
            lid = (v or {}).get("look") if isinstance(v, dict) else v
            how = "registry" if lid else ""
        if not lid:
            row = AR.look_for(ep, name, idx)
            if row is not None:
                lid, score, _dev = AR.match_look(cc.looks().get(cid) or {}, AR.g(row, "slots"), AR.g(row, "raw") or "")
                how = f"script_match {score:.2f}" if lid else ""
        face = cc.face(cid)
        out.append({"character": cid, "name": name, "presence": pr, "look": lid or None, "look_how": how or None,
                    "face_file": face, "face_url": _url(face)})
    return out


def merge(cast: list[dict] | None, briefs: list[dict]) -> list[dict]:
    """镜头卡 characters：cast 为 None → 旧库原样；否则按剧本人物行重排（旧库条目里的插槽 / 冲突 / 覆盖保留）"""
    if cast is None:
        return briefs
    by = {b.get("character"): b for b in briefs}
    out = []
    for c in cast:
        b = dict(by.get(c["character"]) or {
            "character": c["character"], "name": c["name"], "look_id": None, "look_name": "", "label": c["name"],
            "d_state": None, "has_override": False, "changed_from_prev": False, "changed_fields": [],
            "slots": [], "conflicts": []})
        lid = c["look"]
        b.update({
            "name": c["name"],
            "face_url": c["face_url"] or b.get("face_url"),
            "look_label": lid or "",                     # 造型字母 = 出图用的那套（A / B / C）；对不上登记 = 空（前端显示“?”）
            "look_name": f"造型{lid}" if lid else "造型未登记",
            "label": f"{c['name']} · {'造型' + lid if lid else '造型未登记'}" + (f" · {c['presence']}" if c["presence"] != "在画" else ""),
            "presence": c["presence"], "look_how": c["look_how"], "cast_source": "script_cast",
        })
        out.append(b)
    return out



_IMPORT = {"key": None, "val": None}


def import_project() -> str | None:
    """当前画布剧本（data/import/script_v2.json 的 sources）对应的资产项目键；只读 sources，按文件 mtime 缓存。
    用于没带 run 参数的“出图线新图”接口默认取这部剧自己的运行目录，而不是“最近有图的任一运行”"""
    from pathlib import Path
    import json
    f = Path(__file__).resolve().parents[3] / "data" / "import" / "script_v2.json"
    try:
        st = f.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    if _IMPORT["key"] != key:
        try:
            src = (json.loads(f.read_text(encoding="utf-8")) or {}).get("sources") or []
        except (OSError, ValueError):
            src = []
        class _S:   # noqa: N801  project_for 只认 .sources
            sources = src
        _IMPORT.update(key=key, val=project_for(_S))
    return _IMPORT["val"]


_EPCAST = {"key": None, "val": None}


def episode_cast_ids() -> dict[int, list[str]] | None:
    """集 → 本集在画 / 局部的人物 id（剧本 **人物** 行，与出图 asset_refs.cast_on_screen 同口径，按出场顺序）。
    当前剧本不属于登记了资产的项目 → None（调用方保持旧口径）。只读剧本 JSON，按 mtime 缓存"""
    import json
    from pathlib import Path
    if not import_project():
        return None
    f = Path(__file__).resolve().parents[3] / "data" / "import" / "script_v2.json"
    try:
        st = f.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    if _EPCAST["key"] != key:
        try:
            from ns_agent import asset_refs as AR
            sc = json.loads(f.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            return None
        out: dict[int, list[str]] = {}
        for e in sc.get("episodes") or []:
            lst = out.setdefault(int(e.get("number") or 0), [])
            for sh in e.get("shots") or []:
                for name, _pr in AR.cast_on_screen(sh):
                    cid = AR.NAME_ID.get(name, name)
                    if cid not in lst:
                        lst.append(cid)
        _EPCAST.update(key=key, val=out)
    return _EPCAST["val"]
