"""视频按镜分片（PLAN_EP01_FINISH §11）。默认关：config/pipeline/video_shard.json enabled=false → 本模块所有函数都返回“没分片”，
调用方走原来的整集一台逻辑。

分片 = 纯函数：(配置, 本集全部镜 id + 时长) → {镜: 主机}。两台服务器的 night 各自算，结果一致（不用互相通信，不用租约文件）：
  · 每台的 jobs.json 里每镜带 host（build_jobs 填），vidgen Runner 本来就只出 host == 本机 的镜 → 两台出的镜互不相交；
  · state_<host>.json 本来就是一台一份、只有那台的 vidgen 写 → 状态天然不互相覆盖；
  · owner（hosts.json / partition 里这一集的归属）负责合成；helper 的 state + 片子由笔记本 shard_relay.py 送到 owner，
    owner 用 merged_shots() 读各台 state 合并出整集视图（只读，不写 helper 的 state）。
登记 takes 仍走 register_takes → P.mutate_takes（加锁），这里不碰 takes.json。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "pipeline" / "video_shard.json"


def load(path: Path | None = None) -> dict:
    """读不到 / 坏 = 没分片（失败关闭到原行为）"""
    try:
        d = json.loads(Path(path or CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 配置读不到 = 不分片（默认关，失败关闭到原行为）
        return {"enabled": False}
    return d if isinstance(d, dict) else {"enabled": False}


def ep_cfg(run: str, ep: int, cfg: dict | None = None) -> dict | None:
    """这一集的分片配置 {"owner","weights","map","hosts"}；没开 / 没配 / 不足两台 → None"""
    cfg = load() if cfg is None else cfg
    if not cfg.get("enabled"):
        return None
    e = (((cfg.get("runs") or {}).get(run) or {}).get("eps") or {}).get(str(int(ep)))
    if not e:
        return None
    weights = {str(h): float(w) for h, w in (e.get("weights") or {}).items() if float(w) > 0}
    if len(weights) < 2:
        return None
    owner = str(e.get("owner") or "")
    if owner not in weights:
        return None            # owner 必须是分片台之一，否则没人合成：失败关闭到“不分片”
    return {"owner": owner, "weights": weights, "map": {str(k): str(v) for k, v in (e.get("map") or {}).items()},
            "hosts": sorted(weights)}


def plan(c: dict, shots: list[tuple[str, float]]) -> dict[str, str]:
    """shots = [(镜 id, 时长秒)] → {镜: 主机}。显式 map 优先；其余按“时长降序、负载 / 权重最小的台先拿”贪心（确定性，平局按主机名）"""
    out = {sid: h for sid, h in c["map"].items() if h in c["weights"]}
    load_s = {h: 0.0 for h in c["weights"]}
    for sid, sec in shots:
        if sid in out:
            load_s[out[sid]] += float(sec)
    rest = sorted((x for x in shots if x[0] not in out), key=lambda x: (-float(x[1]), x[0]))
    for sid, sec in rest:
        h = min(sorted(c["weights"]), key=lambda k: (load_s[k] + float(sec)) / c["weights"][k])
        out[sid] = h
        load_s[h] += float(sec)
    return out


def plan_all(run: str, specs: dict, cfg: dict | None = None) -> dict[str, str]:
    """specs = {镜 id: ShotSpec（.episode / .duration_s）} → {镜: 主机}（只含配了分片的集的镜；没开 = {}）"""
    cfg = load() if cfg is None else cfg
    by_ep: dict[int, list[tuple[str, float]]] = {}
    for sid, s in specs.items():
        by_ep.setdefault(int(s.episode), []).append((sid, float(s.duration_s)))
    out: dict[str, str] = {}
    for ep, shots in by_ep.items():
        c = ep_cfg(run, ep, cfg)
        if c:
            out.update(plan(c, shots))
    return out


def shard_eps(run: str, cfg: dict | None = None) -> dict[int, dict]:
    """{集: 分片配置}（没开 = {}）"""
    cfg = load() if cfg is None else cfg
    if not cfg.get("enabled"):
        return {}
    eps = (((cfg.get("runs") or {}).get(run) or {}).get("eps") or {})
    return {int(e): c for e in eps if (c := ep_cfg(run, int(e), cfg))}


def eps_on_host(run: str, host: str, hosts_map: dict, cfg: dict | None = None) -> list[int]:
    """本机该出的集 = 原来按集归属的 ∪ 分片集里本机是分片台的（owner 本来就在前一项里）"""
    eps = {int(e) for e, h in (hosts_map or {}).items() if h == host}
    eps |= {e for e, c in shard_eps(run, cfg).items() if host in c["hosts"]}
    return sorted(eps)


def helper_hosts(run: str, cfg: dict | None = None) -> set[str]:
    return {h for c in shard_eps(run, cfg).values() for h in c["hosts"] if h != c["owner"]}


def exclude_lanes(host: str, cfg: dict | None = None) -> list[str]:
    """分片开着时本机不派视频的道（gpu33:3 = 看图 + reserve-vram 9）；没开 = []"""
    cfg = load() if cfg is None else cfg
    if not cfg.get("enabled"):
        return []
    return [x for x in ((cfg.get("exclude_lanes") or {}).get(host) or [])]


def merged_shots(vid: Path, ep: int, hosts: list[str], jobs: dict | None = None) -> dict:
    """整集视图：读 hosts 各台的 state_<host>.json，按镜合并成 {镜: 记录}（只读）。
    同一镜两台都有记录（配置中途改过）→ 取 jobs.json 里 host 对得上的那台；没 jobs → 渲染版本多的那台"""
    jh = {s["shot"]: s.get("host") for s in (jobs or {}).get("shots", [])}
    out: dict = {}
    src: dict = {}
    for h in hosts:
        try:
            st = json.loads((Path(vid) / f"state_{h}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 那台的 state 还没送来 = 这些镜暂时算“没出”（调用方据此等待，不会拿缺镜合成）
            continue
        for sid, r in (st.get("shots") or {}).items():
            if int(sid[2:4]) != int(ep):
                continue
            if sid in out:
                cur_ok, new_ok = jh.get(sid) == src[sid], jh.get(sid) == h
                if cur_ok or (not new_ok and len(out[sid].get("renders") or []) >= len(r.get("renders") or [])):
                    continue
            out[sid], src[sid] = r, h
    return out


def ep_hosts(run: str, ep: int, owner: str, cfg: dict | None = None) -> list[str]:
    """读这一集状态要看的主机：分片 → 全部分片台（owner 在前）；否则 [owner]"""
    c = ep_cfg(run, ep, cfg)
    return [owner] + [h for h in c["hosts"] if h != owner] if c else [owner]
