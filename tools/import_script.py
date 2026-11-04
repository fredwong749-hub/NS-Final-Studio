"""
导入剧本：python tools/import_script.py  →  data/import/script_v2.json

默认读取 script play lib 下的《剧本和镜头》v2 和《image提示词》v2。
"""
import argparse
import sys
from pathlib import Path

from ns_agent.compiler import classify_adult
from ns_agent.importer.script_md import import_script
from ns_agent.state_timeline import VERSION_IN_NAME

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "script play lib"


def merge_into(base_path: Path, new, single_source: bool = False):
    """把新稿的集按集号替换进底稿（ScriptImport）；底稿其余集原样保留。
    全局头（角色锁 / 触发词 / 后缀等）用新稿的（新稿带完整全局头时）；来源列表合并；“缺少集数”类警告去掉。
    single_source=True（非 V1 剧，ISS-1103-044539-f93d）：全局头只用新稿的，见 merge_globals"""
    from ns_schema.script import ScriptImport
    base = ScriptImport.model_validate_json(base_path.read_text(encoding="utf-8"))
    new_eps = {e.number: e for e in new.episodes}
    episodes = [new_eps.pop(e.number, e) for e in base.episodes] + sorted(new_eps.values(), key=lambda e: e.number)
    replaced = sorted(new_eps_all := {e.number for e in new.episodes})
    g = merge_globals(base.globals, new.globals, new_eps_all, single_source=single_source)
    # 封板修复：只去掉“缺少集数”里与本次替换无关的那类；新稿里同一集号重复要提示
    warnings = [w for w in new.warnings if not w.startswith("缺少集数")]
    if len(new.episodes) != len(new_eps_all):
        warnings.append(f"新稿里有重复的集号：{sorted(n for n in new_eps_all if sum(e.number == n for e in new.episodes) > 1)}，只保留最后一个")
    warnings.append(f"合并导入：以 {base_path.name} 为底，替换集 {replaced}，其余 {len(episodes) - len(replaced)} 集保持不变")
    warnings += registry_drift(base.globals, new.globals, new_eps_all, single_source=single_source)
    # 封板修复 P1：被替换的集从旧来源的 episodes 里删掉，按集取版本不会命中旧条目
    old = [s.model_copy(update={"episodes": [n for n in s.episodes if n not in new_eps_all]}) for s in base.sources]
    return ScriptImport(sources=dedupe_sources([*old, *new.sources]), globals=g, episodes=episodes,
                        warnings=warnings)


REGISTRY_FIELDS = {"character_registry": (lambda e: e.name, {"zh": "中文外貌句", "en": "EN外貌短语", "voice": "VOICE声线短语"}),
                   "scene_library": (lambda e: e.scene_id, {"name": "名称", "space": "空间描述", "time_of_day": "时段",
                                                            "light": "光线", "fixtures": "固定陈设"})}


def base_registered(o, replaced) -> bool:
    """底稿登记是否仍有效（先登记为准）：在全剧表登记过（defined_in 含 None），或定义它的集里还有没被这次替换的"""
    d = getattr(o, "defined_in", None) or []
    return not d or None in d or any(n not in replaced for n in d)


def registry_drift(base_g, new_g, replaced: set[int], single_source: bool = False) -> list[str]:
    """fredw-92/D2：新稿把底稿已登记的人物 / 场景改写了（EN / VOICE / 场景格不同）时提示“登记冲突”。
    fredw-92 2026-10-31 定：冲突时保留先登记的（底稿），不覆盖（merge_globals）；新稿这几集逐字引用的新文字会对不上，要按底稿返修"""
    out = []
    for attr, (key, fields) in REGISTRY_FIELDS.items():
        old = {key(e): e for e in getattr(base_g, attr, None) or []}
        for e in getattr(new_g, attr, None) or []:
            o = old.get(key(e))
            if o is None:
                continue
            diff = [label for f, label in fields.items() if getattr(o, f, "") and getattr(e, f, "") != getattr(o, f, "")]
            if diff and single_source and attr == "scene_library" and None in (getattr(e, "defined_in", None) or []):
                out.append(f"场景表更新：{key(e)} 的 {'、'.join(diff)} 以新稿全剧场景表为准，覆盖旧定义（L-188，非 V1 剧）")
            elif diff and base_registered(o, replaced):
                where = "、".join("全剧表" if n is None else f"ep{n:02d}" for n in (getattr(o, "defined_in", None) or []))
                out.append(f"登记冲突：{key(e)} 的 {'、'.join(diff)} 与先登记的（{where or '底稿'}）不同，保留先登记的、不覆盖；"
                           f"新稿第 {sorted(replaced)} 集里逐字引用的新文字会对不上，请按先登记的返修")
    return out


