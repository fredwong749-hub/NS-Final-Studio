"""V2 金样编译工具（PROMPTFIX 11-02 起；PRODMERGE-O 11-03 收薄，L-151）：只剩两个只读入口，不出图、不记账。

    python tools/promptfix/golden_v2.py --compile --shot N [--episode E]   # 只编译 + preflight，打印提示词与 trace
    python tools/promptfix/golden_v2.py --summary --shot N [--episode E]   # 只编译，一行指纹（system_version verify 两台比对用）

出图 / 验收已并回 V1 主干：出图走 tools/autopilot/producer.py（--run <剧>，帧只记 data/renders/<剧>/epNN/SN/takes.json 一本账），
出图后判定（Q9 补跑、anomaly、合并看图逐条 + 年龄 + OCR、pass / reject / retry 三态）在 ns_agent.gen_contract.accept（postflight.accept）。
--render / --rejudge 已退役（退出码 3，指向 producer）；data/ab/v2_golden_epNN 不再有新写入。
必须指定 --shot（ISS-1103-005000-2af2）：不带镜号 = 失败关闭（退出码 2）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", "tools/vqa", "tools/gen_contract", ""):
    sys.path.insert(0, str(ROOT / p))

def _current_run() -> str:
    """剧 id 从 runs.current_run 取（arch_scan hard_run：不写死剧 id）；本工具只给资产包模式（V2）的剧用"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("runs_golden", ROOT / "tools" / "autopilot" / "runs.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return os.environ.get("NS_RUN") or m.current_run(ROOT)


PROJECT = _current_run()
SHOT = None                         # --shot N：从当前剧导入稿（runs.import_path）取第 N 镜，走同一个编译入口与契约（总调度 11-02）
SID = None                          # 镜号定了才有（{run}-ep01-S{N}）
NEED_SHOT = ("必须指定镜号：golden_v2 只出当前剧导入稿里的指定镜（--shot N），V2 剧没有默认金样，也不退回任何夹具"
             "（ISS-1103-005000-2af2 / L-126）")


class ShotRequired(SystemExit):
    """没给镜号：失败关闭（退出码 2，信息写明必须指定镜号）"""
    def __init__(self):
        super().__init__(NEED_SHOT)
        self.code = 2


def require_shot() -> int:
    if not SHOT:
        sys.stderr.write(NEED_SHOT + chr(10))
        raise ShotRequired()
    return int(SHOT)


def _atomic_write(path, text: str) -> None:
    """先写临时文件再 os.replace（arch_scan nonatomic_json）"""
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


EPISODE = 1                          # --episode N（默认第 1 集）
_READY: dict = {}


def shot_ready_row(n: int, episode: int | None = None) -> dict:
    """按镜就绪（GOLDEN-O 11-03）：口径 = tools/master/episode_ready.check（preflight I2–I5 + character_gaps 同一份）→ shot_readiness。
    同一进程同一集只算一次"""
    ep = int(episode or EPISODE)
    if (PROJECT, ep) not in _READY:
        import importlib.util as _u
        sp = _u.spec_from_file_location("episode_ready_golden", ROOT / "tools" / "master" / "episode_ready.py")
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        _READY[(PROJECT, ep)] = m.check(PROJECT, ep).get("shot_ready") or []
    return next((r for r in _READY[(PROJECT, ep)] if int(r.get("index") or 0) == int(n)), {"index": n, "ready": False, "blockers": ["就绪检查里没有这一镜"]})


