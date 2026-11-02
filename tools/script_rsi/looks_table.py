"""P1 造型表（V2 任务书 docs/v2/SCRIPT_BRIEF.md 第 1 步；硬约束：每个出场角色只用 2–3 套固定造型，按编号引用，跨集不另起新造型）。

格式（与 series10_v1 P1_looks.json 同构）：
[{"name": "林晚", "char_id": "lin_wan", "marker": "<固定标志物>",
  "looks": [{"id": "A", "use": "<场合>：ep01、ep02…", "zh": "服装=…｜鞋=…｜饰品=…", "en": "<英文服装短语>"}, …]}, …]
check：人物齐（storyline 人物表里每个人都有）、每人 2–3 套、zh 三槽齐、en 非空且不含否定词 / 人名、use 写了集号且在 1–10 内、
storyline 里每集出场的人至少有一套造型的 use 覆盖这一集。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEG = re.compile(r"\b(no|not|never|without)\b", re.I)


def check(looks, storyline: dict | None = None, ep_range=(1, 10)) -> list[str]:
    probs = []
    if not isinstance(looks, list) or not looks:
        return ["造型表不是非空列表"]
    names = {str(c.get("name")): c for c in looks if isinstance(c, dict)}
    chars = [c.get("name") for c in (storyline or {}).get("characters") or []]
    for n in chars:
        if n not in names:
            probs.append(f"{n} 没有造型")
    for n, c in names.items():
        lk = c.get("looks") or []
        if c.get("char_id") != "lead_f" and not 2 <= len(lk) <= 3:
            probs.append(f"{n}：造型 {len(lk)} 套（要 2–3 套）")
        if not str(c.get("marker") or "").strip():
            probs.append(f"{n}：缺标志物 marker")
        ids = [str(x.get("id")) for x in lk]
        if len(set(ids)) != len(ids):
            probs.append(f"{n}：造型编号重复 {ids}")
        for x in lk:
            tag = f"{n} {x.get('id')}"
            zh = str(x.get("zh") or "")
            miss = [k for k in ("服装=", "鞋=", "饰品=") if k not in zh]
            if miss:
                probs.append(f"{tag}：zh 缺 {'、'.join(m.rstrip('=') for m in miss)}")
            en = str(x.get("en") or "")
            if not en.strip():
                probs.append(f"{tag}：缺 en")
            elif NEG.search(en) or any(m in en for m in names):
                probs.append(f"{tag}：en 不能写否定词或人名")
            eps = [int(e) for e in re.findall(r"ep(\d+)", str(x.get("use") or ""))]
            if not eps:
                probs.append(f"{tag}：use 没写集号（epNN）")
            elif any(not ep_range[0] <= e <= ep_range[1] for e in eps):
                probs.append(f"{tag}：use 集号超出 {ep_range}")
    probs += lead_f_check(names.get(next((n for n, c in names.items() if c.get("char_id") == "lead_f"), ""), {}), storyline)
    for e in (storyline or {}).get("episodes") or []:
        ep = int(e.get("episode"))
        for n in e.get("characters") or []:
            c = names.get(n)
            if c and not any(ep in [int(v) for v in re.findall(r"ep(\d+)", str(x.get("use") or ""))] for x in c.get("looks") or []):
                probs.append(f"ep{ep:02d} {n} 出场，但没有哪套造型的 use 写到这一集")
    return probs


def lead_manifest(root: Path | None = None) -> tuple:
    """OVERSIGHT-F P2（总调度 19:4x）：lead_f 的造型集合 / 成人造型 / 鞋只有一个来源 = assets_v2/manifest.json（不在代码里写死）。
    → (全部造型 id, 成人造型 id, 日常造型 id, 鞋 id)；清单读不到 → 全空（每一套都会被判不合法 = 失败关闭）"""
    try:
        m = json.loads(((root or ROOT) / "assets_v2" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 清单读不出 = 没有合法造型（失败关闭）
        return (), (), (), ()
    c = (m.get("characters") or {}).get("lead_f") or {}
    looks = c.get("looks") or {}
    adult = tuple(sorted(k for k, v in looks.items() if (v or {}).get("adult")))
    daily = tuple(sorted(k for k in looks if k not in adult))
    shoes = tuple(sorted(k for k, v in (c.get("items") or {}).items() if (v or {}).get("slot") == "shoes"))
    return tuple(sorted(looks)), adult, daily, shoes


def lead_f_check(c: dict, storyline: dict | None) -> list[str]:
    """V2 女主（char_id=lead_f）：造型只许 O1–O4；schedule 逐集写 {episode, outfit, shoes}，outfit ∈ O1–O4、shoes ∈ SH1 / SH2；
    非亲密集只能 O1 / O4（schedule 里写 intimate_outfit 的才可以 O2 / O3，且该集 storyline intimate=true）"""
    if not c:
        return []
    probs = []
    LEAD_LOOKS, LEAD_ADULT, LEAD_DAILY, LEAD_SHOES = lead_manifest()
    ids = [str(x.get("id")) for x in c.get("looks") or []]
    bad = [i for i in ids if i not in LEAD_LOOKS]
    if bad:
        probs.append(f"lead_f 造型只许 O1–O4，出现了 {bad}")
    intimate = {int(e.get("episode")): bool(e.get("intimate")) for e in (storyline or {}).get("episodes") or []}
    sched = c.get("schedule") or []
    if storyline and not sched:
        probs.append("lead_f 缺 schedule（逐集写穿哪套、配哪双鞋）")
    for row in sched:
        ep, o, sh = int(row.get("episode") or 0), str(row.get("outfit") or ""), str(row.get("shoes") or "")
        if o not in set(LEAD_DAILY) | {"+".join(LEAD_DAILY)}:
            probs.append(f"lead_f ep{ep:02d} 日常造型只能是 O1 / O4（或 O4 外罩 O1 写 O1+O4），写了 {o}")
        if sh not in LEAD_SHOES:
            probs.append(f"lead_f ep{ep:02d} 鞋只能是 SH1 / SH2，写了 {sh}")
        io = row.get("intimate_outfit")
        if io:
            if io not in LEAD_ADULT:
                probs.append(f"lead_f ep{ep:02d} intimate_outfit 只能是 O2 / O3，写了 {io}")
            if storyline and not intimate.get(ep):
                probs.append(f"lead_f ep{ep:02d} 写了亲密造型 {io}，但这一集 storyline 没标 intimate=true")
    if storyline:
        lead_name = c.get("name")
        need = {int(e["episode"]) for e in storyline.get("episodes") or [] if lead_name in (e.get("characters") or [])}
        have = {int(r.get("episode") or 0) for r in sched}
        if need - have:
            probs.append(f"lead_f 出场但 schedule 没写的集：{sorted(need - have)}")
    return probs


SYSTEM = ("你是这部剧的编剧。这份任务只写造型表（和 P1 故事线配套）。只输出一个 ```json（列表）。"
          "全部人物成年（≥22 岁）、人物虚构；写法不露骨。")


def parse(text: str):
    """回稿 → 造型表（列表）。先取 ```json 代码块，否则整段；hollywood._json_block 只认 {…} 对象，列表会被截坏（11-02 走查发现）"""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = (m.group(1) if m else text).strip()
    try:
        return json.loads(body), ""
    except ValueError as e:
        return None, f"造型表不是合法 JSON：{e}"


def owner_items(root: Path) -> list[dict]:
    """项目方给的 V2 资产（assets_v2/owner_inputs.json items）；没有这个文件 = []"""
    p = root / "assets_v2" / "owner_inputs.json"
    return json.loads(p.read_text(encoding="utf-8")).get("items") or [] if p.exists() else []


def _iid(it: dict) -> str:
    return str(it.get("outfit_id") or it.get("item_id") or it.get("id") or "")


def closed_check(looks, root: Path) -> list[str]:
    """looks_closed（总调度 11-02）：lead_f 的造型编号只认项目方清单里的 O*；清单为空时不判"""
    allowed = {_iid(i) for i in owner_items(root) if i.get("kind") == "outfit"}
    if not allowed:
        return []
    lead = next((c for c in looks if isinstance(c, dict) and c.get("char_id") == "lead_f"), None) if isinstance(looks, list) else None
    if lead is None:
        return ["造型表里没有 lead_f（女主）"]
    bad = [str(x.get("id")) for x in lead.get("looks") or [] if str(x.get("id")) not in allowed]
    miss = sorted(allowed - {str(x.get("id")) for x in lead.get("looks") or []})
    out = [f"lead_f 出现了清单外的造型 {bad}（只认 {sorted(allowed)}）"] if bad else []
    if miss:
        out.append(f"lead_f 少了清单里的造型 {miss}")
    return out


def packet_user(storyline: dict, root: Path) -> str:
    """造型表写作请求（链里的 P1-looks 步）：故事线人物 + 项目方资产清单 + 格式"""
    items = owner_items(root)
    lines = [f"  {_iid(i) or i.get('kind')}：{i.get('name') or ''}（{i.get('file')}）" for i in items]
    chars = "、".join(f"{c.get('name')}（{c.get('char_id')}）" for c in storyline.get("characters") or [])
    lead = {"name": "<女主显示名>", "char_id": "lead_f", "marker": "<看脸图写一个固定可见特征>",
            "looks": [{"id": "O1", "use": "<场合>：epNN…", "zh": "服装=<照项目方造型名>｜鞋=SH1 或 SH2｜饰品=<无，或只在亲密镜：J1 / J2>", "en": "<英文服装短语>"}],
            "schedule": [{"episode": 1, "outfit": "O1 | O4 | O1+O4", "shoes": "SH1 | SH2", "intimate_outfit": "（只在 intimate=true 的集可写 O2 / O3，没有就省略）"}]}
    other = {"name": "<中文名>", "char_id": "ch_<小写英文>", "marker": "<固定可见标志物>",
             "looks": [{"id": "A", "use": "<场合>：ep01、ep02", "zh": "服装=…｜鞋=…｜饰品=…", "en": "<英文服装短语>"}]}
    return "\n".join([
        "【任务】给故事线里的每个人物写造型表：" + chars + "。",
        "1) 女主 lead_f：造型只用项目方清单里的编号（looks_closed，不许增减、不许改名）；非亲密镜只能穿 O1 / O4（或 O4 外罩 O1，写 O1+O4）；"
        "O2 / O3 只能在 storyline 标 intimate=true 的集作为 intimate_outfit；鞋只有 SH1 / SH2；J1 / J2 只在亲密镜。schedule 逐集写清她穿哪套、配哪双鞋。",
        "项目方资产清单（assets_v2/owner_inputs.json）：", *lines,
        "2) 其他人物：每人 2–3 套固定造型（服装 / 鞋 / 饰品 / EN，以及用在哪几集）。",
        "格式：", json.dumps([lead, other], ensure_ascii=False, indent=1),
    ])


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--looks", required=True)
    ap.add_argument("--storyline", default="")
    a = ap.parse_args(argv)
    lp = Path(a.looks) if Path(a.looks).is_absolute() else ROOT / a.looks
    raw = lp.read_text(encoding="utf-8")
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    looks = json.loads(m.group(1) if m else raw)
    sl = None
    if a.storyline:
        sp = Path(a.storyline) if Path(a.storyline).is_absolute() else ROOT / a.storyline
        t = sp.read_text(encoding="utf-8")
        m2 = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
        sl = json.loads(m2.group(1) if m2 else t)
    probs = check(looks, sl)
    print(json.dumps({"ok": not probs, "problems": probs}, ensure_ascii=False, indent=1))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
