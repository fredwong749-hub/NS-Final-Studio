"""night 合成之后的导演收尾（DIRECTOR，总调度 fredw-2b 11-02 批准接进 night；K-EDT-816）：
post_pass（调色 + 音效 + 响度）→ film_score（成片分，不跑看图模型）→ lip_redo（K-EDT-805 口型重出单）。
每步独立，失败只记录、不影响原成片。开关 config/post/director.json（enabled + post_pass / film_score / lip_redo）。
只用相对 ROOT 的路径（笔记本 / 服务器同一套，FACTORY 本机闭环）；服务器上 nice + 线程 4（K-OPS-V13）。

  python tools/director/finish.py <成片.mp4> [--script S]
stdout 最后一行 JSON：{post, post_timeline, film_score, film_score_post, lip_redo:[…], errors:[…]}
"""
from __future__ import annotations

import os as _os
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "director"))
sys.path.insert(0, str(ROOT / "services" / "post"))


def main(argv):
    from ns_post import director as DIRP
    v = Path(argv[0])
    v = v if v.is_absolute() else ROOT / v
    script = Path(argv[argv.index("--script") + 1]) if "--script" in argv else ROOT / "data/import/script_v2.json"
    tlp = v.with_suffix(".timeline.json")
    res = {"input": str(v), "post": None, "lip_redo": [], "errors": [], "enabled": DIRP.enabled()}
    if not DIRP.enabled():
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if hasattr(_os, "nice"):
        try:
            _os.nice(15)
        except OSError:
            pass
    if DIRP.enabled("lip_redo"):
        try:
            import lip_redo as LR
            res["lip_redo"] = LR.record(tlp)
        except Exception:  # noqa: BLE001
            res["errors"].append("lip_redo: " + traceback.format_exc()[-300:])
    out = v.with_name(v.stem + "_post.mp4")
    if DIRP.enabled("post_pass"):
        try:
            import post_pass as PP
            PP.run(v, tlp, script, out)
            res["post"], res["post_timeline"] = str(out), str(out.with_suffix(".timeline.json"))
        except BaseException:  # noqa: BLE001 —— 含 SystemExit（剧本镜数不符）
            res["errors"].append("post_pass: " + traceback.format_exc()[-300:])
    if DIRP.enabled("film_score"):
        import film_score as FS
        for key, path in (("film_score", v), ("film_score_post", out if res["post"] else None)):
            if not path:
                continue
            try:
                r = FS.score(path, path.with_suffix(".timeline.json"), path.stem, False, "night 自动打分")
                res[key] = {"total_50": r["total_50"], "coverage": r["coverage"], "lowest": r["lowest"]}
            except Exception:  # noqa: BLE001
                res["errors"].append(f"{key}: " + traceback.format_exc()[-300:])
    res["steps"] = [{"step": k, "decider": "code", "rule": r} for k, r in
                    (("lip_redo", "K-EDT-805"), ("post_pass", "K-EDT-801/802/803"), ("film_score", "K-REV-801"))]
    res["delivery_gate"] = delivery_gate(res)
    print(json.dumps(res, ensure_ascii=False, default=str))
    return 0


def delivery_gate(res: dict) -> dict:
    """交付闸门（decider = code，K-EDT-817）：后期版能交付 = 后期跑成功 + 成片分不低于原合成版 + 没有口型重出镜 + 无报错。
    不过 → 交付原合成版并列原因（成片本来只出预览，项目方已定）"""
    why = []
    if not res.get("post"):
        why.append("后期没产出")
    a, b = (res.get("film_score") or {}).get("total_50"), (res.get("film_score_post") or {}).get("total_50")
    if a is not None and b is not None and b < a:
        why.append(f"后期版成片分下降 {a} → {b}")
    if res.get("lip_redo"):
        why.append("有口型重出镜：" + "、".join(r.get("shot", "?") for r in res["lip_redo"]))
    if res.get("errors"):
        why.append(f"{len(res['errors'])} 个步骤报错")
    return {"decider": "code", "rule": "K-EDT-817", "deliver": "post" if res.get("post") and not any("下降" in w or "后期" in w for w in why) else "raw",
            "final_ok": not why, "why": why}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
