"""把返修后的单集 P4 稿按"单集 merge"导入正式剧本（不用 replace）。导入前备份 data/import/script_v2.json。

用法：.venv/Scripts/python.exe tools/assetmaster/merge_import.py --ep 9 --ep 10 [--run data/pipeline/runs/series10_v1]
同时刷新整份合并稿 data/staging_v3/merged/<名>_lookfix_v3.md（供以后整份重导用）。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MERGED = ROOT / "data" / "staging_v3" / "merged"
BASE = MERGED / "漆皮之下·十日_series10_v1_ep01-10.md"
FULL = MERGED / "漆皮之下·十日_series10_v1_ep01-10_lookfix_v3.md"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", type=int, action="append", required=True)
    ap.add_argument("--run", default="data/pipeline/runs/series10_v1")
    a = ap.parse_args(argv)
    run = ROOT / a.run
    src = FULL if FULL.exists() else BASE
    M = src.read_text(encoding="utf-8")
    head = M[:M.find("## ep01《")]
    parts = re.split(r"(?m)^(?=## ep\d\d《)", M)
    new = {}
    for n in a.ep:
        t = (run / f"ep{n:02d}" / f"P4_ep{n:02d}.md").read_text(encoding="utf-8")
        new[n] = t[t.find(f"## ep{n:02d}《"):].rstrip() + "\n\n"
    ts = time.strftime("%Y%m%d_%H%M%S")
    note = f"<!-- ASSETMASTER {ts}：ep{','.join(str(n) for n in a.ep)} 造型一致性返修后单集 merge 导入（tools/assetmaster/look_fix.py） -->\n"
    stage = MERGED / f"漆皮之下·十日_series10_v1_lookfix_ep{'_'.join(f'{n:02d}' for n in a.ep)}_v3.md"
    stage.write_text(note + head + "".join(new[n] for n in a.ep), encoding="utf-8")
    full = [new.get(int(m.group(1)), p) if (m := re.match(r"## ep(\d\d)《", p)) else p for p in parts]
    FULL.write_text(note + "".join(full), encoding="utf-8")
    bk = ROOT / "data" / "import" / "backups" / f"script_v2.before_assetmaster_merge_{ts}.json"
    bk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "data" / "import" / "script_v2.json", bk)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "import_script.py"), "--script", str(stage),
                        "--image-doc", str(ROOT / "script play lib" / "为他而骚（image提示词） v2.md"),
                        "--merge-base", str(ROOT / "data" / "import" / "script_v2.json"), "--source-version", "v3"],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    print(r.stdout[-1500:], r.stderr[-800:])
    print(f"备份：{bk.relative_to(ROOT)}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
