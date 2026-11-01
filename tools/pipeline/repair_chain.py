"""R11-3 写作返修链路（WORKFLOW 11-01，规则 K-OPS-W04）：现行生产稿 → qwen_repair_loop（--fix-warn --only-codes QW-A1..A5）→ 校验 → 合并导入计划。

只做系统的事：拼输入、调返修环、核对不变量、写导入计划。**不改写、不评价剧本内容；不调用导入**（导入要总调度批准，
批准后按 import_plan.json 调 POST /api/script-inbox/import，merge 模式只替换输出里的集）。

为什么要这一步（11-01 实查）：现行剧本 data/import/script_v2.json 的各集来自 6 个不同的 md（sources[].episodes：
ep1–2 底稿、ep7 lookfix_ep04_ep07、ep9 lookfix_ep09_10、ep4–6 lookfix_ep03_04_05_06、ep3/8/10 qwch6）。直接拿 23:14 的底稿
（漆皮之下·十日_series10_v1_ep01-10.md）跑返修再合并导入，会把 lookfix / qwch6 的修改整集覆盖回旧版。
所以输入按“每集取现行来源文件里的那一集”拼成一份，只含目标集；来源文件 sha256 必须与 script_v2.json 登记一致。

    .venv/Scripts/python.exe tools/pipeline/repair_chain.py --episodes 7-10            # 默认 --dry-run：只列要返修的镜
    .venv/Scripts/python.exe tools/pipeline/repair_chain.py --episodes 7-10 --run      # 真跑（调写作网关，花 API 费用）
    .venv/Scripts/python.exe tools/pipeline/repair_chain.py --episodes 7 --stub        # 链路自检：桩写作方原样回镜头，不花钱
产物：data/autopilot/repair_chain/<时间>/{input.md, output.md, repair/, verify.json, import_plan.json}
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SCRIPT = ROOT / "data/import/script_v2.json"
OUT_ROOT = ROOT / "data/autopilot/repair_chain"
CODES = ["QW-A1", "QW-A2", "QW-A3", "QW-A4", "QW-A5"]   # 本文件默认码（WORKFLOW）；SCRIPT-RSI 全量返修用 --codes 传 A1–A8、D1


def _load_rl():
    spec = importlib.util.spec_from_file_location("qwen_repair_loop", ROOT / "tools" / "qwen_repair_loop.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(p).as_posix()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _abs(s: str) -> Path:
    p = Path(s.replace("\\", "/"))
    return p if p.is_absolute() else ROOT / p


def episode_sources(script_path: Path = SCRIPT) -> dict[int, dict]:
    """集号 → 现行来源 {path, sha256, sha_ok}（sources 按顺序，后者覆盖前者）"""
    d = json.loads(script_path.read_text(encoding="utf-8"))
    out = {}
    for s in d.get("sources") or []:
        p = _abs(s["path"])
        for e in s.get("episodes") or []:
            out[int(e)] = {"path": p, "sha256": s.get("sha256"),
                           "sha_ok": p.is_file() and _sha(p) == s.get("sha256")}
    return out


def ep_chunks(RL, path: Path) -> tuple[str, dict[int, str]]:
    pre, chunks = RL.split_doc(path.read_text(encoding="utf-8"))
    out = {}
    for c in chunks:
        m = RL.EP_RE.match(RL._norm(c.split("\n", 1)[0]))
        out[int(m.group(1))] = c
    return pre, out


def assemble(RL, eps: list[int], srcs: dict[int, dict]) -> tuple[str, list[dict]]:
    """→ (输入全文, 来源记录)；前言取第一个目标集的来源文件（merge 导入只替换集，不动 globals）"""
    bad = [e for e in eps if e not in srcs or not srcs[e]["sha_ok"]]
    if bad:
        raise SystemExit(f"这些集的现行来源缺失或已被改动（sha256 与 script_v2.json 不符），不拼输入：{bad}")
    pre, parts, rec = None, [], []
    for e in eps:
        p0, ch = ep_chunks(RL, srcs[e]["path"])
        if e not in ch:
            raise SystemExit(f"ep{e:02d} 不在来源 {srcs[e]['path']}")
        pre = pre if pre is not None else p0
        c = ch[e] if ch[e].endswith("\n") else ch[e] + "\n"
        parts.append(c)
        rec.append({"ep": e, "source": _rel(srcs[e]["path"]), "sha256": srcs[e]["sha256"]})
    return pre + "".join(parts), rec


def _shots(path: Path):
    from ns_agent.importer.script_md import import_script
    s = import_script(path)
    return {(e.number, sh.index): sh for e in s.episodes for sh in e.shots}, s


def verify(RL, inp: Path, out: Path, eps: list[int]) -> dict:
    """格式与不变量（不看内容好坏）：能导入、集 / 镜数一致、对白 / 🎙 逐字、时长不变；QW-A 计数前后"""
    res = {"ok": True, "checks": []}

    def add(cid, ok, detail):
        res["checks"].append({"id": cid, "ok": bool(ok), "detail": detail})
        res["ok"] &= bool(ok)
    try:
        a, sa = _shots(inp)
        b, sb = _shots(out)
    except Exception as e:  # noqa: BLE001
        add("parse", False, f"导入解析失败：{e!r}"[:300])
        return res
    add("parse", True, f"输入 {len(sa.episodes)} 集 / 输出 {len(sb.episodes)} 集")
    add("episodes", sorted(e.number for e in sb.episodes) == sorted(eps), f"输出集 {sorted(e.number for e in sb.episodes)}，目标 {sorted(eps)}")
    add("shots", sorted(a) == sorted(b), f"镜数 {len(a)} → {len(b)}")
    diff_d, diff_t = [], []
    for k in sorted(set(a) & set(b)):
        if RL.dialogue_check(a[k], b[k], allow_duration=False):
            diff_d.append(f"ep{k[0]:02d}-S{k[1]}")
        if a[k].duration != b[k].duration:
            diff_t.append(f"ep{k[0]:02d}-S{k[1]}")
    add("dialogue_verbatim", not diff_d, f"对白 / 🎙 / 时长有变的镜：{diff_d or '无'}")
    add("duration", not diff_t, f"时长有变的镜：{diff_t or '无'}")
    def count(path):
        n = {c: 0 for c in CODES}
        pre, chunks = RL.split_doc(path.read_text(encoding="utf-8"))
        wd = out.parent / "verify_work"
        wd.mkdir(exist_ok=True)
        chk = RL.Checker(pre, wd, [])
        for c in chunks:
            e = int(RL.EP_RE.match(RL._norm(c.split("\n", 1)[0])).group(1))
            r = chk.run(c, e)
            si = r.get("shot_issues") or []
            for iss in [i for lst in (si.values() if isinstance(si, dict) else si) for i in lst]:
                if iss.get("rule_id") in n:
                    n[iss["rule_id"]] += 1
        return n
    try:
        res["qw_a_before"], res["qw_a_after"] = count(inp), count(out)
    except Exception as e:  # noqa: BLE001
        res["qw_a_error"] = repr(e)[:300]
    return res


def _run_ids() -> list[str]:
    """登记过的全部 run（tools/autopilot/runs.py；K-OPS-W17 / K-OPS-S01 不写死 run_id），长的优先匹配"""
    if str(ROOT / "tools/autopilot") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RUNS
    return sorted(RUNS.list_runs(status=None) or [RUNS.primary_run()], key=len, reverse=True)


def srcs_name_prefix(rec: list[dict], run_ids: list[str] | None = None) -> str:
    """来源文件名里 _<run_id> 之前的剧名部分 + _<run_id>（例：漆皮之下·十日_series10_v1）；没有 run_id 就取第一段"""
    name = Path(rec[0]["source"]).stem
    for rid in (run_ids if run_ids is not None else _run_ids()):
        i = name.find("_" + rid)
        if i >= 0:
            return name[: i + len(rid) + 1]
    return name.split("_")[0]


def validate_md(path: Path) -> dict:
    """与导入接口同一校验器（validate_qwen_script --json），只取摘要"""
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools/validate_qwen_script.py"), str(path), "--json"],
                       capture_output=True, cwd=ROOT, timeout=900, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    try:
        d = json.loads(r.stdout.decode("utf-8"))
    except ValueError:
        return {"error": r.stderr.decode("utf-8", "replace")[-300:]}
    return {"blocking": d.get("blocking"), "warnings": d.get("warnings"), "episodes": d.get("episodes_found"),
            "qw_a": {k: v for k, v in (d.get("counts") or {}).items() if k in CODES}}


def stub_ask(system: str, user: str) -> str:
    """桩写作方：原样回本镜 Markdown（链路自检用，不改内容、不花钱）"""
    m = re.search(r"当前的完整 Markdown：\n(.*?)\n\n【格式返修】", user, re.S)
    return m.group(1) if m else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episodes", required=True, help="如 7-10 或 2,3,5")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--run", action="store_true", help="真跑返修（调写作网关）")
    g.add_argument("--stub", action="store_true", help="桩写作方原样回镜头：只验链路")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--codes", default=",".join(CODES))
    ap.add_argument("--out-dir")
    a, rest = ap.parse_known_args(argv)
    RL = _load_rl()
    eps = sorted(RL.parse_episodes(a.episodes))
    od = Path(a.out_dir) if a.out_dir else OUT_ROOT / time.strftime("%Y%m%d-%H%M%S")
    od.mkdir(parents=True, exist_ok=True)
    text, rec = assemble(RL, eps, episode_sources())
    inp = od / "input.md"
    inp.write_text(text, encoding="utf-8")
    out = od / "output.md"
    args = [str(inp), "--out", str(out), "--repair-dir", str(od / "repair"), "--fix-warn", "--only-codes", a.codes,
            "--no-export", "--max-rounds", str(a.max_rounds), *rest]
    if not (a.run or a.stub):
        args.append("--dry-run")
    code = RL.main(args, ask=stub_ask if a.stub else None)
    summary = {"schema": "nsfs.repair_chain/1", "at": time.strftime("%F %T"), "episodes": eps, "sources": rec,
               "mode": "run" if a.run else ("stub" if a.stub else "dry-run"), "repair_exit": code,
               "input": _rel(inp)}
    if (a.run or a.stub) and out.exists():
        summary["verify"] = verify(RL, inp, out, eps)
        summary["output"] = _rel(out)
        # 导入接口只收 data/staging_input、data/staging_v3(/merged) 下的 md（ns_api.script_inbox.candidates）：
        # 真跑且校验通过时复制一份到 staging_v3/merged（原名规则：<剧名>_<run_id>_qwA_epXX_..._v3.md），导入计划指向它
        staged = out
        if a.run and summary["verify"]["ok"]:
            pre = srcs_name_prefix(rec)
            staged = ROOT / "data/staging_v3/merged" / f"{pre}_qwA_{'_'.join(f'ep{e:02d}' for e in eps)}_v3.md"
            if staged.exists():
                staged = staged.with_name(staged.stem + time.strftime("_%H%M%S") + ".md")
            staged.write_bytes(out.read_bytes())
            summary["staged"] = _rel(staged)
        summary["validate"] = validate_md(out)
        plan = {"needs_master_approval": True,
                "why": "R11-3：合并导入会改生产剧本 data/import/script_v2.json，须总调度批准（K-OPS-W04）",
                "endpoint": "POST http://127.0.0.1:8800/api/script-inbox/import",
                "body": {"path": _rel(staged), "sha256": _sha(staged), "by": "<总调度批准后填>",
                         "confirm": True, "mode": "merge", "note": f"R11-3 QW-A1..A5 返修 ep{a.episodes}"},
                "stub": a.stub, "verify_ok": summary["verify"]["ok"]}
        if a.stub:
            plan["body"] = None
            plan["why"] = "桩写作方链路自检：内容未改，不导入"
        (od / "import_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (od / "verify.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "sources"}, ensure_ascii=False, default=str)[:1500])
    print(f"产物：{od}")
    return 0 if (not (a.run or a.stub) or summary.get("verify", {}).get("ok")) else 1


if __name__ == "__main__":
    sys.exit(main())
