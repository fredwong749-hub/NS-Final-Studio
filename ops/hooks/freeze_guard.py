"""Claude Code PreToolUse hook: system_version 冻结期间拒绝写代码目录（项目方 11-02 12:1x 批准；SYSARCH 冻结锁第 1 层，K-OPS-F08）。

stdin = hook JSON（tool_name, tool_input.file_path / notebook_path）。
只在目标位于 D:\\NS-Final Studio 的代码目录、且 lock_guard 判锁住时，输出 deny；其余一律放行（exit 0，无输出）。
锁状态查不了时按“锁住”处理（与 lock_guard 一致，失败关闭），但只影响代码目录。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE_DIRS = ("tools", "services", "apps", "config", "knowledge", "tests", "ops", "packages")


def _target(data: dict) -> Path | None:
    ti = data.get("tool_input") or {}
    p = ti.get("file_path") or ti.get("notebook_path")
    return Path(p).resolve() if p else None


def _in_code_dir(p: Path) -> bool:
    try:
        rel = p.relative_to(ROOT)
    except ValueError:   # arch-ok: 不在仓库下 = 不归冻结锁管，放行
        return False
    return bool(rel.parts) and rel.parts[0] in CODE_DIRS


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:   # arch-ok: hook 输入不是 JSON = 不是编辑类调用（harness 格式异常），放行；拦截只针对能解析出目标路径的写入
        return 0
    p = _target(data)
    if p is None or not _in_code_dir(p):
        return 0
    sys.path.insert(0, str(ROOT))
    try:
        from tools.qa.lock_guard import lock_state
        rc, info = lock_state()
    except Exception as e:  # noqa: BLE001  查不了 → 按锁住
        rc, info = 99, {"error": str(e)[:200]}
    if rc == 0:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"system_version 冻结中（lock rc={rc}），代码目录 {p.relative_to(ROOT).parts[0]}/ 禁止写入；等解冻后再改（K-OPS-F08）。"
    }}))   # ASCII 转义：Windows 控制台 cp1252 下也不会编码失败
    return 0


if __name__ == "__main__":
    sys.exit(main())
