"""
方案 D：生成 data/state_timeline.json + data/scenes.json（格式见 docs/state_timeline.md；gpu3 读取）。

    uv run python tools/build_state_timeline.py            # 生成并打印统计
    uv run python tools/build_state_timeline.py --check    # 只计算不写（打印统计）

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
    a = ap.parse_args(argv)
    if a.check:
        tl, _ = T.build(a.root)
    else:
        tl, _ = T.write(a.root)
        save_snapshot(a.root)
        root = T.project_root(a.root)
        print(f"写入 {T.timeline_path(root)}、{T.scenes_path(root)}")
    print(T.summary(tl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
