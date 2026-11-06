"""L-209 S2.3（W-S234，11-07）：分区 partition.json 只留一份 + 临时 hold 一律带到期。

唯一一份：data/state/netfix/partition.json（tools/factory/state_paths 逻辑名 netfix/partition）。
  · 写者：tools/netfix/dispatch.py（push_server_control 三方合并）、tools/debug/lanes.py（hold / lend / release / sweep，带 dispatch.partition_lock）、
    tools/factory/repart.py。只写这一份。
  · config/netfix/partition.json = 旧副本，只读、弃用（_doc 写明），之后隔离到 data/_quarantine/（不删）。新代码不许读它；
    state_paths 的兼容读（新位置不在才读旧位置）仍留痕到 data/state/legacy_reads.jsonl。
读者一律经本模块：
  load(root)      → 分区（已剔除过期的 _temp_holds / _lent_lanes，以及它们在 retired_lanes 里的对应项）；“_dropped_holds” 记剔除原因
  load_raw(root)  → 原样（写者读-改-写用；读者不要用）
  held(part)      → 该 hold 的道（退役道 + 有效借道 / 临时 hold）
  alive(rec)      → (有效?, 原因)
到期口径（所有读者同一个）：
  · expires_at（或 until）到点失效；时间串不带时区按 JST（+09:00）读（K-OPS-E18），带时区按时区；
  · 没带到期 / 写坏：写入时刻 at 起 MAX_NO_EXPIRY_S（2 小时）后失效（L209_S2_PLAN S2.3 验收“没有超过 2 小时的临时 hold”）；
  · 到期和写入时刻都没有 = 不认（S2.3：临时 hold 必须带到期）。
写者写时间一律用 jst()（无时区 JST 串，与 producer.iso 同口径；笔记本时钟是美东，不能用 time.localtime）。
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "netfix/partition"
REL = "data/state/netfix/partition.json"
LEGACY_REL = "config/netfix/partition.json"
HOLD_KEYS = ("_lent_lanes", "_temp_holds")
MAX_NO_EXPIRY_S = 2 * 3600
JST = timezone(timedelta(hours=9))
TS = "%Y-%m-%dT%H:%M:%S"
_SP = None


def _sp():
    global _SP
    if _SP is None:
        d = str(ROOT / "tools" / "factory")
        if d not in sys.path:
            sys.path.insert(0, d)
        import state_paths as SP  # noqa: PLC0415
        _SP = SP
    return _SP


def path(root: Path | None = None) -> Path:
    return Path(root or ROOT) / REL


def jst(t: float | None = None) -> str:
    """epoch → 无时区 JST 串（写 at / expires_at 用）"""
    return datetime.fromtimestamp(time.time() if t is None else t, JST).strftime(TS)


def ts_epoch(s) -> float | None:
    """时间串 → epoch；无时区按 JST；数字 = epoch；认不出 = None"""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        d = datetime.fromisoformat(str(s).strip().replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=JST)).timestamp()


def alive(rec, now: float | None = None, max_no_expiry_s: float = MAX_NO_EXPIRY_S) -> tuple[bool, str]:
    """一条借道 / 临时 hold 记录此刻是否有效 → (有效?, 失效原因)"""
    t = time.time() if now is None else now
    rec = rec if isinstance(rec, dict) else {}
    exp = ts_epoch(rec.get("expires_at") or rec.get("until"))
    if exp is not None:
        return (exp > t), ("" if exp > t else f"已过到期 {rec.get('expires_at') or rec.get('until')}")
    t0 = ts_epoch(rec.get("at"))
    if t0 is None:
        return False, "没带到期也没有写入时刻（S2.3：临时 hold 必须带到期）"
    if t - t0 > max_no_expiry_s:
        return False, f"没带到期，写入 {rec.get('at')} 已超 {max_no_expiry_s / 3600:.0f} h"
    return True, ""


def load_raw(root: Path | None = None) -> dict:
    """原样读唯一一份（写者读-改-写用）；新位置不在才读旧位置并留痕（state_paths 兼容读）"""
    d = _sp().read_state(NAME, default={}, root=Path(root or ROOT))
    return d if isinstance(d, dict) else {}


def live(part: dict | None, now: float | None = None) -> dict:
    """剔除过期 / 没带到期的借道与临时 hold（含 retired_lanes 里只因它们才在的道）；不改入参"""
    out = copy.deepcopy(part or {})
    dropped: dict = {}
    kept: set = set()
    for k in HOLD_KEYS:
        m = out.get(k) if isinstance(out.get(k), dict) else {}
        keep = {}
        for lane, rec in m.items():
            ok, why = alive(rec, now)
            if ok:
                keep[lane] = rec
                kept.add(lane)
            else:
                dropped[lane] = f"{k}: {why}"
        if k in out or keep:
            out[k] = keep
    if dropped:
        out["retired_lanes"] = [x for x in out.get("retired_lanes") or [] if x not in dropped or x in kept]
        out["_dropped_holds"] = dropped
    return out


def load(root: Path | None = None, now: float | None = None) -> dict:
    """读者唯一入口：唯一一份分区，过期 hold 已剔除"""
    return live(load_raw(root), now)


def held(part: dict | None, now: float | None = None) -> set:
    """该 hold 的道：没有借道 / 临时 hold 记录的 retired_lanes（真退役）+ 有效的借道 / 临时 hold"""
    part = part or {}
    rec: dict = {}
    for k in HOLD_KEYS:
        for lane, v in (part.get(k) or {}).items():
            rec[lane] = rec.get(lane, False) or alive(v, now)[0]
    out = {ln for ln in part.get("retired_lanes") or [] if ln not in rec}
    return out | {ln for ln, a in rec.items() if a}


def long_holds(part: dict | None, now: float | None = None, max_s: float = MAX_NO_EXPIRY_S) -> dict:
    """巡检：剩余时长超过 max_s 的有效临时 hold {道: 说明}（验收“没有超过 2 小时的临时 hold”）"""
    t = time.time() if now is None else now
    out = {}
    for k in HOLD_KEYS:
        for lane, v in ((part or {}).get(k) or {}).items():
            exp = ts_epoch((v or {}).get("expires_at") or (v or {}).get("until"))
            if exp is not None and exp - t > max_s:
                out[lane] = f"{k} 还剩 {(exp - t) / 3600:.1f} h（by {(v or {}).get('by')}）"
    return out


def md5(root: Path | None = None) -> str | None:
    try:
        return hashlib.md5(path(root).read_bytes()).hexdigest()[:8]
    except OSError:  # arch-ok: 文件不在 = None（巡检显示“缺”）
        return None


def _cli(argv: list[str]) -> int:
    if argv and argv[0] == "show":
        p = load()
        print(json.dumps({"path": REL, "md5": md5(), "held": sorted(held(p)), "dropped": p.get("_dropped_holds") or {},
                          "long_holds": long_holds(p), "images": p.get("images"), "video": p.get("video")}, ensure_ascii=False, indent=1))
        return 0
    print("用法：python tools/netfix/partition.py show")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
