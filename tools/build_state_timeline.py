"""
方案 D：生成 data/state_timeline.json + data/scenes.json（格式见 docs/state_timeline.md；gpu3 读取）。

    uv run python tools/build_state_timeline.py            # 生成并打印统计
    uv run python tools/build_state_timeline.py --check    # 只计算不写（打印统计）
    uv run python tools/build_state_timeline.py --run series10_v2   # 指定剧（V2CUT-O 11-03：按剧存放）

按剧存放（L-126）：V1（legacy_unprefixed_run）写 data/state_timeline.json + data/scenes.json（原样保留）；
其它剧按本剧导入稿生成 data/import/runs/<run>/state_timeline.json + scenes.json。不给 --run = 当前剧（NS_RUN / primary）。

剧本导入（tools/import_script.py）和造型修改（looks API）后会自动重建，一般不用手动跑。
"""
import argparse
import sys

from ns_agent import state_timeline as T
from ns_agent.prompt_snapshot import save_snapshot


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root")
    ap.add_argument("--run", default=None, help="剧名（config/pipeline/runs.json）；不给 = 当前剧（NS_RUN / primary）")
    a = ap.parse_args(argv)
    if a.run:
        import os
        os.environ["NS_RUN"] = a.run
    from ns_agent import run_paths as RP
    legacy = RP.is_legacy_run(T.project_root(a.root))
    if a.check:
        tl, _ = T.build(a.root)
    else:
        tl, _ = T.write(a.root)
        if legacy:                  # 编译快照目录 data/bible_versions 是 V1 全局产物：非 V1 剧不写
            save_snapshot(a.root)
        root = T.project_root(a.root)
        print(f"写入 {T.timeline_path(root)}、{T.scenes_path(root)}")
    print(T.summary(tl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
