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


def merge_into(base_path: Path, new):
    """把新稿的集按集号替换进底稿（ScriptImport）；底稿其余集原样保留。
    全局头（角色锁 / 触发词 / 后缀等）用新稿的（新稿带完整全局头时）；来源列表合并；“缺少集数”类警告去掉。"""
    from ns_schema.script import ScriptImport
    base = ScriptImport.model_validate_json(base_path.read_text(encoding="utf-8"))
    new_eps = {e.number: e for e in new.episodes}
    episodes = [new_eps.pop(e.number, e) for e in base.episodes] + sorted(new_eps.values(), key=lambda e: e.number)
    replaced = sorted(new_eps_all := {e.number for e in new.episodes})
    g = merge_globals(base.globals, new.globals, new_eps_all)
    # 封板修复：只去掉“缺少集数”里与本次替换无关的那类；新稿里同一集号重复要提示
    warnings = [w for w in new.warnings if not w.startswith("缺少集数")]
    if len(new.episodes) != len(new_eps_all):
        warnings.append(f"新稿里有重复的集号：{sorted(n for n in new_eps_all if sum(e.number == n for e in new.episodes) > 1)}，只保留最后一个")
    warnings.append(f"合并导入：以 {base_path.name} 为底，替换集 {replaced}，其余 {len(episodes) - len(replaced)} 集保持不变")
    warnings += registry_drift(base.globals, new.globals, new_eps_all)
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


def registry_drift(base_g, new_g, replaced: set[int]) -> list[str]:
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
            if diff and base_registered(o, replaced):
                where = "、".join("全剧表" if n is None else f"ep{n:02d}" for n in (getattr(o, "defined_in", None) or []))
                out.append(f"登记冲突：{key(e)} 的 {'、'.join(diff)} 与先登记的（{where or '底稿'}）不同，保留先登记的、不覆盖；"
                           f"新稿第 {sorted(replaced)} 集里逐字引用的新文字会对不上，请按先登记的返修")
    return out


def merge_globals(base, new, replaced: set[int] | frozenset = frozenset()):
    """封板修复 P0：逐字段合并全局头——新稿非空才覆盖（单集稿常没有角色锁 / 后缀 / 基础负面，旧逻辑会整份清空）；
    触发词按 trigger 合并（新稿优先）；装饰自查表按集覆盖。
    人物表 / 场景表（fredw-92 2026-10-31 定：全剧一份、逐集继承）：先登记的为准——底稿登记仍有效（base_registered）就保留，
    只有定义它的集全部被这次替换时才用新稿的；新角色 / 新场景追加"""
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
        return list(d.values())
    pick = lambda k: getattr(new, k) or getattr(base, k)   # noqa: E731
    return base.model_copy(update={
        **{k: pick(k) for k in ("motion_suffix", "image_suffix", "base_negative", "decor_schedule", "daily_outfit")},
        "character_locks": by_key("character_locks", lambda c: c.name),   # 单集稿只写一条角色锁时不丢其余角色
        "references": by_key("references", lambda r: r.id),
        "lora_triggers": by_key("lora_triggers", lambda t: t.trigger),
        "scene_library": registry("scene_library", lambda e: e.scene_id),   # S1：场景表按场景 id 合并（先登记为准）
        "character_registry": registry("character_registry", lambda e: e.name),   # R3：人物表按角色名合并（先登记为准）
        "decor_tables": {**base.decor_tables, **new.decor_tables}})


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


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, default=LIB / "为他而骚 （剧本和镜头）v2.md")
    ap.add_argument("--image-doc", type=Path, default=LIB / "为他而骚（image提示词） v2.md")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "data" / "import" / "script_v2.json")
    ap.add_argument("--no-timeline", action="store_true", help="不重建 data/state_timeline.json")
    ap.add_argument("--source-version", default=None,
                    help="这份剧本的版本（如 v3；Qwen 剧本创作对话 script.md 文件名里没有版本时必须给，S1 闸门要求 ≥ v3）")
    ap.add_argument("--merge-base", type=Path, default=None,
                    help="单集 / 部分导入：以这个 script_v2.json 为底，只替换新稿里出现的集号，其余集保持不变"
                         "（2026-10-30 总调度：单集导入 = 只替换这一集）")
    args = ap.parse_args()

    result = import_script(args.script, args.image_doc)
    # 剧本源文件记下版本与它提供的集（合并导入后 S1 闸门按集判版本）；版本优先 --source-version，否则文件名里的 vN
    import re as _re
    ver = args.source_version or (lambda m: f"v{m[-1]}" if m else None)(VERSION_IN_NAME.findall(args.script.name))
    for s in result.sources:
        if Path(s.path).resolve() == args.script.resolve():
            s.version, s.episodes = ver, [e.number for e in result.episodes]
    if args.merge_base is not None:
        result = merge_into(args.merge_base, result)
    n_auto = auto_triggers(result)
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
    if args.out.resolve() == (ROOT / "data" / "import" / "script_v2.json").resolve() and not args.no_timeline:
        try:
            from ns_agent import state_timeline as T
            from ns_agent.prompt_snapshot import save_snapshot
            tl, _ = T.write(ROOT)
            save_snapshot(ROOT)
            print(f"\n时间线 -> {T.timeline_path(ROOT)}（bible_version {tl['bible_version']}，"
                  f"剧本 {tl['source']['script']}，provisional={tl['provisional']}）")
        except Exception as e:  # noqa: BLE001 — 导入结果已写好，时间线失败只提示
            print(f"\n时间线重建失败：{type(e).__name__}: {e}（可手动 uv run python tools/build_state_timeline.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
