"""
项目方关口记录（SOP ★）：只由项目方本人运行；每条都必须写项目方原话。API / 画布只显示这些命令，从不代为执行。

    uv run python tools/sop_owner.py plate <scene_id> "项目方原话"        # 确认场景底板（写 assets/scenes/<id>/manifest.json）
    uv run python tools/sop_owner.py plate <scene_id> --revoke
    uv run python tools/sop_owner.py g4 --episode 1 "项目方原话"          # G4 样片锁定（要求该集 qa.json 每镜 pass）
    uv run python tools/sop_owner.py g4 --revoke
    uv run python tools/sop_owner.py g5 <集> "项目方原话"                 # G5 成片验收：发布（要求已有 _final）
    uv run python tools/sop_owner.py g5 <集> --rework "返工原因"
    uv run python tools/sop_owner.py show

记录：G4/G5 → data/sop/owner_gates.json；底板确认字段与 docs/state_timeline.md §三 一致
（owner_confirmed_at / owner_confirmed_ref / plate_sha256 = 确认时的图 sha，换图后自动失效）。改底板后重建状态表。
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OWNER_GATES = Path("data") / "sop" / "owner_gates.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (OSError, ValueError):
        return default


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(p)


def _quote(q: str | None) -> str:
    if not q or not q.strip():
        raise SystemExit("必须写项目方原话/消息引用（系统从不自动接受）")
    return q.strip()


def plate(root: Path, scene_id: str, quote: str | None, revoke: bool, rebuild: bool) -> dict:
    d = root / "assets" / "scenes" / scene_id
    man = _read(d / "manifest.json", {}) or {}
    if revoke:
        for k in ("owner_confirmed_at", "owner_confirmed_ref", "plate_sha256"):
            man.pop(k, None)
    else:
        q = _quote(quote)
        scenes = _read(root / "data" / "scenes.json", {}) or {}
        if scenes.get("provisional", True):
            raise SystemExit("data/scenes.json 仍是临时分组（S1 未过）：不得确认底板")
        img = d / (man.get("plate") or "plate.png")
        if not img.is_file():
            raise SystemExit(f"没有底板图：{img}")
        man.update(plate=img.name, owner_confirmed_at=_now(), owner_confirmed_ref=q,
                   plate_sha256=hashlib.sha256(img.read_bytes()).hexdigest())
    _write(d / "manifest.json", man)
    if rebuild:
        from ns_agent import state_timeline as T
        T.write(root)
    return man


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _script_shots(root: Path) -> dict[int, list[int]] | None:
    """剧本里每集的镜号（没有剧本返回 None）"""
    d = _read(root / "data" / "import" / "script_v2.json", None)
    if not isinstance(d, dict):
        return None
    try:
        return {int(e["number"]): [int(s["index"]) for s in e.get("shots") or []] for e in d.get("episodes") or []}
    except (KeyError, TypeError, ValueError):
        return None


def _active_video(gpu3_root: Path, episode: int, sn: str) -> Path | None:
    """gpu3 镜像里该镜当前采用的视频（takes.json active.video；文件路径相对 data/）"""
    tk = _read(gpu3_root / f"ep{episode:02d}" / sn / "takes.json", None)
    if not isinstance(tk, dict):
        return None
    n = (tk.get("active") or {}).get("video")
    t = next((t for t in tk.get("takes") or [] if t.get("stage") == "video" and t.get("n") == n), None)
    if not t or not t.get("file"):
        return None
    f = gpu3_root.parent / t["file"]
    return f if f.is_file() else None


def g4(root: Path, gpu3_root: Path, episode: int, quote: str | None, revoke: bool) -> dict:
    p = root / OWNER_GATES
    rec = _read(p, {}) or {}
    if revoke:
        if rec.get("g4"):
            rec["g4"]["revoked_at"] = _now()
    else:
        q = _quote(quote)
        shots = _script_shots(root)
        sample = min(shots) if shots else 1
        if episode != sample:
            raise SystemExit(f"G4 只锁样片集（第 {sample} 集），不是第 {episode} 集")
        qa = _read(gpu3_root / f"ep{episode:02d}" / "qa.json", None)
        if not isinstance(qa, dict) or qa.get("verdict") != "pass":
            raise SystemExit(f"ep{episode:02d} 的 qa.json 不是 pass：先让第 {episode} 集每镜视频过 QA，再锁样片")
        per = qa.get("shots") if isinstance(qa.get("shots"), dict) else {}
        bad = []
        if not per:
            bad.append("qa.json 没有逐镜结果")
        if shots and episode in shots:
            bad += [f"S{i} 不在 qa.json" for i in shots[episode] if f"S{i}" not in per]
        locked = {}
        for sn, v in sorted(per.items()):
            v = v if isinstance(v, dict) else {}
            if v.get("verdict") != "pass":
                bad.append(f"{sn} verdict={v.get('verdict')!r}")
            elif not v.get("video_sha256"):
                bad.append(f"{sn} 没有 video_sha256（不知道验的是哪一版视频）")
            else:
                f = _active_video(gpu3_root, episode, sn)
                if f is not None and _sha(f) != v["video_sha256"]:
                    bad.append(f"{sn} 当前视频与 qa.json 验收的版本不一致（sha256）")
                locked[sn] = v["video_sha256"]
        if bad:
            r