def merge_globals(base, new, replaced: set[int] | frozenset = frozenset(), single_source: bool = False):
    """封板修复 P0：逐字段合并全局头——新稿非空才覆盖（单集稿常没有角色锁 / 后缀 / 基础负面，旧逻辑会整份清空）；
    触发词按 trigger 合并（新稿优先）；装饰自查表按集覆盖。
    人物表 / 场景表（fredw-92 2026-10-31 定：全剧一份、逐集继承）：先登记的为准——底稿登记仍有效（base_registered）就保留，
    只有定义它的集全部被这次替换时才用新稿的；新角色 / 新场景追加。
    single_source=True（MERGE-OPS-O，ISS-1103-044539-f93d：非 V1 剧重导时底稿 motion_suffix / image_suffix 的“徕卡”原样回流）：
    后缀 / 基础负面 / 装饰区间 / 日常穿搭 / 角色锁 / 基准图 / 触发词只取新稿（= 当前集头），底稿旧值不回流；
    人物表 / 场景表照旧逐集继承（别的集的登记还要用），之后由 scope_globals 只留本剧登记，再过 v1_gate"""
    def by_key(attr, key):   # 列表按键合并，新稿优先；底稿顺序在前
        d = {key(x): x for x in getattr(base, attr)}
        d.update({key(x): x for x in getattr(new, attr)})
        return list(d.values())

    def registry(attr, key):   # 先登记为准
        d = {key(x): x for x in getattr(base, attr)}
        for x in getattr(new, attr):
            o = d.get(key(x))
            if o is None or not base_registered(o, replaced):
                d[key(x)] = x
            elif single_source and attr == "scene_library" and None in (x.defined_in or []):
                # L-188：非 V1 剧（单一来源）重导时，新稿全剧场景表里的场景定义是最新口径——盖住旧定义（旧的光线句等不再回流），
                # 新稿空格沿用旧值，defined_in 取并集；V1 仍按“先登记为准”
                upd = {f: getattr(x, f) or getattr(o, f) for f in REGISTRY_FIELDS[attr][1] if f != "name"}
                upd["name"] = x.name or o.name
                upd["defined_in"] = list(dict.fromkeys([*(o.defined_in or []), *(x.defined_in or [])]))
                d[key(x)] = x.model_copy(update=upd)
        return list(d.values())
    pick = (lambda k: getattr(new, k)) if single_source else (lambda k: getattr(new, k) or getattr(base, k))   # noqa: E731
    if single_source:
        def by_key(attr, key):   # noqa: F811  单一来源：只用新稿
            return list(getattr(new, attr))
    return base.model_copy(update={
        **{k: pick(k) for k in ("motion_suffix", "image_suffix", "base_negative", "decor_schedule", "daily_outfit")},
        "character_locks": by_key("character_locks", lambda c: c.name),   # 单集稿只写一条角色锁时不丢其余角色
        "references": by_key("references", lambda r: r.id),
        "lora_triggers": by_key("lora_triggers", lambda t: t.trigger),
        "scene_library": registry("scene_library", lambda e: e.scene_id),   # S1：场景表按场景 id 合并（先登记为准）
        "character_registry": registry("character_registry", lambda e: e.name),   # R3：人物表按角色名合并（先登记为准）
        "decor_tables": dict(new.decor_tables) if single_source else {**base.decor_tables, **new.decor_tables}})


def _src_key(path: str) -> str:
    p = Path(path.replace("\\", "/"))
    if not p.is_absolute():
        p = ROOT / p
    return str(p.resolve()).replace("\\", "/").lower()


