"""换版首批复核（canary_after_redo，DISTILL gates.yaml；总调度 11-02 排期；reason_kind=canary 与 DEBUG-RSI 对齐）。

规则 / 资产换版（config/gen_contract.json、config/vqa.json、config/recipes/asset_refs.json 内容哈希变了）后，
前 N 张（默认 6）不同镜头的首帧里，同一个阻断项失败占比 > 线（默认 0.34）→ 暂停派单（producer.set_paused kind=canary，
不自动恢复）+ 报警 data/vqa/alerts.jsonl。按镜头去重：单镜反复重出（ep05-S3 82 版）不能代表换版效果。
infra 类不过（score_infra）、只因 Q9 没看成不计。状态 data/vqa/canary_state.json（原子写）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STATE = ROOT / "data" / "vqa" / "canary_state.json"
ALERTS = ROOT / "data" / "vqa" / "alerts.jsonl"
FILES = ("config/gen_contract.json", "config/vqa.json", "config/recipes/asset_refs.json")
N, LINE = 6, 0.34


def version_key(root: Path = ROOT) -> str:
    h = hashlib.sha256()
    for f in FILES:
        p = root / f
        h.update(p.read_bytes() if p.exists() else b"-")
    return h.hexdigest()[:16]


def _load() -> dict:
    if not STATE.exists():
        return {}                      # 第一次运行：按“新版本”从头数
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # arch-ok: 状态坏了从头数（只会多复核、不放宽判定），并显式报
        import sys
        print(f"[canary] 状态文件读不了，从头数：{e!r}"[:200], file=sys.stderr)
        return {}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def observe(sid: str, stage: str, pf: dict, key: str | None = None) -> dict | None:
    """每张出图打分后调用。→ 触发时返回 {item, frac, n, version}（调用方暂停派单），否则 None"""
    if stage != "image" or pf.get("ok") is None or pf.get("score_infra"):
        return None
    key = key or version_key()
    st = _load()
    if st.get("version") != key:
        st = {"version": key, "since": time.strftime("%Y-%m-%dT%H:%M:%S"), "samples": [], "decided": None}
    if st.get("decided") or any(s["sid"] == sid for s in st["samples"]):
        _save(st)
        return None
    blk = [b for b in pf.get("blocking") or [] if not (b == "Q9" and "未看图" in str(pf.get("reasons")))]
    st["samples"].append({"sid": sid, "blocking": blk, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    out = None
    if len(st["samples"]) >= N:
        cnt = Counter(b for s in st["samples"][:N] for b in set(s["blocking"]))
        worst = cnt.most_common(1)
        if worst and worst[0][1] / N > LINE:
            out = {"item": worst[0][0], "frac": round(worst[0][1] / N, 3), "n": N, "version": key,
                   "shots": [s["sid"] for s in st["samples"][:N] if worst[0][0] in s["blocking"]]}
            st["decided"] = {"action": "pause", **out}
            ALERTS.parent.mkdir(parents=True, exist_ok=True)
            with ALERTS.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "canary_pause", **out}, ensure_ascii=False) + chr(10))
        else:
            st["decided"] = {"action": "ok", "counts": dict(cnt)}
    _save(st)
    return out
