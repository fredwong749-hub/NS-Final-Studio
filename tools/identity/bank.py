"""身份库（VQAGATE 11-02，总调度 L-098 批准：Q1 身份库 top-k）。

每个主角一个身份库：锚 = L-086 身份脸（asset_refs.face_of，永远在、不出库），外加已通过的帧：
- 入库条件（防止身份库被慢慢带偏，总调度 04:0x）：首帧过了契约（postflight ok）、没被驳回（master_reject）、
  本镜 Q1 只有这一个角色、单脸，且 Q1 证据里对 L-086 的相似度 ≥ 0.60；
- 按正脸 / 侧脸分组（MediaPipe 头部偏转 |yaw_n| < 0.4 = 正脸；没有 mediapipe 的机器记 unknown），每组最多 8 张，按时间滚动（新的进、旧的出）；
- 每次重建都重新核一遍：被驳回 / 契约改判不过的帧立刻出库（bank_files 发现任一 takes.json 比库新就先重建）。
产物：data/identity/bank.json {角色: {"front": [{file, sim, at}], "side": [...], "unknown": [...]}}（原子写）。
remote_score.face_refs 读它，把库里的帧作为 "<角色>@bN" 参照一起上传打分；top-k 平均和锚条件在 postflight Q1 里算。

    python tools/identity/bank.py            # 重建本机身份库
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "data" / "identity" / "bank.json"
NAME_ID = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}
MIN_ANCHOR = 0.60
PER_GROUP = 8


def _yaw(path: Path) -> float | None:
    try:
        sys.path.insert(0, str(ROOT / "packages/qc"))
        sys.path.insert(0, str(ROOT / "services/agent"))
        from ns_agent.vqa import contract as VQ
        fs = VQ.gaze_mp(path)
    except Exception:  # noqa: BLE001 — 没有 mediapipe 的机器：分组记 unknown
        return None
    if not fs:
        return None
    return abs(float(max(fs, key=lambda f: (f.get("box") or [0, 0, 0, 0])[3])["yaw_n"]))


def candidates() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for tj in glob.glob(str(ROOT / "data" / "renders" / "ep*" / "S*" / "takes.json")):
        try:
            d = json.loads(Path(tj).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:  # 坏的 takes.json：这一镜不入库（库只会更小，不会放宽判定），显式报
            print(f"[bank] 跳过读不了的 {tj}: {e!r}"[:200], file=sys.stderr)
            continue
        for t in d.get("takes") or []:
            if t.get("stage") != "image" or t.get("master_reject") or not t.get("file"):
                continue
            pf = t.get("postflight") or {}
            if pf.get("ok") is not True:
                continue
            q1 = next((i for i in pf.get("items") or [] if i.get("id") == "Q1"), None)
            ev = (q1 or {}).get("evidence") or {}
            sims = ev.get("sims") or {}
            if not q1 or q1.get("status") != "pass" or len(sims) != 1 or (ev.get("faces") or 1) != 1:
                continue
            cid, sim = next(iter(sims.items()))
            f = ROOT / "data" / t["file"]
            if sim is None or sim < MIN_ANCHOR or not f.exists():
                continue
            out.setdefault(cid, []).append({"file": "data/" + t["file"], "sim": round(float(sim), 3),
                                            "at": t.get("created_at") or ""})
    return out


def build() -> dict:
    bank = {}
    for cid, rows in candidates().items():
        groups: dict[str, list] = {"front": [], "side": [], "unknown": []}
        for r in sorted(rows, key=lambda r: r["at"], reverse=True):
            y = _yaw(ROOT / r["file"])
            g = "unknown" if y is None else ("front" if y < 0.4 else "side")
            if len(groups[g]) < (2 * PER_GROUP if g == "unknown" else PER_GROUP):   # 没 mediapipe 的机器（gpu33）全落 unknown，总数仍 ≤16
                groups[g].append({**r, "yaw": None if y is None else round(y, 3)})
        bank[cid] = groups
    BANK.parent.mkdir(parents=True, exist_ok=True)
    tmp = BANK.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "min_anchor": MIN_ANCHOR, "per_group": PER_GROUP,
                               "bank": bank}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, BANK)
    return bank


def stale() -> bool:
    if not BANK.exists():
        return True
    t = BANK.stat().st_mtime
    return any(os.path.getmtime(tj) > t for tj in glob.glob(str(ROOT / "data" / "renders" / "ep*" / "S*" / "takes.json")))  # arch-ok: 判库是否过期（比较全部 takes.json），不是按 mtime 猜当前剧 / 最新文件


def bank_files(cid: str) -> list[str]:
    """remote_score.face_refs 用：这个角色身份库里的帧（不含锚），最多 2×PER_GROUP 张。
    任一 takes.json 比库新（新出图 / 驳回 / 改判都会写它）→ 先重建，驳回的帧下一次打分就出库"""
    if stale():
        build()
    d = json.loads(BANK.read_text(encoding="utf-8"))
    g = (d.get("bank") or {}).get(cid) or {}
    return [r["file"] for k in ("front", "side", "unknown") for r in g.get(k) or [] if (ROOT / r["file"]).exists()][:2 * PER_GROUP]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    b = build()
    print(json.dumps({c: {g: len(v) for g, v in gs.items()} for c, gs in b.items()}, ensure_ascii=False))