def dedupe_sources(sources: list) -> list:
    """同一路径只留最后（最新）一条——带 version / episodes 的那条；顺序按各路径最后出现的位置
    （封板修复：每次合并都整份追加，script_v2.json 里同一文件出现 3–4 次，按集取版本可能命中旧条目）。
    封板修复 P1/P2：相对 / 绝对路径按同一文件算；同一路径同版本先后导入不同集时，episodes 取并集；
    同一路径不同版本各留一条（不能整条丢掉旧版本，否则它认领的集会被算成新版本），旧条目去掉后面条目认领的集"""
    gk = lambda s: (_src_key(s.path), s.version)   # noqa: E731
    last = {gk(s): i for i, s in enumerate(sources)}
    kept = []
    for i, s in enumerate(sources):
        if last[gk(s)] != i:
            continue
        eps = {n for x in sources[:i] if gk(x) == gk(s) for n in x.episodes} | set(s.episodes)
        kept.append((s, eps))
    out = []
    for j, (s, eps) in enumerate(kept):
        later = {n for _, e in kept[j + 1:] for n in e}
        eps = sorted(eps - later)
        if not eps and any(_src_key(x.path) == _src_key(s.path) for x, _ in kept[j + 1:]):
            continue        # 同一文件有更新的条目、这条已不认领任何集 → 去掉
        out.append(s.model_copy(update={"episodes": eps}) if eps != list(s.episodes) else s)
    return out


AUTO_TRIGGERS = ROOT / "config" / "auto_lora_triggers.json"


def auto_triggers(result, cfg_path: Path = AUTO_TRIGGERS) -> int:
    """系统自动补角色 LoRA 触发词（config/auto_lora_triggers.json）：画面里出现该角色的镜头，img_triggers 补上触发词，
    并在 globals.lora_triggers 登记（编译器据此保留触发词、gpu3 据 LORA_REGISTRY 加载）。返回补了几处。"""
    import json
    from ns_agent.bible import load_bible
    from ns_agent.compiler import _strip_triggers, present_characters
    from ns_schema.script import LoraTrigger
    if not cfg_path.exists():
        return 0
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")).get("characters", {})
    b = load_bible()
    g = result.globals
    names = [c.name for c in g.character_locks] + [c.name for c in b.characters
                                                   if c.name not in {x.name for x in g.character_locks}]
    known = {t.trigger for t in g.lora_triggers}
    for spec in (x for lst in cfg.values() for x in lst):
        if spec["trigger"] not in known:
            st = spec.get("strength")
            g.lora_triggers.append(LoraTrigger(trigger=spec["trigger"], kind=spec.get("kind", "image"),
                                               description=spec.get("description", ""), file=spec.get("file"),
                                               strength=(st, st) if st is not None else None))
            known.add(spec["trigger"])
    added = 0
    for ep in result.episodes:
        for s in ep.shots:
            present = present_characters(s, _strip_triggers(s.img_prompt, s.img_triggers), names, b)
            for name in present:
                for spec in cfg.get(name, []):
                    if spec.get("kind", "image") == "image" and spec["trigger"] not in s.img_triggers:
                        s.img_triggers.append(spec["trigger"])
                        added += 1
    return added


def _runs():
    import sys as _s
    if str(ROOT) not in _s.path:
        _s.path.insert(0, str(ROOT))
    from tools.autopilot import runs as _RN    # OVERSIGHT-F P2：tools 侧 runs 唯一入口
    return _RN


def default_out() -> Path:
    """不给 -o = 当前剧（primary）的导入稿；legacy 剧 = 旧路径（K-OPS-F24）"""
    return _runs().script_path(None, ROOT)


def target_run(out: Path) -> str | None:
    """V2CUT-O（11-03，L-126）：输出路径是哪个非 V1 剧的导入稿（runs.import_path）→ 剧名；V1 / 临时输出 / 登记表读不出 → None"""
    try:
        RN = _runs()
        names = list((RN.registry(ROOT).get("runs") or {}))
    except Exception:  # noqa: BLE001  # arch-ok: 没有登记表（沙箱）= 不按剧收口
        return None
    o = Path(out).resolve()
    return next((r for r in names if not RN.is_legacy(r, ROOT) and RN.import_path(r, ROOT).resolve() == o), None)


def _jl(p: Path) -> dict:
    import json
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):  # arch-ok: 读不到 = 本剧没登记（场景 / 角色 / 触发词按空集收口，更严，不是放行）
        return {}


def run_registered(run: str) -> tuple[set[str], set[str]]:
    """本剧自己登记过的场景 id / 角色（中文名 + char_id）：只读本剧的 P1（data/pipeline/runs/<run>/P1_storyline.json）
    和本剧资产包清单（runs.asset_manifest）。绝不读 V1 的全局表 / V1 导入稿"""
    RN = _runs()
    p1 = _jl(RN.run_dir(run, ROOT) / "P1_storyline.json")
    scenes = {s["scene_id"] for s in p1.get("scenes") or [] if isinstance(s, dict) and s.get("scene_id")}
    chars = {v for c in p1.get("characters") or [] if isinstance(c, dict) for v in (c.get("name"), c.get("char_id")) if v}
    mp = RN.asset_manifest(run, ROOT)
    man = _jl(Path(mp)) if mp else {}
    scenes |= set((man.get("scenes") or {}))
    for cid, c in (man.get("characters") or {}).items():
        chars |= {cid} | ({c["display_name"]} if isinstance(c, dict) and c.get("display_name") else set())
    return scenes, chars


