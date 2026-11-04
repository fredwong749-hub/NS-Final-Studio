"""工人在 gpu33 上跑 pytest / arch_scan / 诊断脚本（W45 SERVER-DEV；用法见 docs/master/handover/DEV_ON_SERVER.md）。

项目方原话：“笔记本本来不适合做任务重的开发,gpu那2台服务器内存那么大,gpu 3090那么多卡,你不用,在这台笔记本做干嘛?”
此刻的工作树（.gitignore 口径，含未跟踪的新文件；不动真 index）→ 按 git blob sha 只推服务器上没有的文件 → gpu33 独立副本
（config/qa/remote_dev.json snap_root/_dev/<时间>，数据目录按 cut 快照同口径从 producer 仓库硬链）→ 独立 venv 跑 → 输出原样实时带回、退出码照传。
不碰 producer 的仓库与 venv；不删文件；测试进程 nice 10、CUDA_VISIBLE_DEVICES 置空。

  python tools/qa/remote_pytest.py tests/test_a.py tests/test_b.py -k foo      # pytest（≥ 2 个测试文件自动 -n 16）
  python tools/qa/remote_pytest.py -n 24 tests/                                # 指定 xdist 并行
  python tools/qa/remote_pytest.py --cmd '$PY tools/qa/arch_scan.py --check'   # 任意命令（$PY = 服务器 venv python，cwd = 副本根）
"""
from __future__ import annotations

import argparse
import importlib.util
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_rg():
    if "ns_remote_gates_rp" in sys.modules:
        return sys.modules["ns_remote_gates_rp"]
    spec = importlib.util.spec_from_file_location("ns_remote_gates_rp", Path(__file__).with_name("remote_gates.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["ns_remote_gates_rp"] = m
    spec.loader.exec_module(m)
    return m


def build_argv(pytest_args: list[str], n: int | None, cmd: str | None) -> list[str]:
    """→ 服务器上要跑的 argv（{PY} 由服务器换成 venv python）"""
    if cmd:
        return ["bash", "-c", cmd]
    files = [a for a in pytest_args if a.endswith(".py") or a.rstrip("/").endswith("tests")]
    if n is None:
        n = 16 if len(files) >= 2 or any(not a.endswith(".py") for a in files) else 0
    has_n = any(a == "-n" or a.startswith("-n") and a[2:].isdigit() for a in pytest_args)
    return ["{PY}", "-m", "pytest", "-p", "no:cacheprovider", *(["-n", str(n)] if n and not has_n else []), *pytest_args]


def run(pytest_args: list[str], n: int | None = None, cmd: str | None = None, host: str | None = None, timeout: float | None = None,
        no_data: bool = False, log=print, rg=None, sh_fn=None, tree: str | None = None, evidence: bool = False) -> int:
    rg = rg or load_rg()
    cfg = rg.load_cfg()
    host = host or cfg["host"]
    dev = cfg["snap_root"] + "/" + cfg.get("dev_dir", "_dev")
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    dest = rg.check_dest(f"{dev}/{stamp}", cfg)
    t0 = time.time()
    tree = tree or rg.worktree_tree()
    st = rg.stage_tree(cfg, host, tree, dest, dev, [] if no_data else rg.expand_data_rels(rg.ignored_paths()), sh_fn=sh_fn, log=log,
                       overlay=rg.merged_overlay(cfg) if evidence else None)
    if st.get("error"):
        log("❌ " + st["error"])
        return 2
    argv = build_argv(pytest_args, n, cmd)
    sp = rg.call_op(cfg, host, "spawn", {"job": dest + ".job", "dest": dest, "mode": "exec", "argv": argv, "nice": cfg.get("nice", 10)},
                    sh_fn=sh_fn)
    if sp.get("error"):
        log("❌ " + sp["error"])
        return 2
    log(f"[w45] {host}:{dest} $ {' '.join(shlex.quote(a) for a in argv)}")
    w = rg.wait_job({**cfg, "poll_s": cfg.get("dev_poll_s", 5)}, host, dest + ".job", float(timeout or cfg.get("gates_timeout_s") or 7200),
                    log=log, sh_fn=sh_fn)
    log(f"[w45] {w['state']} rc={w.get('rc')}（合计 {time.time() - t0:.0f} s；准备 {st.get('stage_s')} s，推 {st.get('pushed')} 个文件）"
        + (f"：{w.get('error')}" if w.get("error") else ""))
    if w["state"] != "done":
        return 3
    return int(w.get("rc") or 0)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass                                    # 非文本流：照常输出
    ap = argparse.ArgumentParser(description="W45：在 gpu33 上跑 pytest / 任意诊断命令（推此刻工作树的增量）",
                                 epilog="其余参数原样交给 pytest")
    ap.add_argument("-n", type=int, default=None, help="xdist 并行数（默认：≥ 2 个测试文件 / 目录 = 16，否则串行）")
    ap.add_argument("--cmd", default=None, help="不跑 pytest，跑这条 shell 命令（$PY = 服务器 venv python）")
    ap.add_argument("--host", default=None)
    ap.add_argument("--timeout", type=float, default=None)
    ap.add_argument("--no-data", action="store_true", help="不硬链数据目录（纯单元测试更快）")
    ap.add_argument("--tree", default=None, help="用指定 git 树代替此刻工作树")
    ap.add_argument("--evidence", action="store_true", help="同 cut：带上笔记本数据（知识库证据 / 决策账本 / arch 基线 + B 方案镜像），结果与笔记本可比")
    a, rest = ap.parse_known_args(argv)
    if not rest and not a.cmd:
        ap.error("要给测试文件 / pytest 参数，或 --cmd")
    return run(rest, a.n, a.cmd, a.host, a.timeout, a.no_data, tree=a.tree, evidence=a.evidence)


if __name__ == "__main__":
    sys.exit(main())
