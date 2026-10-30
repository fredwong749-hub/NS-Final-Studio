"""
导入剧本：python tools/import_script.py  →  data/import/script_v2.json

默认读取 script play lib 下的《剧本和镜头》v2 和《image提示词》v2。
"""
import argparse
import sys
from pathlib import Path

from ns_agent.compiler import classify_adult
from ns_agent.importer.script_md import import_script

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "script play lib"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, default=LIB / "为他而骚 （剧本和镜头）v2.md")
    ap.add_argument("--image-doc", type=Path, default=LIB / "为他而骚（image提示词） v2.md")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "data" / "import" / "script_v2.json")
    ap.add_argument("--no-timeline", action="store_true", help="不重建 data/state_timeline.json")
    args = ap.parse_args()

    result = import_script(args.script, args.image_doc)
    # 成人分类写进每个镜头：笔记本与 gpu3 共用同一判定（docs/TASKS.md 规则 7）
    for ep in result.episodes:
        for s in ep.shots:
            s.adult_reasons = classify_adult(ep, s)
            s.adult = bool(s.adult_reasons)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(result.model_dump_json(indent=2), encoding="utf-8", newline="\n")

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
