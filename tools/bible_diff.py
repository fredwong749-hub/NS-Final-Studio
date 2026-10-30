"""
列出自某个规则版本（bible_version）以来编译提示词变了的镜头（T06）。

    uv run python tools/bible_diff.py                      # 打印当前 bible_version，并存当前快照
    uv run python tools/bible_diff.py <旧版本>              # 旧版本 → 当前：变了的镜头 + 变了的字段
    uv run python tools/bible_diff.py <旧版本> --show ep01-S3   # 打印该镜新旧提示词
    uv run python tools/bible_diff.py --inject-preview     # 预览打开 [looks] inject 后的差异（不改 toml）
    uv run python tools/bible_diff.py --inject-preview --all-episodes   # 预览时不管集计划是否已确认
    --json                                                 # 机器可读输出

旧版本的快照在 data/bible_versions/<版本>.json.gz（剧本导入、造型修改、本工具运行时自动存）；
没有快照时退回 data/renders/*/*/compiled.json 里记录了该版本的镜头（含画布人工修改，只能比较这些镜头）。
"""
import argparse
import json
import sys

from ns_agent import prompt_snapshot as PS
from ns_agent.bible import project_root


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("old", nargs="?", help="旧 bible_version（可写前缀）")
    ap.add_argument("--show", help="打印某一镜的新旧提示词")
    ap.add_argument("--inject-preview", action="store_true", help="当前 vs 打开造型注入后")
    ap.add_argument("--all-episodes", action="store_true", help="预览注入时忽略项目方确认状态")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", help="项目根目录（默认 NS_PROJECT_ROOT 或仓库根）")
    a = ap.parse_args(argv)
    root = project_root(a.root)
    # 版本号取自实际保存的快照（编译期间输入变了也对得上）；快照读不出来就直接编译当前结果
    cur_v = PS.save_snapshot(root).name.removesuffix(".json.gz")
    snap_cur = PS.load_snapshot(cur_v, root)
    current = snap_cur["shots"] if snap_cur else PS.compile_all(root)

    if a.inject_preview:
        old, new = current, PS.compile_all(root, inject_looks=True, confirmed_only=not a.all_episodes)
        label = f"{cur_v} → {cur_v}+looks.inject" + (" (all episodes)" if a.all_episodes else " (owner-confirmed episodes)")
        source = "preview"
    elif a.old:
        snap = PS.load_snapshot(a.old, root)
        if snap:
            old, source = snap["shots"], "snapshot"
        else:
            old, source = PS.from_compiled_files(a.old, root), "compiled.json"
            if not old:
                print(f"没有版本 {a.old} 的快照，也没有记录该版本的 compiled.json", file=sys.stderr)
                return 2
            current = {k: v for k, v in current.items() if k in old}
        new = current
        label = f"{snap['bible_version'] if snap else a.old} → {cur_v}"
    else:
        print(cur_v)
        return 0

    changed = PS.diff(old, new)
    if a.json:
        print(json.dumps({"from": a.old, "to": cur_v, "source": source, "changed": changed}, ensure_ascii=False, indent=1))
    else:
        print(f"{label}（{source}）：{len(changed)} 镜提示词变化 / {len(new)} 镜")
        for sid, fields in changed.items():
            print(f"  {sid}: {', '.join(fields)}")
    if a.show:
        o, n = old.get(a.show, {}), new.get(a.show, {})
        for f in PS.FIELDS + ("spec_qwen",):
            if o.get(f) != n.get(f):
                print(f"\n[{f}]\n- {o.get(f)}\n+ {n.get(f)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
