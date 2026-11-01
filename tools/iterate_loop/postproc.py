"""出片后、审片前的后处理（按 RenderPlan.post）：去抖（tools/dejudder.py）、肤色限幅（ns_post.skin_guard）。
产物写到 data/iterate_loop/<run>/post/，不覆盖原 take（refactor_proposal §3.3：后处理作为新产物记录）。
合成时用后处理后的文件（loop 写 sources timeline），所以审到的就是进片的。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv" / "Scripts" / "python.exe"


class PostRunner:
    dry = False

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir

    def apply(self, sid: str, tag: str, src: Path, post: dict) -> tuple[Path, list[str]]:
        steps, cur = [], Path(src)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if post.get("dejudder"):
            dst = self.out_dir / f"{sid}_{tag}_dj.mp4"
            if not dst.exists():
                r = subprocess.run([str(PY), str(ROOT / "tools" / "dejudder.py"), str(cur), str(dst)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT))
                if r.returncode != 0 or not dst.exists():
                    raise RuntimeError(f"dejudder 失败：{(r.stderr or '')[-400:]}")
            cur = dst
            steps.append("dejudder")
        if post.get("skin_guard"):
            sys.path.insert(0, str(ROOT / "services" / "post"))
            from ns_post.skin_guard import ensure_sg
            p, _rep = ensure_sg(cur, log=lambda *a: None)
            if p:
                cur = Path(p)
                steps.append("skin_guard")
        return cur, steps


class DryPostRunner:
    dry = True

    def apply(self, sid: str, tag: str, src: Path, post: dict) -> tuple[Path, list[str]]:
        return Path(src), [k for k in ("dejudder", "skin_guard") if post.get(k)]
