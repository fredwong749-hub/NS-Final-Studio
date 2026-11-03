"""ASSETMASTER 造型一致性返修（内容层交写作模型，关推理；台词 / 独白逐字不动）。

输入：某集 P4 稿 + P1 造型登记 + scan.py 盘出的该集造型问题（或 --issue 手写）。
流程：备份原稿 → 写作模型（llm_config 的 script_write，reasoning=off）按登记改造型描述 → 系统核对
      （对白 / 独白 / 声音行逐字一致、镜数不变）→ check_chain 校验 → 通过才落盘到 epNN/P4_epNN.md。
不导入剧本；导入由 merge_import 段做（单集 merge，导入前备份 script_v2.json）。

用法：.venv/Scripts/python.exe tools/assetmaster/look_fix.py --ep 7 [--ep 4] [--issue "…"] [--dry]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
sys.path[:0] = [str(ROOT / "tools" / "pipeline"), str(ROOT / "services" / "api"), str(ROOT / "services" / "agent"),
                str(ROOT / "tools" / "assetmaster"), str(ROOT / "services" / "recipes"), str(ROOT / "services" / "schema")]
RUN = ROOT / "data" / "pipeline" / "runs" / _LEGACY
KEEP = ("**对白**", "**独白**", "**旁白**", "**VO**", "**sound**", "**时长**", "**衔接**", "**人物**", "**站位**")

SYS_EXTRA = """
【本轮任务：造型一致性返修（ASSETMASTER）】
只改与造型登记不一致的造型描述（服装 / 鞋 / 饰品 / 妆的措辞），其余一字不动：
- 对白、独白、sound、时长、衔接、人物、站位行逐字保留；镜头数量、镜号、动作与情节不变。
- 每个 **造型｜<角色>** 行必须从登记造型里选一套，服装 / 鞋 / 饰品 / EN 逐字照抄登记；同集换装用 **造型｜<角色>｜镜N起**。
- 镜头 img / motion / HN提示词 里写到的衣物、鞋、饰品必须与该镜所用登记造型一致（可以只写景别看得见的部件）。
- 输出整集完整稿（从 "## epNN《" 开始），不要解释。
"""


def blocks_of(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ln in text.splitlines():
        for k in KEEP:
            if ln.startswith(k):
                out.setdefault(k, []).append(ln.strip())
    return out


def shot_count(text: str) -> int:
    return len(re.findall(r"^\*\*镜\d+｜img", text, re.M))


def looks_block() -> str:
    p = (RUN / "ep01" / "prompts" / "P3-P4.fixpass.user.md").read_text(encoding="utf-8")
    i = p.find("【本集人物登记造型")
    return p[i:].strip() if i >= 0 else json.dumps(json.loads((RUN / "P1_looks.json").read_text(encoding="utf-8")),
                                                  ensure_ascii=False)


def issues_for(ep: int) -> list[str]:
    inv = json.loads((ROOT / "data" / "assetmaster" / "inventory.json").read_text(encoding="utf-8"))
    keep = ("表头造型偏离登记", "同造型不同鞋（表头）", "同造型不同鞋（镜头）", "镜头混入其他造型单品")
    out = []
    for i in inv["issues"]:
        if i.get("ep") == ep and i["type"] in keep:
            out.append(f"- {i['type']}｜{i.get('shot', '表头')}｜{i.get('char', '')}｜{i['detail']}｜建议：{i.get('fix', '')}")
    return out


def run_ep(ep: int, extra: list[str], dry: bool, budget: float) -> dict:
    d = RUN / f"ep{ep:02d}"
    src = d / f"P4_ep{ep:02d}.md"
    orig = src.read_text(encoding="utf-8")
    probs = issues_for(ep) + [f"- {x}" for x in extra]
    sysmsg = (d / "prompts" / "P3-P4.system.md").read_text(encoding="utf-8") + "\n" + SYS_EXTRA
    user = (f"第 {ep} 集已写好，下面是整集稿。请按登记造型做造型一致性返修。\n\n{looks_block()}\n\n"
            f"【系统盘出的本集造型问题】\n" + "\n".join(probs) + f"\n\n【原稿】\n{orig}")
    (d / "prompts").mkdir(exist_ok=True)
    (d / "prompts" / "P3-P4.lookfix.user.md").write_text(user, encoding="utf-8")
    if dry:
        return {"ep": ep, "status": "dry", "issues": probs}
    import run_chain as RC
    bak = d / f"v3_pre_lookfix_{time.strftime('%Y%m%d_%H%M%S')}"
    bak.mkdir()
    shutil.copy2(src, bak / src.name)
    rep_all = []
    msgs = [{"role": "user", "content": user}]
    for rnd in range(3):
        res = RC.call_llm(sysmsg, msgs, max_tokens=24000, reasoning=False, tag="assetmaster-lookfix", budget=budget,
                          meta={"link": "P3-P4-lookfix", "round": rnd, "run": f"{_LEGACY}/ep{ep:02d}"})
        txt = res["content"]
        (d / "raw").mkdir(exist_ok=True)
        (d / "raw" / f"P3-P4.lookfix.r{rnd}.txt").write_text(txt, encoding="utf-8")
        i = txt.find(f"## ep{ep:02d}")
        body = txt[i:].strip() if i >= 0 else txt.strip()
        head = orig[:orig.find(f"## ep{ep:02d}")]
        cand = head + body + "\n"
        errs = []
        ob, nb = blocks_of(orig), blocks_of(cand)
        for k in ("**对白**", "**独白**", "**旁白**", "**VO**", "**时长**"):   # sound 里拟音随造型可改，改动进日志由总调度看
            if ob.get(k, []) != nb.get(k, []):
                errs.append(f"{k} 行与原稿不一致（必须逐字保留）")
        if shot_count(orig) != shot_count(cand):
            errs.append(f"镜头数 {shot_count(cand)} ≠ 原稿 {shot_count(orig)}")
        tmp = d / f"_lookfix_cand_ep{ep:02d}" / src.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_text(cand, encoding="utf-8")
        for p3 in d.glob("P3_*.json"):
            shutil.copy2(p3, tmp.parent / p3.name)
        cc = subprocess.run([sys.executable, str(ROOT / "tools" / "pipeline" / "check_chain.py"), "--artifact", str(tmp), "--json"],
                            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        try:
            chk = json.loads(cc.stdout)
        except Exception:
            chk = {"blocking": -1, "issues": [{"message": cc.stderr[-500:]}]}
        if chk.get("blocking"):
            errs += [f"[{x.get('rule')}] {x.get('message', '')[:160]}" for x in chk.get("issues", []) if x.get("level") == "block"][:12]
        # 造型复扫
        rep_all.append({"round": rnd, "errors": errs, "chain_blocking": chk.get("blocking"), "usd": round(res["usd"], 5)})
        if not errs:
            src.write_text(cand, encoding="utf-8")
            shutil.rmtree(tmp.parent, ignore_errors=True)
            return {"ep": ep, "status": "ok", "backup": str(bak.relative_to(ROOT)), "rounds": rep_all, "issues": probs}
        msgs += [{"role": "assistant", "content": txt},
                 {"role": "user", "content": "系统核对没通过，请修正后重新输出整集完整稿：\n" + "\n".join(f"- {e}" for e in errs)}]
    return {"ep": ep, "status": "needs_writer", "backup": str(bak.relative_to(ROOT)), "rounds": rep_all, "issues": probs}


def main(argv=None) -> int:
    argv = RUNS.gate_legacy_tool(argv, __file__)
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", type=int, action="append", required=True)
    ap.add_argument("--issue", action="append", default=[])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--budget", type=float, default=3.0)
    a = ap.parse_args(argv)
    out = [run_ep(e, a.issue, a.dry, a.budget) for e in a.ep]
    log = ROOT / "data" / "assetmaster" / "look_fix_log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(dict(r, at=time.strftime("%Y-%m-%dT%H:%M:%S")), ensure_ascii=False) + "\n")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if all(r["status"] in ("ok", "dry") for r in out) else 1


if __name__ == "__main__":
    sys.exit(main())