def load_imported(n: int, episode: int | None = None):
    """导入稿里第 episode 集（默认 --episode）的第 n 镜。成人镜拒绝（只由项目方触发）；多人镜照常编译（PRODMERGE-O：去掉“只出祁念单人镜”写死）"""
    import importlib.util as _u
    from ns_schema.script import ScriptImport
    sp = _u.spec_from_file_location("runs_golden2", ROOT / "tools" / "autopilot" / "runs.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    s = ScriptImport.model_validate(json.loads(m.import_path(PROJECT, ROOT).read_text(encoding="utf-8")))
    want = int(episode or EPISODE)
    ep = next(e for e in s.episodes if int(e.number) == want)
    sh = next(x for x in ep.shots if int(x.index) == n)
    if sh.adult:
        raise SystemExit(f"拒绝：镜 {n} 带成人标记 {sh.adult_reasons}（成人镜由项目方触发）")
    return s, ep, sh


def compile_job():
    from ns_agent import frame_job as FJ
    os.environ["NS_RUN"] = PROJECT
    s, ep, sh = load_imported(require_shot())
    job = FJ.build_first(PROJECT, ep, sh, s.globals)
    if job.get("adult") or job.get("route") == "local_only":
        raise SystemExit(f"拒绝：成人 / 本地专用造型不由系统出图（{job.get('adult_reasons') or job.get('route_reasons')}）")
    return job


def preflight(job, lane):
    from ns_agent.gen_contract import preflight as PF
    req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
    req.update(kind="image", project=PROJECT, framing_project=PROJECT, shot_id=SID, lane=lane)
    return PF.check(req)


def _g(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


def check_items(job: dict, shot, looks: dict | None = None) -> list[str]:
    """本镜看图核对项（实现在共用验收 ns_agent.gen_contract.accept.check_items；这里只绑定当前剧）"""
    from ns_agent.gen_contract import accept as ACC
    return ACC.check_items(job, shot, looks, PROJECT)


def vlm_question(items: list[str]) -> str:
    return ("按下面的要求逐条核对这张图，每条回答“符合 / 不符合 + 一句理由”，最后一行写“总结：全部符合”或“总结：有不符合”。" + chr(10)
            + "；".join(f"{n}. {t}" for n, t in enumerate(items, 1)) + "。")


def ensure_q9(post: dict, img: str, job: dict) -> dict:
    """转调共用验收（cast_v2 等旧调用方兼容）"""
    from ns_agent.gen_contract import accept as ACC
    return ACC.ensure_q9(post, img, job)


def set_shot(n: int, episode: int = 1) -> None:
    """设定当前镜（CLI 用）。AB = 旧金样账路径（只给旧测试 / 迁移核对读，本工具不再写）"""
    global SHOT, SID, EPISODE, AB
    EPISODE = int(episode)
    SHOT, SID = int(n), f"{PROJECT}-ep{EPISODE:02d}-S{int(n)}"
    AB = ROOT / "data" / "ab" / f"v2_golden_ep{EPISODE:02d}"


AB = None


def judge_bundle(post: dict, an: dict, bundle: dict):
    """转调共用验收（实现已并进 ns_agent.gen_contract.accept）"""
    from ns_agent.gen_contract import accept as ACC
    return ACC.judge_bundle(post, an, bundle)


def verdict(post: dict, lab: dict, bundle: dict):
    from ns_agent.gen_contract import accept as ACC
    return ACC.verdict(post, lab, bundle)


def q9_timeout(post: dict) -> bool:
    from ns_agent.gen_contract import accept as ACC
    return ACC.q9_timeout(post)


RETIRED = ("--render / --rejudge 已退役（PRODMERGE-O，L-151）：出图走 producer.py --run <剧>（帧记 takes.json），"
           "验收走 ns_agent.gen_contract.accept")


def summary_of(job: dict, pf) -> dict:
    """编译结果指纹（system_version verify：两台同一镜 dry-run 必须一致）：prompt / refs 的 sha、参考图逐个 sha、路由、成人标记、preflight 结论"""
    import hashlib
    tr = job.get("compile_trace") or {}
    return {"project": PROJECT, "shot": tr.get("shot") or SID, "prompt_sha": hashlib.sha256((job.get("prompt") or "").encode("utf-8")).hexdigest()[:16],
            "refs": [{"file": r.get("file"), "sha": r.get("sha")} for r in tr.get("refs") or []], "refs_sha": tr.get("refs_sha"),
            "faces": tr.get("faces"), "style_preset": tr.get("style_preset"), "route": job.get("route"), "adult": bool(job.get("adult")),
            "preflight_ok": bool(pf.ok), "preflight_fail": list(pf.reasons())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--summary", action="store_true",
                    help="只编译 + preflight，输出一行 GOLDEN_SUMMARY {json}（system_version verify 两台比对用，不出图）")
    ap.add_argument("--render", action="store_true", help="已退役（退出码 3）")
    ap.add_argument("--rejudge", action="store_true", help="已退役（退出码 3）")
    ap.add_argument("--lane", default="gpu36:0", help="preflight I12 判本地专用资产用的道（不出图）")
    ap.add_argument("--seed", type=int, help="已无用（保留参数兼容）")
    ap.add_argument("--shot", type=int, help="从当前剧导入稿取第 N 镜")
    ap.add_argument("--episode", type=int, default=1, help="第几集（默认 1）")
    a = ap.parse_args(argv)
    if not a.shot:
        sys.stderr.write(NEED_SHOT + chr(10))
        return 2
    if a.render or a.rejudge:
        sys.stderr.write(RETIRED + chr(10))
        return 3
    set_shot(a.shot, a.episode)
    job = compile_job()
    pf = preflight(job, a.lane)
    if a.summary:
        print("GOLDEN_SUMMARY " + json.dumps(summary_of(job, pf), ensure_ascii=False, sort_keys=True))
        return 0
    print(job["prompt"])
    print(json.dumps({"refs": job["refs"], "trace": job["compile_trace"], "preflight_ok": pf.ok, "fail": pf.reasons()},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