def scope_globals(result, scenes_ok: set[str], chars_ok: set[str]) -> list[str]:
    """非 V1 剧导入稿的全局登记只留本剧自己的（L-126 完全切割）：
    - 场景表 / 人物表：本剧某集“本集场景表 / 本集人物表”定义过的（defined_in 有集号），或本剧 P1 / 资产包清单登记过的；
      只在“全剧表”（全局头，defined_in 只有 None）出现、本剧又没登记的 = 别的剧带进来的，丢掉；
    - 角色锁 / 触发词 / 日常穿搭：属于被丢掉角色的（角色锁按名字；触发词、日常穿搭原文提到该角色名）一并丢掉。
    → 丢掉了什么（写进导入警告）"""
    g = result.globals
    own = lambda e: any(n is not None for n in (e.defined_in or []))          # noqa: E731
    keep_s = [e for e in g.scene_library if own(e) or e.scene_id in scenes_ok]
    keep_c = [e for e in g.character_registry if own(e) or e.name in chars_ok or (e.char_id and e.char_id in chars_ok)]
    drop_s = [e.scene_id for e in g.scene_library if e not in keep_s]
    drop_c = [e for e in g.character_registry if e not in keep_c]
    names = {e.name for e in drop_c}
    kept_names = {e.name for e in keep_c} | {x for x in chars_ok}
    locks = [c for c in g.character_locks if c.name in kept_names and c.name not in names]
    drop_l = [c.name for c in g.character_locks if c not in locks]
    names |= set(drop_l)
    trig = [t for t in g.lora_triggers if not any(n and n in t.description for n in names)]
    drop_t = [t.trigger for t in g.lora_triggers if t not in trig]
    daily = "" if any(n and n in g.daily_outfit for n in names) else g.daily_outfit
    g.scene_library, g.character_registry, g.character_locks, g.lora_triggers, g.daily_outfit = keep_s, keep_c, locks, trig, daily
    # 警告只记个数，不把别剧的 id / 名字写进本剧导入稿（V1 泄漏扫描也扫导入稿）；明细打到导入输出里
    out = []
    if drop_s:
        out.append(f"本剧没登记的场景 {len(drop_s)} 个不进导入稿（L-126，全局头带进来的别剧登记）")
    if drop_c or drop_l:
        out.append(f"本剧没登记的角色 {len({e.name for e in drop_c} | set(drop_l))} 个不进导入稿（L-126）")
    if drop_t:
        out.append(f"属于这些角色的触发词 {len(drop_t)} 个不进导入稿")
    if drop_s or drop_c or drop_l or drop_t:
        print(f"按剧收口丢掉：场景 {drop_s}；角色 {sorted({e.name for e in drop_c} | set(drop_l))}；触发词 {drop_t}")
    return out


def run_triggers(run: str) -> set[str]:
    """MERGE-OPS-O（ISS-1103-024206-9974，L-137）：本剧登记过的 LoRA 触发词。只认本剧自己的登记：
    runs.json 该剧条目 lora_triggers、本剧资产包清单 lora_triggers（字符串或 {trigger}）、
    config/auto_lora_triggers.json 里属于本剧登记角色的条目。剧本全局头里的“LoRA 触发词表”不算登记（V1 全局头会把 V1 道具词带进来）"""
    RN = _runs()
    out: set[str] = set()

    def add(xs):
        for x in xs or []:
            t = x.get("trigger") if isinstance(x, dict) else x
            if isinstance(t, str) and t:
                out.add(t)
    add(((RN.registry(ROOT).get("runs") or {}).get(run) or {}).get("lora_triggers"))
    mp = RN.asset_manifest(run, ROOT)
    add((_jl(Path(mp)) if mp else {}).get("lora_triggers"))
    _scenes, chars = run_registered(run)
    for name, es in ((_jl(AUTO_TRIGGERS).get("characters")) or {}).items():
        if name in chars:
            add(es if isinstance(es, list) else [es])
    return out


