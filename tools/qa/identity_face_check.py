"""身份脸断言（DISTILL 11-02，总调度派；L-086；规则 K-OPS-X07）：对 config/pipeline/runs.json 里每个 run 的每个角色，
用生产入口 ns_agent.asset_refs.face_of(run, cid) 解析身份脸，结果必须等于项目方定的那张。

起因：同一类事故今晚出了两次——01:24 服务器缺 face_overrides，47/50 镜身份脸解析成 lin_wan_face_ref2va；
03:0x 第二季 series10_s2 继承链漏了 face_overrides，又解析成 ref2va。preflight 只查“有没有”，不查“是不是那张”。

判定（gates.identity_faces）：
  pinned   项目方定死的脸（林晚 = lin_wan_face_hd_A_s202，L-086）：任何 run 只要角色里有这个人，必须解析成这张，sha 也要一致
  inherit  有 inherits 的子 run：继承来的每个角色，解析结果必须和父 run 一致（防继承链漏配置）
接入：config/owner_decisions.yaml D-AST-86d（type: cmd）→ decision_check（system_version cut 闸门跑它）；SENTINEL 每拍调 check()。

  python tools/qa/identity_face_check.py [--json]     退出码 0 = 全部一致，1 = 有不一致
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "tools/autopilot"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def _sha(rel: str | None) -> str | None:
    if not rel or not (ROOT / rel).is_file():
        return None
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def pinned_faces(root: Path = ROOT) -> dict[str, str]:
    doc = yaml.safe_load((root / "config/policies/gates.yaml").read_text(encoding="utf-8")) or {}
    return dict(((doc.get("items") or {}).get("identity_faces") or {}).get("value", {}).get("pinned") or {})


def runs(root: Path = ROOT) -> list[str]:
    """runs.json 的全部 run + config/recipes/asset_refs.json 里有 inherits 的项目（WORKFLOW 转办 11-02：继承链上的项目都要核）"""
    # fail-closed（K-OPS-X07 / arch_scan silent_read）：任何登记文件读不到或解析失败都直接抛出，main() 判失败、退出码 1；
    # 只有 runs.json 尚未建立（多剧并行前的旧环境）才退回 run.json 的 primary
    reg_p = root / "config/pipeline/runs.json"
    if reg_p.exists():
        reg = json.loads(reg_p.read_text(encoding="utf-8"))
        out = list((reg.get("runs") or {}).keys()) or [reg.get("primary")]
    else:
        out = [json.loads((root / "config/pipeline/run.json").read_text(encoding="utf-8"))["run_id"]]
    projs = json.loads((root / "config/recipes/asset_refs.json").read_text(encoding="utf-8")).get("projects") or {}
    out += [k for k, v in projs.items() if (v or {}).get("inherits") and k not in out]
    out = [r for r in out if r]
    if not out:
        raise ValueError("没有任何 run 可核（runs.json / run.json 为空）")
    return out


def check(face_of=None, project_cfg=None, project_chain=None, run_ids: list[str] | None = None, pinned: dict | None = None,
          sha=_sha) -> dict:
    """→ {ok, runs, rows: [{run, cid, got, want, why}], bad: [...]}；参数可注入（测试）"""
    if face_of is None:
        from ns_agent import asset_refs as AR
        face_of, project_cfg, project_chain = AR.face_of, AR.project_cfg, AR.project_chain
    run_ids = run_ids if run_ids is not None else runs()
    pinned = pinned if pinned is not None else pinned_faces()
    rows, bad = [], []
    for run in run_ids:
        cfg = project_cfg(run) or {}
        cast = sorted(set((cfg.get("faces") or {}).keys()) | {c for c in pinned if c in (cfg.get("faces") or {})})
        chain = project_chain(run) or [run]
        parent = chain[1] if len(chain) > 1 else None
        for cid in cast:
            got = face_of(run, cid)
            want, why = None, None
            if cid in pinned:
                want = pinned[cid]
                if got != want:
                    why = f"项目方定的身份脸是 {want}（L-086），实际解析成 {got}"
                elif sha(got) is None:
                    why = f"{got} 文件不存在"
            elif parent:
                want = face_of(parent, cid)
                if got != want:
                    why = f"继承自 {parent} 应为 {want}，实际 {got}（继承链漏配置？）"
            r = {"run": run, "cid": cid, "got": got, "want": want, "ok": why is None, "why": why}
            rows.append(r)
            if why:
                bad.append(r)
    return {"ok": not bad, "runs": run_ids, "checked": len(rows), "rows": rows, "bad": bad}


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    try:
        res = check()
    except Exception as e:  # noqa: BLE001 —— fail-closed：读不到 / 解析失败 = 闸门不过
        print(f"身份脸断言：无法完成检查（{type(e).__name__}: {e}）→ 判失败")
        return 1
    if not res["checked"]:
        print("身份脸断言：0 个角色被检查 → 判失败（没测到 ≠ 通过）")
        return 1
    if "--json" in argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"身份脸断言：{len(res['runs'])} 个 run / {res['checked']} 个角色，不一致 {len(res['bad'])}")
        for b in res["bad"]:
            print(f"  ❌ {b['run']} {b['cid']}：{b['why']}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
