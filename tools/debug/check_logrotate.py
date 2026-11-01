"""K-OPS-E07 机器检查：gpu36 的 /etc/logrotate.d/ns-comfy-gpu36 与仓库里的 config/debug/ns-comfy-gpu36.logrotate 逐字一致。
用法：.venv/Scripts/python.exe tools/debug/check_logrotate.py [--fix]   （--fix = 不一致时按仓库版本写回；只读模式退出码 1 = 不一致）"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SPEC = ROOT / "config" / "debug" / "ns-comfy-gpu36.logrotate"
REMOTE = "/etc/logrotate.d/ns-comfy-gpu36"


def spec_ok(text: str) -> list[str]:
    """内容要求：三个日志都在、copytruncate（不重启 ComfyUI）、有 size 与 rotate 上限"""
    need = ["/root/work/fredw/comfy/logs/gpu0.log", "/root/work/fredw/comfy/logs/gpu1.log",
            "/root/work/fredw/longshot/logs/lane.log", "copytruncate", "size ", "rotate "]
    return [n for n in need if n not in text]


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    want = SPEC.read_text(encoding="utf-8")
    miss = spec_ok(want)
    if miss:
        print("仓库规格缺项：", miss)
        return 1
    from tools.netfix import rssh
    r = rssh.run("gpu36", f"timeout 20 cat {REMOTE}", timeout=60)
    have = r.stdout.decode("utf-8", "replace")
    if have.strip() == want.strip():
        print("OK gpu36", REMOTE, "与仓库一致")
        return 0
    print("不一致：gpu36", REMOTE, "rc", r.returncode)
    if "--fix" in argv:
        w = rssh.run("gpu36", f"timeout 20 tee {REMOTE} >/dev/null && timeout 30 logrotate -d {REMOTE} 2>&1 | tail -1",
                     input=want.encode(), timeout=90)
        print("已写回", w.returncode, w.stdout.decode("utf-8", "replace").strip())
        return 0 if w.returncode == 0 else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
