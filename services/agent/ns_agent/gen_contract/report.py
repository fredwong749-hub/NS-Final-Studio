"""契约逐项结果表（markdown）+ 接触印样（GEN_CONTRACT §4 回报格式 ②③）。"""
from __future__ import annotations

from pathlib import Path

from . import ROOT

MARK = {"pass": "通过", "fail": "**不通过**", "na": "不适用", "untested": "**未测**"}


def _ev(ev: dict) -> str:
    keep = {k: v for k, v in (ev or {}).items() if k not in ("rows", "slots") and v not in (None, [], {})}
    s = "；".join(f"{k}={v}" for k, v in keep.items())
    return s[:160]


def markdown(rows: list[dict], title: str = "契约逐项结果表") -> str:
    """rows: [{"subject": 镜号 / 图名, "pre": ContractResult.to_dict() | None, "post": ... | None, "image": 路径}]"""
    out = [f"## {title}", ""]
    for r in rows:
        out.append(f"### {r['subject']}" + (f"　`{r['image']}`" if r.get("image") else ""))
        out.append("")
        out.append("| 项 | 内容 | 结果 | 说明 / 数字 | 证据 |")
        out.append("|---|---|---|---|---|")
        for stage in ("pre", "post"):
            d = r.get(stage)
            if not d:
                continue
            for it in d["items"]:
                out.append(f"| {it['id']} | {it['title']} | {MARK.get(it['status'], it['status'])} | "
                           f"{(it.get('detail') or '').replace('|', '／')} | {_ev(it.get('evidence')).replace('|', '／')} |")
            rows2 = next((it["evidence"].get("rows") for it in d["items"] if it["id"] == "Q2" and it.get("evidence")), None)
            if rows2:
                out.append("")
                out.append("| Q2 明细 | 来源 | 区域 | CLIP | 直方图 | 过 |")
                out.append("|---|---|---|---|---|---|")
                for q in rows2:
                    out.append(f"| {q['label']} | {q.get('source')} | {q.get('zone') or '整体'} | {q['clip']:.3f} | {q['hist']:.2f} | "
                               f"{'是' if q.get('pass') else '否'} |")
        out.append("")
    return "\n".join(out)


def contact_sheet(entries: list[dict], out: str | Path, thumb_h: int = 420) -> str:
    """entries: [{"label", "image", "refs": [路径...]}] → 每行：生成图 + 本镜参考图（按槽位），底部标注"""
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for fp in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            font = ImageFont.truetype(fp, 22)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    rows = []
    for e in entries:
        tiles = []
        for k, p in enumerate([e["image"], *(e.get("refs") or [])]):
            pp = Path(p) if Path(p).is_absolute() else ROOT / p
            try:
                im = Image.open(pp).convert("RGB")
            except OSError:
                continue
            h = thumb_h if k == 0 else int(thumb_h * 0.6)
            im = im.resize((max(1, int(im.width * h / im.height)), h))
            tiles.append(im)
        w = sum(t.width for t in tiles) + 10 * len(tiles) + 10
        row = Image.new("RGB", (w, thumb_h + 40), "white")
        x = 10
        for t in tiles:
            row.paste(t, (x, 0))
            x += t.width + 10
        lab = e.get("label", "")
        flags = review_flags(e.get("postflight")) if e.get("postflight") else []
        if flags and "待目检" not in lab:
            lab = "待目检：" + "；".join(flags) + " ｜ " + lab
        ImageDraw.Draw(row).text((10, thumb_h + 8), lab[:90], fill=(200, 30, 30) if "待目检" in lab else (20, 20, 20), font=font)
        rows.append(row)
    W = max((r.width for r in rows), default=100)
    sheet = Image.new("RGB", (W, sum(r.height for r in rows) + 10), (235, 235, 235))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 5
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=90)
    return str(out)


# ---------------------------------------------------------------- Q4 塑料 / 娃娃脸：总调度目检闸（11-01，Q4 自动判定不可靠，只记录）
def q4_metrics(pf: dict | None) -> dict:
    """从 postflight 结果取 Q4 脸部度量（metrics.face_texture，记录在 Q4 的 evidence 里）"""
    it = next((i for i in (pf or {}).get("items") or [] if i.get("id") == "Q4"), None) or {}
    ev = it.get("evidence") or {}
    return {k: ev.get(k) for k in ("face_hf", "face_lap", "face_oil", "p_plastic", "lap_full", "face_px")}


from ..asset_refs import ID_NAME as WHO   # noqa: E402  OVERSIGHT-F P2：同一张人物表（V2 清单角色名由 register_manifest_names 登记）


def review_flags(pf: dict | None) -> list[str]:
    """只记录、不挡契约、要总调度目检的项（总调度 11-01：印样上标“待目检”）：
    未校准的外层单品探针低（例：顾沉深灰西装）/ 外层单品未测 / 鞋待目检 / 同一角色第二张脸"""
    out = []
    items = {i.get("id"): i for i in (pf or {}).get("items") or []}
    q2 = items.get("Q2") or {}
    for line in str(q2.get("detail") or "").split("；"):
        if "只记录（未校准）" in line:
            out.append(line.replace("，只记录（未校准）", "").replace("外层探针 ", "")[:40])
        elif "未测（没有" in line and "的脸框" in line:
            out.append(line.split("（")[0] + " 未测")
    if q2.get("status") == "na" and "只记录区" in str(q2.get("detail") or ""):
        out.append("局部特写的单品（指甲 / 手套等）没自动比对")
    if (q2.get("evidence") or {}).get("review") or "鞋待目检" in str(q2.get("detail") or ""):
        out.append("鞋")
    for qid, what in (("Q7", "场景相似度低"), ("Q5", "手型可疑")):
        ev = (items.get(qid) or {}).get("evidence") or {}
        det = str((items.get(qid) or {}).get("detail") or "")
        if ev.get("would_fail") or (qid == "Q5" and "手型可疑" in det and "只记录" in det):
            out.append(what)
    q9 = items.get("Q9") or {}
    if (q9.get("evidence") or {}).get("would_fail"):
        out.append("本地看图：" + str(q9.get("detail") or "")[:30])
    if "只记录：纯数字" in str((items.get("Q6") or {}).get("detail") or ""):
        out.append("画面里有数字")
    q1 = str((items.get("Q1") or {}).get("detail") or "")
    if "同一角色第二张脸" in q1:
        out.append("第二张脸（镜像 / 重复人物）")
    return out


def q4_caption(pf: dict | None) -> str:
    """缩略图下的一行：待目检项（若有）+ 脸部高频（越低越像磨皮）· 塑料探针 · 脸部油光 · 整图清晰度"""
    m = q4_metrics(pf)
    flags = review_flags(pf)
    head = ("待目检：" + "；".join(flags) + " ｜ ") if flags else ""
    if m.get("face_hf") is None:
        return head + "Q4：没检出脸"
    return head + (f"脸高频 {m['face_hf']:.2f} · 塑料 {m['p_plastic']:.3f} · 油光 {m['face_oil']:.3f}"
                   + (f" · 整图 {m['lap_full']:.0f}" if m.get("lap_full") is not None else ""))


def q4_sort_key(pf: dict | None):
    """“最可能塑料的排最前”：脸部高频能量从低到高（磨皮 / 娃娃脸偏低），同分时塑料探针高的在前；没检出脸的排最后"""
    m = q4_metrics(pf)
    if m.get("face_hf") is None:
        return (1, 0.0, 0.0)
    return (0, float(m["face_hf"]), -float(m.get("p_plastic") or 0))
