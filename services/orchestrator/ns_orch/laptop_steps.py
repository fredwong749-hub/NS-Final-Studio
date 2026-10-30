"""
编排器的笔记本子进程入口（RealExecutor 调用；NS_PROJECT_ROOT = 项目目录）。

    NS_PROJECT_ROOT=projects/<slug> python -m ns_orch.laptop_steps frame_spec 3
"""
import json
import os
import sys
from pathlib import Path

from ns_api.project_ctx import ProjectContext, default_project
from ns_orch.executors import write_frame_specs


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 2 or argv[0] != "frame_spec":
        print(__doc__)
        return 2
    root = os.environ.get("NS_PROJECT_ROOT")
    ctx = ProjectContext(slug=Path(root).name, name=Path(root).name, root=Path(root)) if root else default_project()
    print(json.dumps(write_frame_specs(ctx, int(argv[1])), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
