"""服务器上“这台的主剧是不是已经被别人暂停”的唯一判定（OVERSIGHT-F P1-3，总调度 11-02 19:4x；K-OPS-F20 / F24 / F26）。

以前 system_version.server_pause_owner 和 restart_queue.pre_paused 都写死读 data/producer/control.json——那是 legacy 剧（V1）的
control；primary 切到 V2 后，producer 读的是 data/producer/runs/<run>/control.json，判断就读错了剧。现在：
  剧 = config/pipeline/run.json 的 run_id（producer serve 默认跑的剧，同 producer.RUN_ID）
  control 路径 = legacy_unprefixed_run → data/producer/control.json；其它剧 → data/producer/runs/<run>/control.json
  已暂停 = runs.json 里该剧 status 不是 producing（暂停唯一来源，K-OPS-F20），或 control.paused=true
读不到 = 当作已暂停（保守：部署 / 重启不 pause 也不 resume，不清别人的暂停）。
"""
from __future__ import annotations

import json

PAUSE_PY = r'''
import json, os, sys
R = sys.argv[1]
def jl(p):
    with open(os.path.join(R, p), encoding="utf-8") as f:
        return json.load(f)
try:
    reg = jl("config/pipeline/runs.json")
    run = (jl("config/pipeline/run.json") or {}).get("run_id") or reg.get("primary")
    leg = reg.get("legacy_unprefixed_run")
    if not leg:
        raise ValueError("runs.json 没写 legacy_unprefixed_run")
    st = ((reg.get("runs") or {}).get(run) or {}).get("status")
    cp = "data/producer/control.json" if run == leg else "data/producer/runs/%s/control.json" % run
    try:
        c = jl(cp)
    except OSError:
        c = {}
    if st and st != "producing":
        out = {"run": run, "paused_by": "runs.json status=%s" % st}
    elif c.get("paused"):
        out = {"run": run, "paused_by": c.get("paused_by") or "unknown"}
    else:
        out = {"run": run, "paused_by": None}
except Exception as e:
    out = {"run": None, "paused_by": "unknown（%s）" % type(e).__name__}
print(json.dumps(out))   # ASCII 转义：任何终端编码都能原样解析
'''


def parse(out: str) -> str | None:
    """远端输出 → 暂停人（None = 没暂停）；解析不了 = 当作已暂停"""
    try:
        line = [x for x in (out or "").strip().splitlines() if x.startswith("{")][-1]
        return json.loads(line).get("paused_by")
    except (IndexError, ValueError):   # arch-ok: 读不出 = 保守按已暂停（不 pause / 不 resume）
        return "unknown（读暂停状态失败）"


def remote_pause_owner(rs, host: str, **ssh_kw) -> str | None:
    import base64
    code = base64.b64encode(PAUSE_PY.encode()).decode()
    try:
        raw = rs.ssh(host, f'python3 -c "$(echo {code} | base64 -d)" {rs.R}', **ssh_kw)
    except Exception as e:  # noqa: BLE001  # arch-ok: 连不上 = 保守按已暂停
        return f"unknown（读暂停状态失败：{type(e).__name__}）"
    return parse(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))
