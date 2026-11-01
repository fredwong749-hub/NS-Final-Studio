"""K-OPS-E18 数据层检查：控制文件里的时间戳必须带时区偏移（ISO 8601，如 2026-11-02T04:30:00+09:00）。
不带偏移的时间戳 = 失败（报出文件 / 字段路径），不静默当本地时间。

用法：.venv/Scripts/python.exe tools/debug/tz_check.py [--strict] [文件 ...]
  默认扫 CONTROL_FILES；--strict 时有任何不带偏移的时间戳就退出 1（过渡期默认只报告、退出 0）。
迁移计划（总调度 04:4x，G0）：
  1. 远程调用唯一入口 tools/netfix/rssh.py（run / run_retry）和 rsh.py 统一注入 TZ=Asia/Tokyo（NETFIX 合入，见 PATCH_RSSH）。
  2. 写时间戳的公共函数（producer.iso 等）改为输出带 +09:00 的 ISO 8601；读取方遇到不带偏移的报警。
  3. 各写入方迁完后把本检查改成 --strict 进 iter_gate。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL_FILES = ["data/producer/control.json", "data/producer/master_rejects.json", "data/producer/heartbeat.json",
                 "config/netfix/partition.json", "data/netfix/override_state.json"]
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(?P<off>Z|[+-]\d{2}:?\d{2})?$")
PATCH_RSSH = """# 给 NETFIX：tools/netfix/rssh.py rewrite() / run() / run_retry() 拼远程命令时统一前缀
#   remote_cmd = "TZ=Asia/Tokyo " + cmd        （服务器之间本机执行的 bash -c 分支同样处理）
# 测试：tests/test_netfix.py::test_rssh_injects_tz —— rewrite（参数：ssh 命令 + gpu33 + date）的最后一段以 "TZ=Asia/Tokyo " 开头"""


def scan(obj, path="$"):
    """→ [(路径, 值)]：所有像时间戳但不带偏移的字符串"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += scan(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        m = TS.match(obj)
        if m and not m.group("off"):
            out.append((path, obj))
    return out


def check(files: list[str]) -> dict:
    res = {}
    for f in files:
        p = ROOT / f if not Path(f).is_absolute() else Path(f)
        if not p.exists():
            continue                                      # 文件本来就不存在（这台机器没有这个控制文件）不算问题
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:                # 失败关闭：读不了 / 坏 JSON 记为问题，不静默跳过
            res[str(p)] = {"n": 1, "examples": [("$", f"读不了：{type(e).__name__}: {e}")]}
            continue
        bad = scan(d)
        if bad:
            res[str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)] = {"n": len(bad), "examples": bad[:3]}
    return res


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    files = [a for a in argv if not a.startswith("--")] or CONTROL_FILES
    res = check(files)
    print(json.dumps({"naive_timestamps": res, "strict": strict}, ensure_ascii=False, indent=1))
    return 1 if (strict and res) else 0


if __name__ == "__main__":
    sys.exit(main())
