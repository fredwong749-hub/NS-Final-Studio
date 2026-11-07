"""11-07 项目方选 a：冻结期单独放行 run_phase enforce（只改两台服务器 config/pipeline/state.json 的 run_phase.mode 一行，先备份）。
用法（在 D:\\NS-Final Studio）：.venv\\Scripts\\python.exe ops\\psmaster\\runphase_enforce_1107.py [--revert]
--revert = 改回 record。producer 每拍重读，不用重启。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
import resident_sync as RS  # noqa: E402

target = "record" if "--revert" in sys.argv else "enforce"
code = r'''
import json, os, shutil
p = "config/pipeline/state.json"
shutil.copy2(p, p + ".bak_rp_1107")
d = json.load(open(p, encoding="utf-8"))
rp = d.get("run_phase")
if not isinstance(rp, dict):
    rp = {"mode": rp}
before = rp.get("mode")
rp["mode"] = "TARGET"
rp["_by_1107"] = "11-07 owner a: run_phase only; revert = record"
d["run_phase"] = rp
tmp = p + ".tmp_rp"
json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, p)
print("before", before, "after", json.load(open(p, encoding="utf-8"))["run_phase"]["mode"])
'''.replace("TARGET", target)
py = RS.R.rsplit("/repo", 1)[0] + "/venv/bin/python"
for h in RS.HOSTS:
    out = RS.ssh(h, f"cd {RS.R} && {py} -", data=code.encode(), timeout=120, tries=2)
    print(h, (out.decode() if isinstance(out, bytes) else out).strip())
