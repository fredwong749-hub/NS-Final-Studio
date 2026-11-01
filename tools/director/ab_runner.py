"""DIRECTOR A/B 执行器（服务器本机跑；D9：取代服务器上手改的 srv_run_dedicated.py 拷贝，随版本部署）。

复用 tools/video_rca/srv_run.py 的提交 / 取片 / 打分流程，只把“道”换成从配置读的单道：
  config/director/ab_runner.json：{lane: "gpu36:1", port: 8189, out: ".../output/gpu1", client_prefix: "director-",
                                   dedicated: true, borrowed_lanes: ["gpu36:1"]}
- 只往配置里的那一条道交单（LANES 置空，不轮询别的道）；目标道不在 borrowed_lanes 里 → 拒绝启动（K-OPS：生产道不许被 A/B 占）。
- dedicated=true（总调度批的临时专用道，producer hold_lanes 已挂住）→ 不按“生产有 ready 单”让道；false → 沿用 srv_run 的让道规则。
- client_id 前缀 director-，VIDEO-RCA 撤单不会误伤。
- 限线程 / 绑核沿用 srv_run（LIMIT / THREAD_ENV）。

  /root/work/fredw/venv_idm/bin/python tools/director/ab_runner.py [--config X.json] <exp_dir> [arm=prompt_id ...]
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "director" / "ab_runner.json"


def load_cfg(path: Path = CFG) -> dict:
    c = json.loads(path.read_text(encoding="utf-8"))
    if c.get("lane") not in (c.get("borrowed_lanes") or []):
        raise SystemExit(f"目标道 {c.get('lane')} 不在借用名单 {c.get('borrowed_lanes')} 里，拒绝启动（生产道不许被 A/B 占）")
    for k in ("port", "out", "client_prefix"):
        if not c.get(k):
            raise SystemExit(f"config/director/ab_runner.json 缺 {k}")
    return c


def configure(sr, c: dict):
    """把 srv_run 模块的道参数换成配置值（函数在调用时读模块全局）"""
    sr.PORT = int(c["port"])
    sr.OUT = c["out"]
    sr.LANES = []
    sr.CLIENT = c["client_prefix"]
    if c.get("dedicated"):
        sr.prod_ready = lambda: False
    return sr


def load_srv_run():
    spec = importlib.util.spec_from_file_location("nsfs_srv_run", ROOT / "tools" / "video_rca" / "srv_run.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    args = sys.argv[1:]
    cfg = CFG
    if "--config" in args:   # 别的 loop 借道时用自己的配置（例 config/vidlab/ab_runner.json，前缀 vidlab-）
        k = args.index("--config")
        cfg = Path(args[k + 1])
        cfg = cfg if cfg.is_absolute() else ROOT / cfg
        del args[k:k + 2]
    sr = configure(load_srv_run(), load_cfg(cfg))
    sr.main(args[0], dict(x.split("=", 1) for x in args[1:]))
