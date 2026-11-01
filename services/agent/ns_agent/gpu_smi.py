"""nvidia-smi 只读查询的共用解析（GPUVIEW 2026-11-01）。

ns_api.gpu_live（GPU 面板）和 tools/monitor/server.py（:8810 看板）共用这一份，不各写一遍。
只做查询（--query-gpu / --query-compute-apps），绝不执行 nvidia-smi -pl 等改状态的命令。
"""
from __future__ import annotations

MONITOR_FIELDS = ("index", "name", "utilization.gpu", "memory.used", "memory.total", "temperature.gpu", "power.draw")
MONITOR_QUERY = "nvidia-smi --query-gpu=" + ",".join(MONITOR_FIELDS) + " --format=csv,noheader,nounits"


def parse_query(lines, names) -> list[dict]:
    """csv,noheader 输出（行列表或整段字符串）→ [{name: 原始字符串}]；列数不够的行跳过；第一列须是数字（GPU 序号）"""
    if isinstance(lines, str):
        lines = lines.splitlines()
    out = []
    for ln in lines:
        p = [x.strip() for x in ln.split(",")]
        if len(p) < len(names) or not p[0].isdigit():
            continue
        out.append(dict(zip(names, p)))
    return out


def num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_monitor(out: str) -> list[dict]:
    """tools/monitor/server.py 旧格式：{idx, name, util, mem, memt, temp, pw}"""
    res = []
    for r in parse_query(out, ("idx", "name", "util", "mem", "memt", "temp", "pw")):
        res.append({"idx": int(r["idx"]), "name": r["name"].replace("NVIDIA GeForce ", ""), "util": num(r["util"], 0.0),
                    "mem": num(r["mem"], 0.0), "memt": num(r["memt"], 0.0), "temp": r["temp"], "pw": r["pw"]})
    return res
