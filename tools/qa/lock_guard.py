"""改代码前的冻结锁闸门（DEBUG-RSI 11-02，总调度 03:2x；规则 K-OPS-E14，配合 FACTORY K-OPS-F08）。

system_version.py cut 期间工作树冻结（lock-status 退出码 3）。旧写法 `lock-status | head -2 && 改文件` 会被管道吃掉退出码，
11-02 02:5x / 03:0x 两次在 cut 中改了文件。统一用本脚本：

  .venv/Scripts/python.exe tools/qa/lock_guard.py                 # 没在 cut → 退出 0；在 cut → 打印原因，退出 3
  .venv/Scripts/python.exe tools/qa/lock_guard.py -- <命令 ...>   # 没在 cut 才执行命令，返回命令的退出码；在 cut → 不执行，退出 3
  Python 里：from tools.qa.lock_guard import require_unlocked; require_unlocked()   # 在 cut → 抛 LockedError

不要把它接到管道里（`| head` / `| tail` 会吞掉退出码）；要看输出就 `; echo rc=$?`。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCKED_RC = 3


class LockedError(RuntimeError):
    pass


def lock_state(runner=None) -> tuple[int, dict]:
    """→ (退出码, lock-status 的 json)；0 = 没在 cut，3 = cut 中，其它 = 查不了（按锁住处理）"""
    run = runner or (lambda: subprocess.run([sys.executable, str(ROOT / "tools/qa/system_version.py"), "lock-status"],
                                            capture_output=True, text=True, timeout=60, cwd=ROOT))
    r = run()
    try:
        info = json.loads(r.stdout or "{}")
    except ValueError:
        info = {"raw": (r.stdout or "")[-300:]}
    return r.returncode, info


def require_unlocked(runner=None) -> None:
    rc, info = lock_state(runner)
    if rc != 0:
        raise LockedError(f"system_version cut 进行中或锁状态查不了（rc={rc}）：{json.dumps(info, ensure_ascii=False)[:300]}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[argv.index("--") + 1:] if "--" in argv else []
    rc, info = lock_state()
    if rc != 0:
        print(f"LOCKED rc={rc}：现在不能改工作树（system_version cut 中，K-OPS-F08 / E14）", json.dumps(info, ensure_ascii=False)[:300],
              file=sys.stderr)
        return LOCKED_RC
    if not cmd:
        print("unlocked")
        return 0
    return subprocess.call(cmd, cwd=ROOT, timeout=int(os.environ.get("NS_LOCK_GUARD_TIMEOUT", "3600")))   # 总调度 03:0x：K-OPS arch_scan no_timeout


if __name__ == "__main__":
    sys.exit(main())