def scope_triggers(result, allowed: set[str]) -> list[str]:
    """非 V1 剧：globals.lora_triggers 只留本剧登记的触发词；每镜 img_triggers / motion_triggers 里没登记的一并去掉。→ 警告"""
    g = result.globals
    drop = sorted({t.trigger for t in g.lora_triggers if t.trigger not in allowed})
    g.lora_triggers = [t for t in g.lora_triggers if t.trigger in allowed]
    n_shot = 0
    for ep in result.episodes:
        for s in ep.shots:
            for attr in ("img_triggers", "motion_triggers"):
                cur = list(getattr(s, attr, None) or [])
                keep = [t for t in cur if t in allowed]
                if len(keep) != len(cur):
                    n_shot += len(cur) - len(keep)
                    setattr(s, attr, keep)
    if not drop and not n_shot:
        return []
    print(f"按剧收口丢掉未登记触发词：{drop}（镜头引用 {n_shot} 处）")
    return [f"本剧没登记的触发词 {len(drop)} 个不进导入稿（镜头引用 {n_shot} 处，L-126 / ISS-1103-024206-9974）"]


def v1_gate(result, run: str) -> str:
    """CLEAN_CUT“交稿须 v1_leak 0 命中”的导入执行点（ISS-1103-024206-9974）：整份导入稿（按剧收口之后、写盘之前）
    过 script_chat.assert_no_v1（词表 config/v1_guard.json，与写手包 / 成稿出口同一份）。命中 → 原因（拒绝导入）；没命中 / V1 → 空串。
    闸门自身出错 = 失败关闭"""
    try:
        from ns_api import script_chat as SC
    except Exception as e:  # noqa: BLE001  # arch-ok: 读不到闸门 = 不放行
        return f"v1_leak 闸门不可用：{type(e).__name__}: {e}"
    try:
        SC.assert_no_v1(result.model_dump_json(), run=run, what="导入稿")
    except SC.HeaderMissing as e:
        return str(e)
    except Exception as e:  # noqa: BLE001  # arch-ok: 闸门出错 = 不放行
        return f"v1_leak 闸门出错：{type(e).__name__}: {e}"
    return ""


OLD_DOC_DIR = "script play lib"      # 第一季（V1）剧本 / image 提示词文档所在目录


