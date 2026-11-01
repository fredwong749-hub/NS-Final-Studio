"""给项目方看的人话（BGM10，UIAUDIT P2）：
- 选中理由：审听模型按 config/prompts/bgm_reason_plain.md 改写 → meta.json chosen.reason_plain / reason_evidence（原 reason 不动）。
- 候选提示：系统自己生成的提示（agent.gate 的 flags）直接在源头给人话版本 → candidate.flags_plain。

    .venv/Scripts/python.exe tools/bgm/plain.py --eps 1-10 [--force]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm as L  # noqa: E402
from deliver import ROOT, jload, jsave, load_cfg, out_dir  # noqa: E402

# 人话里不许出现的东西（也给 check_plain / 测试用）
FORBID = re.compile(r"[A-Za-z]+_[A-Za-z_]+|\b(?:energy|clap|vocal|tempo|gate|onset|centroid|brief|target|BPM|LUFS|dBTP|dB|Hz)\b"
                    r"|\d+\.\d+|闸门|[（(]\s*r?\s*[)）]", re.I)
# 句子里有“空位”（数字被删后留下的碎片）
# 删数字留下的空位都带空白：“最高值 相当”“的 是 60 的 倍”“（r1_c1 仅）”；“是反的。”这种正常句尾不算
DANGLING = re.compile(r"(?:的|与|和|为|是|仅|约|从|至|到|对|达|比|在)\s+(?:[，。；、）)！？]|$)"
                      r"|\s(?:倍|相当|仅|左右)(?=[\s，。；、）)]|$)|的\s+(?:是|为|与|和)\s|仅\s*[）)]|[（(]\s*[，、；]|[\u4e00-\u9fff]\s+[，。；、！？]|\S\s{2,}\S")


def flag_plain(flag: str) -> str:
    """agent.gate 产生的提示 → 人话（源头确定性生成，不经模型）"""
    if flag.startswith("tempo_off"):
        return "测出来的速度和说明对不上（慢铺底常被测成倍速或半速，不一定真偏）"
    if flag.startswith("energy_weak"):
        return "强弱起伏和说明里的走向贴得不紧"
    return "有一项自动提示，原文见悬停"


def fail_plain(fail: str) -> str:
    for k, v in (("vocals", "有人声"), ("clipping", "有削波"), ("silence_gap", "中间有较长的空白段"),
                 ("too_short", "比这一集短"), ("clap_low", "听起来和说明不像"), ("energy_inverse", "强弱起伏和说明正好相反"),
                 ("error", "生成失败")):
        if fail.startswith(k):
            return v
    return "没过自动检查"


def check_text(s: str) -> list[str]:
    bad = []
    if not s or not s.strip():
        bad.append("空")
    if len(s) > 200:
        bad.append(f"太长（{len(s)} 字）")
    m = FORBID.search(s or "")
    if m:
        bad.append(f"有内部用语或小数：{m.group(0)!r}")
    d = DANGLING.search(s or "")
    if d:
        bad.append(f"句子有空位：{d.group(0)!r}")
    return bad


def rewrite_reason(ep: int, reason: str, cfg: dict) -> dict:
    system = (ROOT / "config" / "prompts" / "bgm_reason_plain.md").read_text(encoding="utf-8")
    user = f"第 {ep} 集，选中候选的原理由：\n{reason}"
    err = ""
    for attempt in range(3):
        res = L.chat(system, user + err, cfg=cfg, max_tokens=1500,
                     meta={"link": "P4-BGM", "episode": ep, "step": "reason_plain", "attempt": attempt})
        try:
            d = L.extract_json(res["content"])
            rp = str(d.get("reason_plain") or "").strip()
        except ValueError as e:
            err, rp, d = f"\n\n上一次不是 JSON（{e}），只输出 JSON。", "", {}
            continue
        bad = check_text(rp)
        if not bad:
            return {"reason_plain": rp, "reason_evidence": str(d.get("evidence") or ""), "model": res["model"],
                    "attempts": attempt + 1, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        err = f"\n\n上一次的 reason_plain 不合格：{'；'.join(bad)}。原文：{rp}\n按要求重写，只输出 JSON。"
    raise RuntimeError(f"ep{ep:02d} 人话改写 3 次不合格：{err.strip()}")


def plain_episode(ep: int, cfg: dict | None = None, force: bool = False, log=print) -> dict:
    cfg = cfg or load_cfg()
    mp = out_dir(cfg) / f"ep{ep:02d}" / "meta.json"
    st = jload(mp)
    if not st:
        return {}
    for c in st.get("candidates") or []:
        c["flags_plain"] = [flag_plain(f) for f in c.get("flags") or []]
        c["gate_fail_plain"] = [fail_plain(f) for f in c.get("gate_fail") or []]
    ch = st.get("chosen") or {}
    if ch.get("reason") and (force or not ch.get("reason_plain")):
        r = rewrite_reason(ep, ch["reason"], cfg)
        ch.update(reason_plain=r["reason_plain"], reason_evidence=r["reason_evidence"],
                  reason_plain_by={"model": r["model"], "prompt": "config/prompts/bgm_reason_plain.md", "at": r["at"]})
        log(f"ep{ep:02d} 人话理由：{r['reason_plain']}")
    jsave(mp, st)
    return st


def main(argv=None) -> int:
    from report import parse_eps  # noqa: PLC0415
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", default="1-10")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_cfg()
    bad = 0
    for ep in parse_eps(a.eps):
        try:
            plain_episode(ep, cfg, force=a.force)
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"ep{ep:02d} 失败：{e}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
