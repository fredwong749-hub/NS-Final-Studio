"""人物摆位判定（单一来源，K-WRT-H15 / H16；总调度 11-02：项目方亲标 20 张融合样本，IMGFIX 分析——
“自然”的图都是单人、非特写、人物和场景物件有接触、身体侧向；“贴图”的多是正面居中站立的设定图姿势，或者双人、特写）。

逐镜（看 img 原文 + 人物行）判：
  H15 接触   每个“在画”人物在 img 里至少有一个写了他名字的分句带接触动作（扶 / 坐 / 拿 / 靠 / 握 / 撑 …），
             且没有“正面直立对镜头”的写法（同一分句里既写站 / 直立，又写正面 / 面向镜头 / 看镜头）。“局部”人物不判。
  H16 双人   ≥2 个“在画”（露脸）人物的镜，景别不许是 大特写 / 特写 / 近景 / 中近景——用中景以上，或把其中一人写成前景“局部”。
读方：tools/script_rsi/autoflow.all_fails（补丁目标）、tools/script_rsi/rubric_audit.gate（导入闸门）、本文件 dist（分布）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CONTACT = re.compile(r"扶|坐|拿|靠|倚|握|撑|搭|按|捏|端|托|抱|攥|贴着|贴在|抵|趴|躺|跪|踩|蹲|攀|勾着|勾住|夹着|捧|提着|拎|摸|抚|压着|压在|搂|抓|拽|翻着|翻开|放在|搁在|摁|枕|蜷|举着|拉着|拉住|推着|推开|扣着|扣在|插在|点在|划过|捻|揉|接过|递|拄|倚")
UPRIGHT = re.compile(r"站着|站在|站立|直立|笔直地站|立在")
FRONTAL = re.compile(r"正面|面向镜头|面对镜头|看向镜头|直视镜头|对着镜头|看镜头|朝向镜头")
TIGHT = ("大特写", "特写", "近景", "中近景")
SPLICE_PART = r"的(?:左手|右手|手|左肩|右肩|肩|后背|背|手肘|手指|后腰|腰)[^，；。]{0,8}?(?:扶|撑|倚|贴|靠|搭|按|抵)"
SIZES = ["大特写", "中近景", "中全景", "特写", "近景", "中景", "全景", "远景"]


def _size(img: str) -> str | None:
    head = img[:16]
    for s in SIZES:            # 长词在前（中近景先于近景）
        if s in head:
            return s
    return None


def check_shot(img: str, cast: list[tuple[str, str]]) -> dict:
    """img = 首帧原文；cast = [(名字, 在画 | 局部 | 画外)] → {ok, no_contact, frontal, tight_pair, size}"""
    clauses = [c for c in re.split(r"[，。；,;]", img or "") if c.strip()]
    on = [n for n, p in cast if p == "在画"]
    no_contact, frontal = [], []
    for n in on:
        mine = [c for c in clauses if n in c]
        if not any(CONTACT.search(c) for c in mine):
            no_contact.append(n)
        if any(UPRIGHT.search(c) and FRONTAL.search(c) for c in mine):
            frontal.append(n)
    size = _size(img or "")
    # 11-05 PS-MASTER（L-192 过肩 coverage）：前景只露肩 / 后脑 / 背影的人不算“露脸”——按小句主语延续归属（无人名小句沿用上一句主语），
    # 与编译层 ns_schema.prompt_v2.hidden_face 同一口径；否则过肩中近景（K-WRT-816 要求 85mm）永远被 H16 挡
    faces = [n for n in on if not _face_hidden(n, clauses, [x for x, _p in cast])]
    tight_pair = len(faces) >= 2 and size in TIGHT
    # 插断的分句（FACTCHECK 11-02 发现：补丁把“<名>的手 / 肩 + 接触”插进了另一句中间，如“视线落在林晚的左手扶着矮柜边缘”“停在林晚的后背贴在砖墙上”）
    names = [n for n, _p in cast]
    spliced = [c.strip()[:40] for c in clauses for a in names for b in names
               if a != b and re.search(re.escape(a) + r"[^，；。]{1,14}?" + re.escape(b) + SPLICE_PART, c)]
    return {"ok": not no_contact and not frontal and not tight_pair and not spliced, "no_contact": no_contact, "frontal": frontal,
            "tight_pair": faces if tight_pair else [], "size": size, "spliced": sorted(set(spliced))}


def _face_hidden(name: str, clauses: list[str], names: list[str]) -> bool:
    """这个人的小句（含其后无人名的延续小句）里写了 背对镜头 / 背影 / 只露… / 以…入画 / 被…遮 → 不露脸"""
    try:
        from ns_schema.prompt_v2 import hidden_face
    except Exception:                                     # arch-ok: 编译层不可用时按旧口径（算露脸），不放宽
        return False
    try:
        from ns_agent.asset_refs import clause_subjects
    except Exception:                                     # arch-ok: 取不到就退回“最靠前的人名”
        clause_subjects = None
    mine, cur = [], ()
    for c in clauses:
        hit = [n for n in names if n in c]
        if hit:
            # REVIEW-B 11-05：主语 = 小句里最靠前的人名（“卓琳蹲在祁念左前”主语是卓琳，不按 cast 顺序）；并列主语“X和Y背对镜头”两人都是主语（与 asset_refs.clause_subjects 同口径）
            cur = (clause_subjects(c, names, cur) if clause_subjects else ()) or (min(hit, key=c.find),)
        if name in cur:
            mine.append(c)
    return bool(mine) and hidden_face("，".join(mine))[0]


def staging_rows(text: str, ep_no: int | None = None) -> list[dict]:
    """text = 带前言的剧本稿（一集或多集）→ 每镜 {episode, shot, ok, no_contact, frontal, tight_pair, size}"""
    from ns_agent.importer.script_md import import_script
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "cand.md"
        f.write_text(text, encoding="utf-8")
        si = import_script(f)
    rows = []
    for e in si.episodes:
        if ep_no is not None and e.number != ep_no:
            continue
        for sh in sorted(e.shots, key=lambda s: s.index):
            cast = [(c.name, c.presence or ("在画" if getattr(c, "visible", True) else "画外")) for c in (sh.cast or [])]
            rows.append({"episode": e.number, "shot": sh.index, **check_shot(sh.img_prompt or "", cast)})
    return rows


def why(row: dict) -> str:
    parts = []
    if row["no_contact"]:
        parts.append(f"{'、'.join(row['no_contact'])} 在画但 img 里没有和场景物件的接触动作（K-WRT-H15）——给每个在画人物写一个分句："
                     "人名主语 + 接触动作 + 场景里的物件（扶着门框 / 坐在桌沿 / 拿着杯子 / 靠在墙上），身体写侧向")
    if row["frontal"]:
        parts.append(f"{'、'.join(row['frontal'])} 写成了正面直立对镜头（设定图姿势，K-WRT-H15）——改成侧身 / 坐 / 倚靠，视线落在画里的人或物上")
    if row.get("spliced"):
        parts.append(f"接触分句插断了别的句子：{row['spliced']}（K-WRT-H15）——接触分句单独成句，以人名开头放在逗号之间，原句（视线落点 / 走位）补完整")
    if row["tight_pair"]:
        parts.append(f"{row['size']}里 {'、'.join(row['tight_pair'])} 两人都露脸（K-WRT-H16）——改成中景以上，或把其中一人写成前景“局部”（肩 / 背影 / 手）")
    return "；".join(parts)


def season_dist(paths: list[Path]) -> dict:
    """多份稿 → 分布（每集、整季）"""
    from ns_api import script_chat as SC
    header, _ = SC.script_header(registry={}, run=SC.run_for_dir(paths[0]) if paths else None)
    per, tot = {}, {"shots": 0, "ok": 0, "no_contact": 0, "frontal": 0, "tight_pair": 0}
    for p in paths:
        t = p.read_text(encoding="utf-8")
        m = re.search(r"ep(\d+)", p.name)
        ep = int(m.group(1)) if m else None
        text = t if t.lstrip().startswith("<!--") or "**全剧人物表**" in t else header + "\n---\n\n" + t[t.find("## ep"):]
        rows = staging_rows(text, ep)
        d = {"shots": len(rows), "ok": sum(r["ok"] for r in rows), "no_contact": sum(bool(r["no_contact"]) for r in rows),
             "frontal": sum(bool(r["frontal"]) for r in rows), "tight_pair": sum(bool(r["tight_pair"]) for r in rows),
             "bad_shots": [r["shot"] for r in rows if not r["ok"]]}
        per[p.name] = d
        for k in tot:
            tot[k] += d[k]
    tot["ok_rate"] = round(tot["ok"] / tot["shots"], 3) if tot["shots"] else None
    return {"total": tot, "episodes": per}


def supplement(paths: list[Path]) -> list[dict]:
    """已拍季（第一季）不返修剧本：给 H15 不达标的镜列出“编译层补充”候选——缺接触的在画人物 + 本镜场景的固定陈设（场景表原文），
    交编译层负责方（ns_agent，IMGFIX）在首帧编译时补一句“<人名>的手扶着 / 靠着 <陈设>”；已定稿（已过闸 / 已批）的镜由编译层按生产状态跳过"""
    from ns_api import script_chat as SC
    from ns_agent.importer.script_md import import_script
    header, _ = SC.script_header(registry={}, run=SC.run_for_dir(paths[0]) if paths else None)
    out = []
    for p in paths:
        t = p.read_text(encoding="utf-8")
        m = re.search(r"ep(\d+)", p.name)
        ep = int(m.group(1)) if m else None
        text = header + "\n---\n\n" + t[t.find("## ep"):]
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "cand.md"
            f.write_text(text, encoding="utf-8")
            si = import_script(f)
        lib = {x.scene_id: x for x in (si.globals.scene_library or [])} if getattr(si.globals, "scene_library", None) else {}
        for e in si.episodes:
            if ep is not None and e.number != ep:
                continue
            for sh in sorted(e.shots, key=lambda q: q.index):
                cast = [(c.name, c.presence or "在画") for c in (sh.cast or [])]
                r = check_shot(sh.img_prompt or "", cast)
                if r["ok"]:
                    continue
                sc = lib.get(sh.scene_id)
                out.append({"shot": f"ep{e.number:02d}-S{sh.index}", "no_contact": r["no_contact"], "tight_pair": r["tight_pair"],
                            "size": r["size"], "scene_id": sh.scene_id, "fixtures": getattr(sc, "fixtures", None) if sc else None,
                            "scene_detail": sh.scene_detail})
    return out


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sys.path[:0] = [str(ROOT / "services" / "api")]
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dist", help="分布：给一组稿（glob，相对仓库根）算 H15 / H16 达标率")
    d.add_argument("--glob", action="append", required=True)
    d.add_argument("--out", default="")
    sp = sub.add_parser("supplement", help="已拍季：H15 / H16 不达标镜的编译层补充候选（不改剧本）")
    sp.add_argument("--glob", action="append", required=True)
    sp.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    paths = sorted({p for g in a.glob for p in ROOT.glob(g)})
    if a.cmd == "supplement":
        rows = supplement(paths)
        op = ROOT / a.out
        op.parent.mkdir(parents=True, exist_ok=True)
        tmp = op.with_suffix(op.suffix + ".tmp")
        tmp.write_text(json.dumps({"rule": "K-WRT-H15/H16", "shots": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(op)
        print(json.dumps({"shots": len(rows), "no_contact": sum(bool(r["no_contact"]) for r in rows),
                          "tight_pair": sum(bool(r["tight_pair"]) for r in rows), "out": a.out}, ensure_ascii=False))
        return 0
    res = season_dist(paths)
    if a.out:
        op = ROOT / a.out
        op.parent.mkdir(parents=True, exist_ok=True)
        tmp = op.with_suffix(op.suffix + ".tmp")
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(op)
    print(json.dumps(res["total"], ensure_ascii=False))
    for k, v in res["episodes"].items():
        print(f"  {k}: {v['ok']}/{v['shots']} 达标；无接触 {v['no_contact']}，正面直立 {v['frontal']}，双人紧景别 {v['tight_pair']}；不达标镜 {v['bad_shots']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