def old_doc_refs(out: Path, docs: list) -> list[str]:
    """A-08：输出不是 legacy 剧（V1）的导入稿，却引用了第一季文档目录里的文件 → 列出来（拒绝导入，V2 完全切割 L-126）"""
    try:
        legacy_out = _runs().script_path(_runs().legacy_run(ROOT), ROOT).resolve()
    except Exception:  # noqa: BLE001  # arch-ok: 登记表读不出 = 按非 legacy 处理（更严）
        legacy_out = None
    if legacy_out is not None and Path(out).resolve() == legacy_out:
        return []
    return [f"{d} 是第一季文档（{OLD_DOC_DIR}/），不许导入到 {out}" for d in docs if d and OLD_DOC_DIR in Path(d).resolve().as_posix()]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    # A-08（V2_READINESS，总调度 19:2x：V2 导入前必须修）：不再默认导入第一季剧本、不再默认并入第一季的 image 提示词文档；
    # 输出默认 = 当前剧的导入稿（runs.script_path，K-OPS-F24）——以前默认写 data/import/script_v2.json，带 run=s2 导入会覆盖第一季
    ap.add_argument("--script", type=Path, required=True, help="要导入的剧本 md（必须给，没有默认值）")
    ap.add_argument("--image-doc", type=Path, default=None, help="可选：image 提示词文档（只在明确给出时并入；V2 不许引用旧剧文档）")
    ap.add_argument("-o", "--out", type=Path, default=None, help="输出导入稿；不给 = 当前剧（runs.json primary）的导入稿路径")
    ap.add_argument("--no-timeline", action="store_true", help="不重建 data/state_timeline.json")
    ap.add_argument("--source-version", default=None,
                    help="这份剧本的版本（如 v3；Qwen 剧本创作对话 script.md 文件名里没有版本时必须给，S1 闸门要求 ≥ v3）")
    ap.add_argument("--merge-base", type=Path, default=None,
                    help="单集 / 部分导入：以这个 script_v2.json 为底，只替换新稿里出现的集号，其余集保持不变"
                         "（2026-10-30 总调度：单集导入 = 只替换这一集）")
    args = ap.parse_args()
    if args.out is None:
        args.out = default_out()
    bad = old_doc_refs(args.out, [args.script, args.image_doc])
    if bad:
        print("拒绝导入：" + "；".join(bad))
        return 2

    run = target_run(args.out)
    if run and args.merge_base is not None:
        legacy_in = _runs().import_path(_runs().legacy_run(ROOT), ROOT).resolve()
        if Path(args.merge_base).resolve() == legacy_in:
            print(f"拒绝导入：{args.merge_base} 是 V1 的导入稿，不能当 {run} 的合并底稿（L-126）")
            return 2

    result = import_script(args.script, args.image_doc)
    # 剧本源文件记下版本与它提供的集（合并导入后 S1 闸门按集判版本）；版本优先 --source-version，否则文件名里的 vN
    import re as _re
    ver = args.source_version or (lambda m: f"v{m[-1]}" if m else None)(VERSION_IN_NAME.findall(args.script.name))
    for s in result.sources:
        if Path(s.path).resolve() == args.script.resolve():
            s.version, s.episodes = ver, [e.number for e in result.episodes]
    if args.merge_base is not None:
        result = merge_into(args.merge_base, result, single_source=bool(run))   # 非 V1 剧：全局头单一来源（当前集头）
    if run:                         # V2CUT-O：非 V1 剧的场景表 / 人物表只留本剧登记的（全局头带进来的别剧登记丢掉）
        result.warnings += scope_globals(result, *run_registered(run))
        result.warnings += scope_triggers(result, run_triggers(run))      # MERGE-OPS-O：触发词只取本剧登记
    n_auto = auto_triggers(result)
    if run:                         # MERGE-OPS-O（ISS-1103-024206-9974）：v1_leak 0 命中才写导入稿
        why = v1_gate(result, run)
        if why:
            print(f"拒绝导入（v1_leak block）：{why}")
            return 3
    if n_auto:
        print(f"系统自动补 LoRA 触发词 {n_auto} 处（config/auto_lora_triggers.json）")
    # 成人分类写进每个镜头（合并后对全部集重算，判定规则变了也能刷新）：笔记本与 gpu3 共用同一判定（docs/TASKS.md 规则 7）
    for ep in result.episodes:
        for s in ep.shots:
            s.adult_reasons = classify_adult(ep, s)
            s.adult = bool(s.adult_reasons)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.name + ".tmp")   # 封板修复 P2：原子写（桥 / 画布可能正在读）
    tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    from ns_agent.state_timeline import _replace_retry
    _replace_retry(tmp, args.out)

    shots = sum(len(e.shots) for e in result.episodes)
    g = result.globals
    adult = sum(bool(s.adult) for e in result.episodes for s in e.shots)
    print(f"成人镜头 {adult}（写入每镜 adult 字段）")
    print(f"集 {len(result.episodes)}，镜 {shots}，角色锁 {len(g.character_locks)}，"
          f"触发词 {len(g.lora_triggers)}，基准图 {len(g.references)}，装饰区间 {len(g.decor_schedule)}")
    print(f"输出 -> {args.out}")
    if result.warnings:
        print(f"\n警告 {len(result.warnings)} 条：")
        for w in result.warnings:
            print(f"  - {w}")
    # T51：导入后重建每镜人物状态时间线 + 场景分组（gpu3 读取），并存本规则版本的编译快照（tools/bible_diff.py）
    if (run or args.out.resolve() == (ROOT / "data" / "import" / "script_v2.json").resolve()) and not args.no_timeline:
        try:
            import os as _os
            if run:                 # V2CUT-O：按本剧导入稿重建本剧自己的状态表（data/import/runs/<run>/），不碰 V1 全局文件
                _os.environ["NS_RUN"] = run
            from ns_agent import state_timeline as T
            from ns_agent.prompt_snapshot import save_snapshot
            tl, _ = T.write(ROOT)
            if not run:             # 编译快照目录 data/bible_versions 是 V1 全局产物：非 V1 剧不写
                save_snapshot(ROOT)
            print(f"\n时间线 -> {T.timeline_path(ROOT)}（bible_version {tl['bible_version']}，"
                  f"剧本 {tl['source']['script']}，provisional={tl['provisional']}）")
        except Exception as e:  # noqa: BLE001 — 导入结果已写好，时间线失败只提示
            print(f"\n时间线重建失败：{type(e).__name__}: {e}（可手动 uv run python tools/build_state_timeline.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
