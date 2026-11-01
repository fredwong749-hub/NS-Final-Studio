"""运镜词表 A/B 判定（DIRECTOR L-107；K-REN-801 / K-REV-806）：读 data/ab/video_rca/cm_r1/results.json（tools/video_rca/lab.py export / pull，
服务器道空档跑，生产优先），按 config/director/camera_moves.yaml ab_criteria AB1–AB5 逐臂判，同一运镜 2 seed 全过 → enabled: true，
否则 enabled: false 并写原因；把结果写回词表（只改该运镜的 enabled / ab / reason 三行），结果表写 data/ab/camera_moves/cm_r1_verdict.json。
decider = code。

  python tools/director/camera_ab.py [--exp cm_r2] [--pull] [--dry]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOCAB = ROOT / "config" / "director" / "camera_moves.yaml"
EXP = "cm_r2"
RES = ROOT / "data" / "ab" / "video_rca" / EXP / "results.json"
OUT = ROOT / "data" / "ab" / "camera_moves" / f"{EXP}_verdict.json"
SIZES = ["大特写", "特写", "近景", "中近景", "中景", "中全景", "全景", "远景"]
BAND = {"大特写": 0, "特写": 1, "近景": 2, "中近景": 2, "近景/中近景": 2, "中景": 3, "中全景": 4, "全景": 5, "远景": 6}
WHO = "林晚"


def judge(arm: dict, want_size: str = "中景") -> dict:
    """一臂 → {pass, fails[], metrics}；没分数 = 未测"""
    sc = arm.get("score") or {}
    if not sc or sc.get("error"):
        return {"pass": None, "fails": ["未测：" + str(sc.get("error") or "没有分数")[:80]], "m": {}}
    idn = (sc.get("identity") or {}).get(WHO) or {}
    v6 = sc.get("v6") or {}
    m = {"mean": sc.get("mean"), "cuts": len(sc.get("cuts") or []), "sface_med": idn.get("sface_med"), "sface_p10": idn.get("sface_p10"),
         "dup_side": v6.get("dup_side_frac"), "extra_hand": v6.get("extra_hand_frac"), "people": v6.get("people"),
         "J4": sc.get("J4"), "J4_z": sc.get("J4_z"), "size": sc.get("size_measured")}
    f = []
    if (m["mean"] or 0) < 0.5 or m["cuts"]:
        f.append(f"AB1 运动 mean {m['mean']} / 镜内硬切 {m['cuts']}")
    if m["sface_med"] is None or m["sface_med"] < 0.30 or (m["sface_p10"] or 0) < 0.25:
        f.append(f"AB2 面部不稳 SFace 中位 {m['sface_med']} p10 {m['sface_p10']}")
    if (m["dup_side"] or 0) > 0.15 or (m["extra_hand"] or 0) > 0.05 or (m["people"] not in (None, 1)):
        f.append(f"AB3 分身 / 多肢 dup {m['dup_side']} 多手 {m['extra_hand']} 人数 {m['people']}")
    soft = []
    if (m["J4"] or 0) > 1.3 and (m["J4_z"] or 0) >= 3:
        soft.append(f"AB4 4 帧一顿 J4 {m['J4']}（z {m['J4_z']}，去抖处理，不否决）")
    if m["size"] and abs(BAND.get(m["size"], 3) - BAND.get(want_size, 3)) > 1:
        f.append(f"AB5 景别跑档 {want_size} → {m['size']}")
    return {"pass": not f, "fails": f, "soft": soft, "m": m}


def set_move(text: str, mid: str, enabled: bool, ab: dict, reason: str) -> str:
    """只改词表里该运镜块的 enabled / ab / reason 三行（保留注释和其余字段）"""
    lines = text.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.strip() == f"- id: {mid}")
    j = next((k for k in range(i + 1, len(lines)) if lines[k].lstrip().startswith("- id:") or lines[k].startswith("  #")), len(lines))
    for k in range(i, j):
        s = lines[k].strip()
        if s.startswith("enabled:"):
            lines[k] = f"    enabled: {'true' if enabled else 'false'}"
        elif s.startswith("ab:"):
            lines[k] = "    ab: " + json.dumps(ab, ensure_ascii=False)
        elif s.startswith("reason:"):
            lines[k] = "    reason: " + json.dumps(reason, ensure_ascii=False)
    return "\n".join(lines) + "\n"


RULES = ROOT / "knowledge" / "rules" / "director.yaml"


def _atomic_write(path: Path, text: str) -> None:
    """先写同目录 tmp 再 os.replace（arch_scan nonatomic_json）"""
    import os
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def writer_line(vocab_text: str) -> str:
    """K-WRT-804 的 writer_text：从词表生成（中文名 + 适用场景；只列 enabled 的，其余说明会被改成固定镜头）"""
    import yaml
    v = yaml.safe_load(vocab_text)
    on = [m for m in v["moves"] if m.get("enabled")]
    off = [m["zh"] for m in v["moves"] if not m.get("enabled")]
    items = "；".join(f"{m['zh']}（{'、'.join(m.get('moods') or [])}；{'/'.join(m.get('sizes') or [])}）" for m in on)
    return (f"镜头运动字段只写运镜词表里的名字，每镜一种，幅度写“小幅”，不写速度词。当前可用：{items}。"
            f"词表里其余（{'、'.join(off)}）Pika 上没验证通过，写了会被编译层改成固定镜头；复合运镜按词表拆成两镜。")


def update_writer_rule(vocab_text: str) -> bool:
    if not RULES.exists():
        return False
    lines = RULES.read_text(encoding="utf-8").splitlines()
    try:
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "- id: K-WRT-804")
    except StopIteration:
        return False
    for k in range(i + 1, len(lines)):
        if lines[k].lstrip().startswith("- id:"):
            break
        if lines[k].strip().startswith("writer_text:"):
            lines[k] = "    writer_text: " + json.dumps(writer_line(vocab_text), ensure_ascii=False)
            _atomic_write(RULES, chr(10).join(lines) + chr(10))
            return True
    return False


def main(argv):
    global EXP, RES, OUT
    if "--exp" in argv:   # 实验名（cm_r1 / cm_r2 …），默认 cm_r2（r4 gpu36:1 专用道那一轮）
        EXP = argv[argv.index("--exp") + 1]
    RES = ROOT / "data" / "ab" / "video_rca" / EXP / "results.json"
    OUT = ROOT / "data" / "ab" / "camera_moves" / f"{EXP}_verdict.json"
    if "--pull" in argv:
        subprocess.run([sys.executable, str(ROOT / "tools/video_rca/lab.py"), "pull", EXP], cwd=ROOT, check=False, timeout=3600)
    rows = json.loads(RES.read_text(encoding="utf-8")) if RES.exists() else []
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    by = {}
    for r in rows:
        m = re.match(r"cm_(.+)_s(\d+)$", r.get("id") or "")
        if m:
            by.setdefault(m.group(1), []).append({"seed": int(m.group(2)), **judge(r)})
    text = VOCAB.read_text(encoding="utf-8")
    table = {}
    for mid, arms in sorted(by.items()):
        tested = [a for a in arms if a["pass"] is not None]
        if mid == "static":
            table[mid] = {"verdict": "baseline", "arms": arms}
            continue
        if len(tested) < 2:
            table[mid] = {"verdict": "pending", "arms": arms}
            continue
        ok = all(a["pass"] for a in tested)
        why = "；".join(sorted({f.split(" ")[0] + " " + f.split(" ", 1)[1][:40] for a in tested for f in a["fails"]})) or "AB1–AB5 全过"
        ab = {"status": "pass" if ok else "fail", "exp": f"data/ab/video_rca/{EXP}", "seeds": [a["seed"] for a in tested],
              "metrics": [a["m"] for a in tested], "soft": sorted({s for a in tested for s in a.get("soft") or []})}
        reason = f"Pika A/B {EXP} 2 seed 全过" if ok else f"Pika A/B {EXP} 未过：{why}"
        table[mid] = {"verdict": ab["status"], "reason": reason, "arms": arms}
        if "--dry" not in argv:
            text = set_move(text, mid, ok, ab, reason)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(OUT, json.dumps({"exp": EXP, "decider": "code", "criteria": "config/director/camera_moves.yaml ab_criteria",
                                   "table": table}, ensure_ascii=False, indent=1))
    if "--dry" not in argv:
        _atomic_write(VOCAB, text)
        if update_writer_rule(text):   # 写作规则跟着词表走，再生成 writer_knowledge
            subprocess.run([sys.executable, str(ROOT / "tools/knowledge/compile.py")], cwd=ROOT, check=False, timeout=600)
    for mid, t in table.items():
        print(mid, t["verdict"], t.get("reason", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
