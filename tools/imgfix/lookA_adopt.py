"""IMGFIX r5：造型 A 袖子修复版按 REFLOCK 流程替换（总调度亲审“采用”后执行；L-098 项目方全权委托总调度）。

  step adopt  : 候选 → data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202_sleevefix.png（新文件，旧 adopted 原地保留 + 隔离副本）；
                走中枢 set_sheet 接口把 sheet:lin_wan_lookA 指过去（审计 character_hub_log），sheets_chosen 先备份；
                sheet_item_checks 补一条按文件认的 pass 记录（K-AST-260 / 262：v2_s202 同一张图只改袖子）；重裁 front / back / half nohead + hand2
  step reject : 按 data/autopilot/lookA_hold.json，已出图的首帧 / 尾帧当前版走 producer.master_reject（不计次）
  step release: lookA_hold.json active=false（记解除人 / 时间）
    .venv/Scripts/python.exe tools/imgfix/lookA_adopt.py adopt|reject|release --by "<原话 / 授权>"
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
for _p in ("packages/schema", "services/agent", "services/api", "services/render_router"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

CAND = ROOT / "data/assetmaster/sheets_v2/candidates/lookA_sleeve_fix/lin_wan_lookA_v2_s202_sleevefix_v4_d92_s20261102.png"
OLD = ROOT / "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202.png"
NEW = ROOT / "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202_sleevefix.png"
QUAR = ROOT / "data/_quarantine/imgfix_lookA_sleeve_20261102"
SC = ROOT / ("data/pipeline/runs/" + _LEGACY + "/assets/sheets_chosen.json")
CHECKS = ROOT / "data/assetmaster/sheet_item_checks.json"
HOLD = ROOT / "data/autopilot/lookA_hold.json"
PJ = _LEGACY
STAMP = "20261102"


def adopt(by: str):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ns_agent import asset_refs as AR
    from ns_api import character_hub as H
    QUAR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OLD, QUAR / OLD.name)                       # 旧图隔离副本（原文件不动：别处按路径引用）
    for f in (ROOT / ("data/pipeline/runs/" + _LEGACY + "/images/refcrops")).glob("lin_wan_lookA_v2_s202_*"):
        (QUAR / "refcrops").mkdir(exist_ok=True)
        shutil.copy2(f, QUAR / "refcrops" / f.name)
    shutil.copy2(SC, SC.with_name(f"sheets_chosen.before_imgfix_sleeve_{STAMP}.json"))
    shutil.copy2(CAND, NEW)
    ck = json.loads(CHECKS.read_text(encoding="utf-8"))
    shutil.copy2(CHECKS, CHECKS.with_name(f"sheet_item_checks.before_imgfix_sleeve_{STAMP}.json"))
    prev = ck.get("lin_wan_lookA")
    ck["lin_wan_lookA"] = {"seed": "202", "verdict": "pass", "how": "契约逐项 + 目检", "by": "IMGFIX（总调度 fredw-2b 亲审采用）",
                           "at": time.strftime("%Y-%m-%dT%H:%M"), "file": str(NEW.relative_to(ROOT)).replace("\\", "/"),
                           "note": "v2_s202 正面栏左臂补深灰外套袖（遮罩外逐像素不变）；两只袖子都在、ΔE 4.49、Q1 0.9622 不变（data/review_pages/lookA_sleeve_fix/check.json）",
                           "model": "qwen-image-2.1", "prev": prev}
    CHECKS.write_text(json.dumps(ck, ensure_ascii=False, indent=1), encoding="utf-8")
    H._actor = lambda request: by
    app = FastAPI()
    app.include_router(H.router)
    r = TestClient(app).post("/api/character-hub/lin_wan/sheet",
                             json={"look": "A", "file": str(NEW.relative_to(ROOT)).replace("\\", "/"), "project": PJ})
    print(r.status_code, r.text[:300])
    if r.status_code != 200:
        raise SystemExit("中枢换设定图失败")
    H._log(by, "lin_wan", "sheet_note", look="A", why="IMGFIX r5：v2_s202 正面栏缺左臂外套袖，局部重绘修复版",
           quarantine=str(QUAR.relative_to(ROOT)).replace("\\", "/"), check="data/review_pages/lookA_sleeve_fix/check.json")
    sheet = AR.sheet_of(PJ, "lin_wan", "A")
    assert sheet == str(NEW.relative_to(ROOT)).replace("\\", "/"), sheet
    out = [AR.sheet_crop(PJ, sheet, p) for p in ("front_nohead", "back_nohead", "half_nohead", "side_nohead")]
    out += [AR.sheet_crop(PJ, sheet, p, "hand") for p in ("front", "half", "side", "back")]
    print("\n".join(out))


def reject(by: str):
    from ns_render import pipeline as P
    hold = json.loads(HOLD.read_text(encoding="utf-8"))
    done = []
    for it in hold["shots"]:
        sid = it["shot"]
        act = (P.load_takes(sid).get("active") or {})
        for kind, stage in (("first", "image"), ("last", "last")):
            n = act.get(stage)
            if not n:
                continue
            r = subprocess.run([sys.executable, str(ROOT / "tools/autopilot/producer.py"), "reject", "--obj", f"{kind}:{sid}", "--n", str(n),
                                "--reason", "林晚造型 A 设定图缺左臂外套袖已修（IMGFIX r5），旧图按新设定图重出（不计次）", "--by", by],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            done.append({"obj": f"{kind}:{sid}", "n": n, "rc": r.returncode, "err": r.stderr[-200:]})
            print(done[-1], flush=True)
    hold.setdefault("log", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by, "rejected": done})
    HOLD.write_text(json.dumps(hold, ensure_ascii=False, indent=1), encoding="utf-8")


def release(by: str):
    hold = json.loads(HOLD.read_text(encoding="utf-8"))
    hold.update(active=False, released_at=time.strftime("%Y-%m-%dT%H:%M:%S"), released_by=by)
    HOLD.write_text(json.dumps(hold, ensure_ascii=False, indent=1), encoding="utf-8")
    print("released")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    RUNS.gate_legacy_tool(None, __file__)        # I-16：必须显式 --run（只认第一季）
    a = sys.argv
    by = a[a.index("--by") + 1] if "--by" in a else "IMGFIX"
    {"adopt": adopt, "reject": reject, "release": release}[a[1]](by)
