"""master_review 机签（VQAGATE 11-02；总调度批准，DISTILL 判定函数 policy.autosign_switch_ok / autosign_spot_check；
门槛 config/policies/resources.yaml master_review_autosign；gates.only_show_passing / DJ-11；iter_gate --for-owner C2 认 master_review*.md）。

  check                    回归集（regression_check --json 的 pairs）+ 总调度历史亲审（takes.json：master_review.ok = 人判过，
                           画面原因的 master_reject = 人判不过；流程性驳回如全量重做 / 剧本返修不算）对机判（postflight.ok）
                           → autosign_switch_ok → data/vqa/autosign_state.json {mode: auto|manual, ...}
  sign <review_dir> <manifest.json>
                           manifest = [{"sid": "ep01-S1", "stage": "image", "n": 3}, ...]（审片页上的候选）。mode=auto 且每条都
                           契约 postflight.ok + Q9 pass（Q1a 有就要 pass）+ 回归集全过 → 写 <review_dir>/master_review_auto.md（by=POLICY）；
                           否则不写、列出原因（回到总调度亲签）。签了的按 testphase_spot_check_ratio 抽进 data/vqa/autosign_spot.jsonl
  false-reject <file> [说明]  总调度判过、机器拦了 → data/vqa/autosign_false_reject.jsonl（误拦面样本）
  spot <id> pass|fail      总调度抽检结论 → autosign_spot_check：不一致 → mode=manual（退回人工）+ data/vqa/alerts.jsonl 报警
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data" / "vqa" / "autosign_state.json"
SPOT = ROOT / "data" / "vqa" / "autosign_spot.jsonl"
SIGNED = ROOT / "data" / "vqa" / "autosign_signed.jsonl"
FALSE_REJECT = ROOT / "data" / "vqa" / "autosign_false_reject.jsonl"   # 总调度判过、机器拦了（误拦面样本，测试期积累）
ALERTS = ROOT / "data" / "vqa" / "alerts.jsonl"
PROCESS_WORDS = ("全量重做", "剧本", "重出", "旧 img", "隔离")


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _append(p: Path, row: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + chr(10))


def _rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def state() -> dict:
    if not STATE.exists():
        return {"mode": "manual", "why": ["还没跑过 check"]}
    return json.loads(STATE.read_text(encoding="utf-8"))


def history_pairs(root: Path = ROOT) -> list[dict]:
    out = []
    for tj in glob.glob(str(root / "data" / "renders" / "ep*" / "S*" / "takes.json")):
        try:
            d = json.loads(Path(tj).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"[autosign] 跳过读不了的 {tj}: {e!r}"[:200], file=sys.stderr)
            continue
        for t in d.get("takes") or []:
            if t.get("stage") != "image" or (t.get("postflight") or {}).get("ok") is None:
                continue
            if not (root / "data" / str(t.get("file") or "")).exists():
                # 总调度 11-02 08:3x：只取现行剧本的样本——旧剧本的图已隔离（data/_quarantine_20261102_oldscript），
                # 现行契约按新剧本的镜头要求判，拿它去比旧图不成立
                continue
            mr, rj = t.get("master_review") or {}, t.get("master_reject")
            if rj:
                why = str(rj.get("reason") if isinstance(rj, dict) else rj)
                by = str(rj.get("by") if isinstance(rj, dict) else "")
                if "WORKFLOW" in by or any(w in why for w in PROCESS_WORDS):
                    continue
                human = "fail"
            elif mr.get("ok") and not any(x in str(mr.get("by") or "") for x in ("VQAGATE", "POLICY")):
                human = "pass"
            else:
                continue
            out.append({"auto": "pass" if t["postflight"]["ok"] else "fail", "human": human, "file": t.get("file"),
                        "why": str((rj or {}).get("reason") if isinstance(rj, dict) else "")[:80]})
    return out


def regression() -> dict:
    r = subprocess.run([sys.executable, str(ROOT / "tools/vqa/regression_check.py"), "--json"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", timeout=1800)
    line = next((x for x in reversed((r.stdout or "").splitlines()) if x.startswith("{")), None)
    if not line:
        return {"ok": False, "pairs": [], "why": "回归集没跑成：" + (r.stderr or "")[-200:]}
    d = json.loads(line)
    return {"ok": r.returncode == 0 and not d.get("bad"), "pairs": d.get("pairs") or [], "bad": d.get("bad") or []}


def check() -> dict:
    sys.path.insert(0, str(ROOT))
    from tools.autopilot import policy
    reg = regression()
    hist = history_pairs()
    sw = policy.autosign_switch_ok(reg["pairs"] + [{"auto": h["auto"], "human": h["human"]} for h in hist])
    why = list(sw.get("why") or []) + ([] if reg["ok"] else ["回归集没全过"])
    st = {"mode": "auto" if (sw["ok"] and reg["ok"]) else "manual", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
          "agreement": sw.get("agreement"), "false_pass": sw.get("false_pass"), "n": sw.get("n"),
          "n_regression": len(reg["pairs"]), "n_history": len(hist), "regression_ok": reg["ok"], "why": why,
          "false_pass_samples": [h for h in hist if h["auto"] == "pass" and h["human"] == "fail"][:10]}
    old = state()
    if old.get("mode") == "manual" and old.get("reverted_at") and st["mode"] == "auto":
        st["mode"], st["why"] = "manual", ["抽检不一致退回过人工：要总调度确认后才重新切换"] + why
        st["reverted_at"] = old["reverted_at"]
    _w(STATE, st)
    return st


def take_ok(sid: str, stage: str, n: int) -> tuple[bool, str]:
    ep, s = sid.split("-")
    tj = ROOT / "data" / "renders" / ep / s / "takes.json"
    d = json.loads(tj.read_text(encoding="utf-8"))
    t = next((x for x in d.get("takes") or [] if x.get("stage") == stage and int(x.get("n") or 0) == int(n)), None)
    if not t:
        return False, f"{sid} {stage} v{n} 不在 takes.json"
    pf = t.get("postflight") or {}
    items = {i["id"]: i.get("status") for i in pf.get("items") or []}
    if pf.get("ok") is not True:
        return False, f"{sid} v{n} 契约没过（{'、'.join(pf.get('blocking') or [])}）"
    if items.get("Q9") != "pass":
        return False, f"{sid} v{n} 本地看图 Q9 = {items.get('Q9')}"
    if "Q1a" in items and items["Q1a"] != "pass":
        return False, f"{sid} v{n} Q1a = {items['Q1a']}"
    if t.get("master_reject"):
        return False, f"{sid} v{n} 被驳回过"
    return True, t.get("file") or ""


def sign(review_dir: str, manifest: str) -> int:
    st = state()
    rows = json.loads(Path(manifest).read_text(encoding="utf-8"))
    bad, good = [], []
    if st.get("mode") != "auto":
        bad.append("机签未切换（mode=manual）：" + "；".join(st.get("why") or []))
    reg = regression()
    if not reg["ok"]:
        bad.append("回归集没全过")
    for r in rows:
        ok, info = take_ok(r["sid"], r.get("stage", "image"), r["n"])
        (good if ok else bad).append(info if not ok else {**r, "file": info})
    if bad:
        print("不机签，回到总调度亲签：" + chr(10) + chr(10).join(f"- {b}" for b in bad))
        return 1
    d = ROOT / review_dir
    lines = [f"# master_review（机签 by=POLICY，{time.strftime('%Y-%m-%d %H:%M')}）", "",
             f"门槛：回归集一致率 {st.get('agreement')}、漏放 {st.get('false_pass')}（n={st.get('n')}）；条件：契约全过 + 本地看图 Q9 / Q1a 过 + 回归集全过", "",
             "| 镜 | 阶段 | 版本 | 文件 |", "|---|---|---|---|"] + [f"| {g['sid']} | {g.get('stage', 'image')} | v{g['n']} | {g['file']} |" for g in good]
    (d / "master_review_auto.md").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    from tools.autopilot import policy
    ratio = float((policy.get("resources.master_review_autosign", {}) or {}).get("testphase_spot_check_ratio", 0.10))
    for i, g in enumerate(good):
        k = len(_rows(SIGNED))
        _append(SIGNED, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "review_dir": review_dir, **g})
        if ratio > 0 and k % max(1, round(1 / ratio)) == 0:
            _append(SPOT, {"id": f"{g['sid']}:{g.get('stage', 'image')}:{g['n']}", "file": g["file"], "auto": "pass", "human": None,
                           "queued_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    print(f"机签：{len(good)} 条 → {d / 'master_review_auto.md'}")
    return 0


def spot(sid: str, verdict: str) -> dict:
    sys.path.insert(0, str(ROOT))
    from tools.autopilot import policy
    rows = _rows(SPOT)
    for r in rows:
        if r["id"] == sid and r.get("human") is None:
            r.update(human=verdict, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
            break
    else:
        raise SystemExit(f"抽检队列里没有待判的 {sid}")
    SPOT.write_text("".join(json.dumps(r, ensure_ascii=False) + chr(10) for r in rows), encoding="utf-8")
    done = [{"auto": r["auto"], "human": r["human"]} for r in rows if r.get("human")]
    res = policy.autosign_spot_check(done, len(_rows(SIGNED)))
    if res["action"] == "revert":
        st = state()
        st.update(mode="manual", reverted_at=time.strftime("%Y-%m-%dT%H:%M:%S"), why=[res["why"]])
        _w(STATE, st)
        _append(ALERTS, {"at": st["reverted_at"], "kind": "autosign_revert", "why": res["why"], "spot": sid})
    return res


def false_reject(file: str, note: str = "") -> dict:
    """总调度抽检 / 亲审时判过、但机器（契约 / 看图）拦了的图：记误拦样本（不影响机签开关，用来调闸门、补回归集）"""
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": file, "auto": "fail", "human": "pass", "note": note[:200]}
    _append(FALSE_REJECT, row)
    return row


def main(argv: list[str]) -> int:
    if argv and argv[0] == "check":
        print(json.dumps(check(), ensure_ascii=False, indent=1))
        return 0
    if len(argv) == 3 and argv[0] == "sign":
        return sign(argv[1], argv[2])
    if len(argv) >= 2 and argv[0] == "false-reject":
        print(json.dumps(false_reject(argv[1], " ".join(argv[2:])), ensure_ascii=False))
        return 0
    if len(argv) == 3 and argv[0] == "spot" and argv[2] in ("pass", "fail"):
        print(json.dumps(spot(argv[1], argv[2]), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
