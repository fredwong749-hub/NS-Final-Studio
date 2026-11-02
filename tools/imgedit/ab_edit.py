"""图像编辑 A/B 第 1 轮（docs/research/imgedit/AB_PLAN_R1.md；执行 ASSETUX，19:10 之后借 gpu36:1 开跑）。

scope = ab：产物只写 data/ab/imgedit/r1/<项>/，不写 takes.json、不写契约账本、不走生产作业、不设当前版本。图片不外发（改写只发文字，经 text_only_guard）。
本文件分步（每步只做一件事，可单独重跑）：
  step0-samples   固定样本 → data/ab/imgedit/r1/samples.json（P 林晚单人 6 / D 双人 2 / S 场景底图 2；只用非成人单镜、首帧当前版且 Q1 pass）
  step0-prompts   把测试用的中文编辑意图各改写一次 → data/ab/imgedit/r1/prompts.json（冻结；之后所有臂共用这份文字）
  （后续：A/B-1、2、3、12 的出图与打分，借道成功后再加，见方案 §2–§5）
  .venv/Scripts/python.exe tools/imgedit/ab_edit.py step0-samples
  .venv/Scripts/python.exe tools/imgedit/ab_edit.py step0-prompts
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/api", "services/agent", "packages/schema", "services/render_router", "tools/pipeline", "tools/autopilot", "tools/imglab", "."):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

OUT = ROOT / "data" / "ab" / "imgedit" / "r1"
SIZE_WORDS = [("特写", "close"), ("近景", "close"), ("中景", "mid"), ("全身", "full"), ("全景", "full")]
# 测试用的编辑指令（技术用例，不属于剧本内容）：代号 → (中文意图, 用于)
INTENTS = {
    "e1": ("把鞋换成黑色漆皮细高跟", "P 全身、中景"),
    "e2": ("光线改成从画面左侧来的柔和窗光", "P、S"),
    "e3": ("背景换成夜晚的城市街道，人物不变", "P、D"),
    "e4": ("表情改成淡淡的微笑", "P 特写、中景"),
    "e5": ("桌上加一束白色郁金香", "S"),
    "e0": ("保持画面完全不变", "P、S（只用于 A/B-12 测纯漂移）"),
}
# 选区（0–1 相对坐标，x y w h），第 0 步按样本填；整张 = None。这里只记哪些意图需要框
BOXED = {"e1": "鞋", "e4": "脸", "e5": "桌面"}


def _wjson(p: Path, obj) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _size_of(prompt: str) -> str | None:
    head = (prompt or "")[:40]
    for w, k in SIZE_WORDS:
        if w in head:
            return k
    return None


def _q1_pass(t: dict) -> bool:
    items = (t.get("postflight") or {}).get("items") or []
    q1 = next((i for i in items if i.get("id") == "Q1"), None)
    return bool(q1 and str(q1.get("status")).lower() == "pass")


def _candidates(ep_min: int = 1, ep_max: int = 3) -> list[dict]:
    from ns_api import takes_ui as TU
    from ns_agent import asset_refs as AR
    doc = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    out = []
    for ep in doc.get("episodes") or []:
        n = int(ep.get("number") or 0)
        if not ep_min <= n <= ep_max:
            continue
        for sh in ep.get("shots") or []:
            sid = f"ep{n:02d}-S{int(sh.get('index') or 0)}"
            if sh.get("adult"):
                continue
            cast = [AR.NAME_ID.get(nm, nm) for nm, _pr in AR.cast_on_screen(sh)]
            tj = ROOT / "data" / "renders" / f"ep{n:02d}" / f"S{int(sh.get('index'))}" / "takes.json"
            try:
                data = json.loads(tj.read_text(encoding="utf-8"))
            except (OSError, ValueError):   # arch-ok: 这一镜还没有出图记录 = 不进样本池，其余镜照常
                continue
            a = (data.get("active") or {}).get("image")
            t = next((x for x in data.get("takes") or [] if x.get("stage") == "image" and x.get("n") == a), None)
            if not t or t.get("quarantined") or not TU._verdict(t, None)[0] or not _q1_pass(t):
                continue
            if not (ROOT / "data" / t["file"]).is_file():
                continue
            out.append({"shot": sid, "ep": n, "cast": cast, "size": _size_of(sh.get("img_prompt") or ""), "file": "data/" + t["file"], "take": a})
    return out


def step0_samples() -> dict:
    from ab import is_adult      # tools/imglab/ab.py 同口径（编译器判成人）
    pool = [c for c in _candidates() if not is_adult(c["shot"])]
    single = [c for c in pool if c["cast"] == ["lin_wan"]]
    pick, used = [], set()
    for size, k in (("close", 2), ("mid", 2), ("full", 2)):
        got = [c for c in single if c["size"] == size and c["shot"] not in used][:k]
        pick += got
        used |= {c["shot"] for c in got}
    for c in single:                       # 某个景别凑不够 2 张：用别的景别补足 6 张，样本里如实标出
        if len(pick) >= 6:
            break
        if c["shot"] not in used:
            pick.append(c)
            used.add(c["shot"])
    # 总调度 17:2x：e1（换鞋）要全身样本。ep01–03 没有 Q1 通过的全身镜 → 从 ep04 以后补 2 张（条件不变：非成人、Q1 通过、当前版）；
    # 找不到合格的就用林晚造型 A 设定图（sleevefix 版）当全身样本，顺带测“资产修改”这条路径
    full = [c for c in _candidates(4, 99) if c["cast"] == ["lin_wan"] and c["size"] == "full" and not is_adult(c["shot"])][:2]
    sheet = "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202_sleevefix.png"
    if not full:      # 总调度同意：设定图只当 1 个全身样本（2 个 seed 在出图时跑）；版式是四栏设定图，e1 单独统计，不和镜头样本混比（stats_group = sheet）
        full.append({"shot": None, "asset": "lin_wan 造型 A 设定图", "size": "full", "cast": ["lin_wan"], "file": sheet, "stats_group": "sheet", "look": "A"})
    duo = [c for c in pool if "lin_wan" in c["cast"] and len(c["cast"]) == 2][:2]
    scenes = []
    for d in sorted((ROOT / "assets" / "scenes").glob("sk_*"))[:6]:
        img = d / "plate.png" if (d / "plate.png").is_file() else next((f for f in sorted(d.glob("*")) if f.suffix.lower() in (".png", ".jpg", ".jpeg") and f.is_file()), None)
        if img:
            scenes.append({"scene": d.name, "file": img.relative_to(ROOT).as_posix()})
    res = {"P": pick[:6], "F": full, "D": duo, "S": scenes[:2], "note": {"F_from_shots": sum(1 for c in full if c.get("shot")), "P_short": 6 - len(pick[:6]), "D_short": 2 - len(duo), "S_short": 2 - len(scenes[:2])}}
    OUT.mkdir(parents=True, exist_ok=True)
    _wjson(OUT / "samples.json", res)
    return res


def step0_prompts() -> dict:
    """把测试用的中文意图各改写一次（写作 API，只发文字）；E-3 的 V-B 变体用临时系统提示词，在 A/B-3 里单独做"""
    from ns_api import prompt_rewrite as PR
    res = {}
    for code, (zh, used) in INTENTS.items():
        r = PR.rewrite("edit_mask" if code in BOXED else "shot_frame", zh, {"name": "林晚", "shot": "测试", "stage": "首帧"})
        res[code] = {"zh": zh, "for": used, "prompt": r["prompt"], "negative_add": r.get("negative_add") or "", "zh_summary": r.get("zh_summary"), "model": r.get("model")}
    # 设定图样本的 e1：用 sheet 的系统提示词改写（里面有“设定图版式不变”那一条）；单独存，不和镜头样本的 e1 混
    r = PR.rewrite("sheet", INTENTS["e1"][0], {"name": "林晚", "look": "A", "use": "设定图"})
    res["e1_sheet"] = {"zh": INTENTS["e1"][0], "for": "F 设定图（单独统计）", "prompt": r["prompt"], "negative_add": r.get("negative_add") or "",
                       "zh_summary": r.get("zh_summary"), "model": r.get("model"), "stats_group": "sheet"}
    OUT.mkdir(parents=True, exist_ok=True)
    _wjson(OUT / "prompts.json", res)
    return res


def main(argv: list[str] | None = None) -> int:
    a = (argv if argv is not None else sys.argv[1:]) or ["-h"]
    if a[0] == "step0-samples":
        r = step0_samples()
        print({k: len(v) for k, v in r.items() if k != "note"}, r["note"], [c.get("shot") or c.get("asset") for c in r["F"]])
        return 0
    if a[0] == "step0-prompts":
        r = step0_prompts()
        for k, v in r.items():
            print(k, v["zh_summary"])
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
