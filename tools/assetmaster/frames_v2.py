"""ASSETMASTER 第 3 步：series10 首帧 + 尾帧全量重出（项目方授权"全部默认同意"，总调度 2026-11-01 夜）。

配方 = frame_v9：徕卡 S★（Turbo 8 步、krea2 0.5、无 lin_wan_qi、1.5× 出图 + lanczos 缩回 + USM），参考 = REFLOCK 槽位规划
（ns_agent.asset_refs.plan_for：身份脸 > 造型设定图 / 去头 > 景别单品 / 参考板 > 场景底图），提示词 = 槽位标注 + 编译器输出
（与 tools/gen_contract/reflock_v9.py 的 vR 同一路径：imgfix_ab.build sstar no_suffix）。
闸门：
  preflight（ns_agent.gen_contract.preflight）不过 → 不提交，记"阻断"；
  postflight（remote_score 原地打分 + postflight.evaluate Q1–Q7）不过 → 只换 seed 重出（≤3 次），仍不过标"不合格"，不冒充通过；
  首帧通过 → register_takes 登记（标签"新配方"）并设为当前 → 用该首帧 + 身份脸出尾帧（compiler last_prompt），同样过闸；
  一集全部首尾帧结束 → 写 data/review_pages/series10_frames_v2/epNN/（契约逐项表 + 接触印样），发总调度 / 通知 VIDEO10。
状态：data/assetmaster/frames_v2/state.json（断点续跑）；日志 frames_v2.log。

用法：.venv/Scripts/python.exe tools/assetmaster/frames_v2.py run [--eps 1-10] [--lanes gpu33:0,gpu33:1,gpu33:3,gpu36:0,gpu36:1,gpu36:2]
      .venv/Scripts/python.exe tools/assetmaster/frames_v2.py jobs [--eps 1]      # 只建作业 + preflight，不出图
      .venv/Scripts/python.exe tools/assetmaster/frames_v2.py page --eps 1         # 重写某集审阅页
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
for p in ("services/render_router", "services/agent", "services/api", "packages/schema", "tools/pipeline", "tools/series10_imggen",
          "tools/gen_contract", "services/recipes"):
    sys.path.insert(0, str(ROOT / p))

RUN = ROOT / ("data/pipeline/runs/" + _LEGACY)
OUT = ROOT / "data/assetmaster/frames_v2"
STATE = Path(__import__("os").environ.get("AM_FRAMES_STATE") or OUT / "state.json")
LOG = OUT / "frames_v2.log"
PAGES = ROOT / "data/review_pages/series10_frames_v2"
PROJECT = _LEGACY
SEEDS = (20261101, 20261102, 20261103, 20261104)        # 首次 + 最多 3 次重出（只换 seed）
LANES_ALL = {"gpu33:0": "http://127.0.0.1:18188", "gpu33:1": "http://127.0.0.1:18189", "gpu33:3": "http://127.0.0.1:18191",
             "gpu36:0": "http://127.0.0.1:18288", "gpu36:1": "http://127.0.0.1:18289", "gpu36:2": "http://127.0.0.1:18290"}
LABEL = "新配方"
# 契约门槛改动版本：每改一次（REFLOCK / 总调度），只因“改过的项”不过的旧尝试用新代码重打一次分（不重出、不计次）
CONTRACT_TAG = "2026-11-01e"          # d：Q4 只记录、Q5 停肢体比例子规则、Q2 鞋分三段；e：Q2 鞋加装饰探针 embellished_max 0.6→0.7
RETUNED = {"Q2", "Q4", "Q5", "Q8"}    # 历次改过的项（累计）
RETUNED_NOW = {"Q2"}                  # 本版本改动的项：已按旧版本重打过的尝试，只有还挂在这些项上的才再打


def _retunable(a_) -> bool:
    blk = set((a_.get("postflight") or {}).get("blocking") or [])
    if not (a_.get("file") and blk and blk <= RETUNED) or a_.get("rescored_ver") == CONTRACT_TAG:
        return False
    return a_.get("rescored_ver") is None or bool(blk & RETUNED_NOW)
PF_THREADS = 6
lock = threading.RLock()


def log(*a):
    s = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(s, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(s + "\n")


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def save(st):
    with lock:
        OUT.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(STATE)


TWO_PERSON_BOARD = True


def two_person_board(sr, plan):
    """总调度 11-01：双人镜两张脸各占一槽（Q1），其余（两人的造型图 / 景别可见单品 / 场景底图）合成一张参考板占第 3 槽，
    服装与鞋不再只靠文字（项目方头号抱怨）。参考板 = ns_agent.asset_refs.make_board（脸不进板；设定图已去头）"""
    from ns_agent import asset_refs as AR
    # W20（ep01-S1 三人镜）：三张脸被 asset_refs 合成一个 faceboard 槽；只认 kind=="face" 会把脸板丢掉 → preflight I2 挡。脸板同样是脸槽
    faces = [sl for sl in plan.slots if sl.kind in ("face", "faceboard")]
    tiles = [(r.file, r.label) for r in sr.refs if r.role != "face" and r.file][:6]
    if not tiles or len(faces) + 1 > plan.capacity:
        return plan
    board = AR.make_board(sr.project if hasattr(sr, "project") else PROJECT, tiles)
    n = len(faces) + 1
    line = (f"图{n}是本镜参考板（{len(tiles)} 格，按格号）：" + "；".join(f"格{i}是{lab}" for i, (_, lab) in enumerate(tiles, 1)) +
            "。两人的服装、鞋、饰品必须与参考板对应格完全一致（款式、颜色、材质、细节），场景格只取空间、陈设与光线；参考板的背景与排版不取。")
    members = [{"file": f, "label": lab, "role": next((r.role for r in sr.refs if r.file == f), "item"), "source": "board"} for f, lab in tiles]
    slots = [*faces, AR.Slot(n, "board", board, None, [lab for _, lab in tiles], members, line, 0)]
    import dataclasses
    return dataclasses.replace(plan, slots=slots, prompt_prefix="".join(sl.line for sl in faces) + line,
                               dropped=[d for d in plan.dropped if d.get("file") not in {f for f, _ in tiles}])


def lin_sheet_only(sr, plan):
    """总调度 11-01 阶梯：双人镜参考板版连续 2 次只因 Q4 不过 → 第 3 次用“两张脸 + 林晚造型图”（板里不放单品和场景）"""
    from ns_agent import asset_refs as AR
    import dataclasses
    faces = [sl for sl in plan.slots if sl.kind == "face"]
    sh = next((r for r in sr.refs if r.role == "sheet" and r.character == "lin_wan" and r.file), None)
    if not sh or len(faces) + 1 > plan.capacity:
        return None
    n = len(faces) + 1
    line = f"图{n}是{sh.label}——林晚这一镜的服装、鞋、饰品必须与图{n}完全一致（款式、颜色、材质、细节），背景与姿势不取。"
    slot = AR.Slot(n, "sheet", sh.file, "lin_wan", [sh.label], [{"file": sh.file, "label": sh.label, "role": "sheet", "source": "sheet"}], line, 0)
    return dataclasses.replace(plan, slots=[*faces, slot], prompt_prefix="".join(sl.line for sl in faces) + line)


# ------------------------------------------------------------------ 作业
def build_jobs(eps: list[int]) -> list[dict]:
    import image_jobs as IJ
    from ns_agent import asset_refs as AR
    from ns_agent.gen_contract import preflight as PF
    prod, bible = IJ.production_globals(), IJ.load_bible()
    out = []
    for n in eps:
        si, ep = IJ.import_episode(n)   # CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：生产出图只认导入稿
        g = IJ.merged_globals(si.globals, prod)
        for shot in ep.shots:
            sid = f"ep{n:02d}-S{shot.index}"
            try:
                full, c, _, plan0 = IJ.frame_prompt_full(ep, shot, g, [], PROJECT, bible)
                body = full[len(plan0.prompt_prefix):]
                n_on = sum(1 for x in shot.cast if x.presence == "在画")
                # 双人镜：第二人只给造型图时 Q1 必挂（ep01-S4 林晚 0.23），换 seed 救不回（RSI IMG I5）→ 两张脸各占一槽（I9 允许）
                kw = {"two_person": "both_faces"} if n_on >= 2 else {}
                sr, plan = AR.plan_for(PROJECT, ep, shot, "qwen_image_2.1", **kw)
                alt = None
                if n_on >= 2 and TWO_PERSON_BOARD:
                    alt = lin_sheet_only(sr, plan)
                    plan = two_person_board(sr, plan)
                j = {"id": sid, "shot": sid, "ep": n, "index": shot.index, "prompt": plan.prompt_prefix + body,
                     "refs": plan.files, "asset_refs": AR.record(sr, plan), "cast": IJ.cast_of(shot),
                     "loras": [["krea2_film_texture_qwen21.safetensors", 0.5]],
                     "compiled_by": "tools/pipeline/image_jobs.py → ns_agent.compiler.compile_shot", "framing_project": PROJECT,
                     "recipe": "frame_v9（leica_sstar krea2 0.5，无 lin_wan_qi，REFLOCK 槽位）", "last_prompt": c.last_prompt,
                     "end_state": c.end_state, "face_files": [s.file for s in plan.slots if s.kind == "face"],
                     "variant": "both_faces+board" if alt else "plan",
                     "alt_q4": ({"refs": alt.files, "prompt": alt.prompt_prefix + body, "variant": "both_faces+lin_sheet"} if alt else None)}
                pf = PF.check(IJ.contract_request(j))
                j["preflight"] = {"ok": pf.ok, "blocking": [i.id for i in pf.blocking], "reasons": pf.reasons(), "items": pf.to_dict()}
            except Exception as e:  # noqa: BLE001
                j = {"id": sid, "shot": sid, "ep": n, "index": shot.index, "preflight": {"ok": False, "blocking": ["build"],
                                                                                         "reasons": [repr(e)[:300]]}}
            out.append(j)
    return out


def last_job(j: dict, first_file: str) -> dict | None:
    """尾帧：用通过契约的首帧做编辑（图1），身份脸作图2（I2）；提示词 = 编译器 last_prompt（含结束状态、锁、造型、后缀）"""
    if not j.get("last_prompt"):
        return None
    faces = list(j.get("face_files") or [])[:1]
    refs = [first_file] + faces
    lines = ""                                  # last_prompt 自带“图1是本镜头的首帧画面…”
    if faces:
        lead = next((s.get("character") for s in (j["asset_refs"].get("slots") or []) if s.get("kind") == "face"), "主角")
        lines += f"图2是{lead}的脸部参考（只取脸和发型，必须一致）。"
    return {**j, "id": j["id"] + ":last", "stage": "last", "prompt": lines + j["last_prompt"], "refs": refs}


# ------------------------------------------------------------------ 出图 / 打分
def render(lane: str, url: str, j: dict, seed: int) -> dict:
    import imgfix_ab as FX
    import imggen as IG
    from ns_render import image_params as IP
    o = {"prompt": j["prompt"], "sstar": [], "refs": j["refs"], "no_suffix": True}
    stage = j.get("stage", "image")
    tag = f"{j['shot']}_{stage}_s{seed}"
    g, eff, sent = FX.build(j, None, o, seed, url, f"assetmaster_frames/{tag}")
    c = IG.Lane(lane, url)
    try:   # GPU 任务归属标签（K-OPS-G01）；出错就不带标签
        _tag = IG._ct().make("ASSETMASTER", "last_frame" if stage == "last" else "first_frame", episode=j.get("ep"),
                             shot=str(j.get("shot") or "").rsplit("-", 1)[-1] or None, label=f"frames_v2 s{seed}", job=j.get("id"))
    except Exception:  # noqa: BLE001
        _tag = None
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    pid = c.submit(g, front=True, tag=_tag)
    t0 = time.time()
    dest = OUT / f"ep{j['ep']:02d}" / f"{tag}_raw.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    while True:
        time.sleep(4)
        r = c.fetch(pid, dest)
        if r:
            break
        if time.time() - t0 > 1800:
            r = "error:timeout"
            break
    gpu_s = None
    try:                                              # IMGPERF：ComfyUI 实际执行时长（不含排队），K-OPS-P01 墙钟 ≤ 2×GPU
        from ns_api.jobs import gpu_seconds
        gpu_s = gpu_seconds((json.loads(IG.api(url, f"/history/{pid}", timeout=30)) or {}).get(pid) or {})
    except Exception:  # noqa: BLE001
        pass
    rec = {"seed": seed, "lane": lane, "status": r, "secs": round(time.time() - t0, 1), "sent_prompt": sent, "refs": j["refs"],
           "started_at": started_at, "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "gpu_s": gpu_s,
           "host": lane.split(":")[0], "host_path": getattr(c, "last_host_path", None) if r == "ok" else None}
    if r == "ok":
        post = IP.post_file(dest, eff) if eff else None
        rec["file"] = str(Path(post["path"] if post else dest).relative_to(ROOT)).replace("\\", "/")
    return rec


def postflight(j: dict, rec: dict, tries: int = 4) -> dict:
    """打分。临时错误（ssh 断连 / 懒加载竞争）重试；仍失败抛 ScoringError —— 调用方不把它算成一次内容尝试"""
    last = None
    for k in range(tries):
        try:
            return _postflight(j, rec)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(15 * (k + 1))
    raise ScoringError(repr(last)[:300])


class ScoringError(RuntimeError):
    pass


def _limit_threads():
    try:
        import torch
        torch.set_num_threads(max(2, (__import__("os").cpu_count() or 8) // max(1, PF_THREADS)))
    except Exception:  # noqa: BLE001
        pass


def warmup():
    """主线程预加载 CLIP（4 个打分线程同时首次 import transformers 会懒加载竞争：ImportError CLIPModel，ep02-S3 02:35）"""
    from ns_agent.gen_contract import postflight as PO
    _limit_threads()
    try:
        PO._clip()
    except Exception as e:  # noqa: BLE001
        log("WARMUP_ERR", repr(e)[:200])


_POST = None


def _post():
    global _POST
    if _POST is None:
        import remote_score as RS
        from ns_render import image_params as IP
        _POST = RS.post_of(IP.resolve("frame_v9", {"style_suffix": ""}))
    return _POST


def _postflight(j: dict, rec: dict) -> dict:
    """REFLOCK 11-01：remote_score.postflight_full 在出图机器 GPU 上一次 ssh 算完 Q1–Q7（30–61 s/张，与 CPU 结果差 ≤0.0036）；
    传 host_path 不上传。没有 host_path（旧尝试）或 GPU 侧量测出错时，退回本机 CPU 路径"""
    if rec.get("file"):
        import image_jobs as IJ
        import remote_score as RS
        req = IJ.contract_request({**j, "graph": {}})
        if rec.get("host") == "gpu33" and rec.get("host_path"):
            job = {"id": "a", "host_path": rec["host_path"], "post": _post(), "request": req}
        else:
            # REFLOCK：CLIP 只在 gpu33 → gpu36 出的图传本机交付图（已后处理，post=None），经同一 ssh base64 上传
            job = {"id": "a", "file": str(ROOT / rec["file"]), "post": None, "request": req}
        d = RS.postflight_full("gpu33", [job])["a"]
        if not d.get("measure_error"):
            d["lap768"] = lap768(ROOT / rec["file"])
            d["borderline"] = 175 <= d["lap768"] < 200
            return d
        log("GPU_SCORE_FALLBACK", j["id"], str(d.get("measure_error"))[:160])
    return _postflight_cpu(j, rec)


def _postflight_cpu(j: dict, rec: dict) -> dict:
    import image_jobs as IJ
    import remote_score as RS
    from ns_agent.gen_contract import postflight as PO
    m = RS.score_local_files("gpu33", {"a": ROOT / rec["file"]})
    req = IJ.contract_request({**j, "graph": {}})
    remote = m["items"].get("a")
    local = PO.measure_local(ROOT / rec["file"], req["asset_refs"] or {}, remote)
    r = PO.evaluate(ROOT / rec["file"], req, remote=remote, cross=m["cross"], hands=m["hands"].get("a"), local=local)
    d = r.to_dict()
    d["reasons"] = r.reasons()
    d["lap768"] = lap768(ROOT / rec["file"])
    d["borderline"] = 175 <= d["lap768"] < 200          # 总调度：Q4 线 175，175–200 标“临界”人工看
    return d


def lap768(path) -> float:
    import cv2
    im = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    im = cv2.resize(im, (768, int(im.shape[0] * 768 / im.shape[1])), interpolation=cv2.INTER_AREA)
    return round(float(cv2.Laplacian(im, cv2.CV_64F).var()), 1)


def score_key(pf: dict) -> tuple:
    items = {i["id"]: i for i in pf.get("items", [])}
    q1 = items.get("Q1", {})
    v = 0.0
    for k in ("value", "min", "score"):
        if isinstance((q1.get("evidence") or {}).get(k), (int, float)):
            v = (q1["evidence"])[k]
            break
    return (pf.get("ok", False), -len(pf.get("blocking") or []), v)


# ------------------------------------------------------------------ 调度
class Orchestrator:
    def __init__(self, eps, lanes):
        self.eps, self.lanes = eps, lanes
        self.st = jl(STATE, {}) or {}
        self.q: "queue.PriorityQueue" = queue.PriorityQueue()
        self.cnt = 0
        self.inflight = 0
        self.done_ev = threading.Event()
        self.pfq: "queue.Queue" = queue.Queue()

    def put(self, prio, j, seed_i):
        with lock:
            self.cnt += 1
            self.q.put((prio, self.cnt, j, seed_i))

    def rec(self, sid, stage):
        return self.st.setdefault(sid, {}).setdefault(stage, {"attempts": []})

    def seed_job(self, jobs):
        for j in jobs:
            r = self.rec(j["id"], "image")
            r["job"] = {k: j.get(k) for k in ("prompt", "refs", "recipe", "preflight", "last_prompt", "end_state")}
            ar = j.get("asset_refs") or {}
            r["job"]["looks"] = {c["name"]: c.get("look") for c in ar.get("characters") or []}
            r["job"]["expected"] = [m.get("label") for sl in ar.get("slots") or [] for m in sl.get("members") or []
                                    if m.get("role") not in ("face", "scene")]
            if not j["preflight"]["ok"]:
                r["final"] = {"status": "阻断", "why": j["preflight"]["reasons"]}
                continue
            if (r.get("final") or {}).get("status") == "不合格" and any(
                    _retunable(a_) for a_ in r["attempts"] if not a_.get("stale")):
                r.pop("final")                     # Q8 改为只记录（REFLOCK 03:47）→ 重新打分后再收尾
                self.rec(j["id"], "last").pop("final", None)
            if r.get("final"):
                if r["final"]["status"] == "通过":
                    self.after_first(j, r["final"]["file"], requeue_only=True)
                continue
            # 打分崩溃（postflight_error）的旧尝试不算内容尝试：拿出来重新打分；
            # 只因 Q2 / Q5 不过的旧尝试（REFLOCK 11-01 02:xx 修了 Q2 区域与 Q5 指长比）用新契约代码重打分一次，不重出
            def _rescore_me(a_):
                # REFLOCK 03:47：Q8 发色改为只记录不阻断 → 只因 Q8（或 Q8 + 已修的 Q2 / Q5）不过的也重打一次分
                # gpu36 出的图曾送 gpu36 打分（无 CLIP）→ Q2/Q4/Q7/Q8 untested / measure_error：重打，不计次
                pf_ = a_.get("postflight") or {}
                if a_.get("file") and not a_.get("stale") and not a_.get("rescored_clip") and (
                        pf_.get("measure_error") or any(i.get("status") == "untested" and i.get("id") in ("Q2", "Q4", "Q7", "Q8")
                                                       for i in pf_.get("items") or [])):
                    a_["rescored_clip"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    return True
                blk = set((a_.get("postflight") or {}).get("blocking") or [])
                return a_.get("file") and not a_.get("stale") and (blk == {"postflight_error"} or _retunable(a_))
            errs = [a_ for a_ in r["attempts"] if _rescore_me(a_)]
            for a_ in errs:
                if _retunable(a_):
                    a_["rescored_ver"] = CONTRACT_TAG
                    a_["rescored"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    a_["postflight_before"] = a_.get("postflight")
            for a_ in errs:
                r["attempts"].remove(a_)
                a_.pop("postflight", None)
                with lock:
                    self.inflight += 1
                self.pfq.put(((j["ep"], 0), j, "image", len(r["attempts"]), a_))
            if errs:
                continue
            # 只认参考图与当前规划一致的旧尝试（双人镜改参考板 / 设定图 v2 后，旧的不算）
            for a_ in r["attempts"]:
                if a_.get("refs") and a_["refs"] != j["refs"] and a_["refs"] != (j.get("alt_q4") or {}).get("refs"):
                    a_["stale"] = "参考规划已变"
            live = [a_ for a_ in r["attempts"] if not a_.get("stale")]
            ok = [a_ for a_ in live if (a_.get("postflight") or {}).get("ok") and a_.get("file")]
            if ok:
                best = max(ok, key=lambda a_: score_key(a_["postflight"]))
                r["final"] = {"status": "通过", "file": best["file"], "seed": best["seed"], "via": best.get("rescored")}
                self.register(j, "image", r["final"], best)
                self.after_first(j, best["file"])
                continue
            if len(live) >= len(SEEDS):
                continue
            self.put((j["ep"], 0), j, len(live))
        save(self.st)

    def after_first(self, j, first_file, requeue_only=False):
        lj = last_job(j, first_file)
        rl = self.rec(j["id"], "last")
        if lj is None:
            rl["final"] = {"status": "不适用", "why": "剧本 motion 没有结束状态（compiler.last_prompt 为空）"}
            return
        if rl.get("final"):
            return
        self.put((j["ep"], 1), lj, len(rl["attempts"]))

    def worker(self, lane, url):
        while not self.done_ev.is_set():
            try:
                prio, _, j, si = self.q.get(timeout=5)
            except queue.Empty:
                with lock:
                    if self.inflight == 0 and self.q.empty():
                        self.done_ev.set()
                continue
            with lock:
                self.inflight += 1
            stage = j.get("stage", "image")
            try:
                rec = render(lane, url, j, SEEDS[si])
                self.pfq.put((prio, j, stage, si, rec))      # 打分交给 postflight 线程池，出图道立刻接下一张（卡不空等）
            except Exception as e:  # noqa: BLE001
                log("ERR", lane, j["id"], repr(e)[:300], traceback.format_exc()[-400:])
                if si + 1 < len(SEEDS):
                    self.put(prio, j, si + 1)
                with lock:
                    self.inflight -= 1

    def pf_worker(self):
        while not self.done_ev.is_set():
            try:
                prio, j, stage, si, rec = self.pfq.get(timeout=5)
            except queue.Empty:
                continue
            try:
                if rec["status"] == "ok":
                    try:
                        _t = time.time()
                        rec["postflight"] = postflight(j, rec)
                        rec["score_s"] = round(time.time() - _t, 1)
                        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    except ScoringError as e:
                        rec["scoring_errors"] = rec.get("scoring_errors", 0) + 1
                        log("SCORE_RETRY_LATER", j["id"], rec["seed"], str(e)[:160])
                        with lock:
                            self.inflight += 1               # 下面 finally 会减；重新排队等再打分
                        threading.Timer(120, lambda: self.pfq.put((prio, j, stage, si, rec))).start()
                        continue
                else:
                    rec["postflight"] = {"ok": False, "blocking": ["render"], "reasons": [rec["status"][:300]], "items": []}
                self.finish(j, stage, si, rec)
            except Exception as e:  # noqa: BLE001
                log("ERR", "pf", j["id"], repr(e)[:300], traceback.format_exc()[-400:])
            finally:
                with lock:
                    self.inflight -= 1

    def finish(self, j, stage, si, rec):
        sid = j["shot"]
        with lock:
            r = self.rec(sid, stage)
            rec["refs"] = j.get("refs")
            rec["variant"] = j.get("variant")
            rec["run"] = PROJECT                      # W28（C-14）：state.json 全局按镜号存，条目带剧名，producer adopt 只认本剧
            if rec.get("rescored") and (rec.get("postflight") or {}).get("ok"):
                self.st.setdefault("_rescued", []).append(f"{sid}:{stage}:s{rec['seed']}")
            r["attempts"].append(rec)
            ok = rec["postflight"].get("ok")
            log(stage, sid, "seed", rec["seed"], rec["lane"], "通过" if ok else "不过", rec["postflight"].get("blocking"))
            if ok or si + 1 >= len(SEEDS):
                good = [a for a in r["attempts"] if a.get("file") and not a.get("stale")]
                best = max(good, key=lambda a: score_key(a["postflight"])) if good else None
                if best and best["postflight"].get("ok"):
                    r["final"] = {"status": "通过", "file": best["file"], "seed": best["seed"]}
                else:
                    r["final"] = {"status": "不合格", "file": best["file"] if best else None,
                                  "why": best["postflight"].get("reasons") if best else ["没出图"]}
                save(self.st)
                self.register(j, stage, r["final"], rec if best is None else best)
                if stage == "image" and r["final"]["status"] == "通过":
                    self.after_first(j, r["final"]["file"])
                elif stage == "image":
                    self.rec(sid, "last")["final"] = {"status": "未出（首帧不合格）"}
                self.check_episode(j["ep"])
            else:
                nj = j
                live = [a_ for a_ in r["attempts"] if not a_.get("stale")]
                if (stage == "image" and si + 1 == 2 and j.get("alt_q4") and len(live) >= 2
                        and all(((a_.get("postflight") or {}).get("blocking") or []) == ["Q4"] for a_ in live[-2:])):
                    nj = {**j, "refs": j["alt_q4"]["refs"], "prompt": j["alt_q4"]["prompt"], "variant": j["alt_q4"]["variant"]}
                    log("LADDER", sid, "参考板版 2 次只因 Q4 不过 → 第 3 次用", nj["variant"])
                self.put((j["ep"], 0 if stage == "image" else 1), nj, si + 1)
            save(self.st)

    def register(self, j, stage, final, best):
        """登记为候选；契约通过的带 postflight 写进 take 并设为当前（register_takes，总调度接口决定）；不合格的只登记可查"""
        if not final.get("file"):
            return
        try:
            import register_takes as RT
            pf = best.get("postflight") or {}
            it = {"shot": j["shot"], "stage": stage, "file": final["file"], "seed": best["seed"], "prompt": best.get("sent_prompt") or "",
                  "refs": j["refs"], "label": LABEL if final["status"] == "通过" else LABEL + "·不合格",
                  "postflight": {"ok": final["status"] == "通过", "items": pf.get("items") or [], "reasons": pf.get("reasons") or []},
                  "origin": {"run": "assetmaster/frames_v2", "recipe": "frame_v9", "qc": pf.get("blocking"),
                             "contract_ok": final["status"] == "通过", "lap768": pf.get("lap768"), "borderline": pf.get("borderline")}}
            res = RT.register(it, label=it["label"])
            final["take"] = res
            final["active"] = bool(res.get("active"))
        except Exception as e:  # noqa: BLE001
            final["register_error"] = repr(e)[:300]
            log("REG_ERR", j["shot"], stage, repr(e)[:200])

    def check_episode(self, n):
        ids = [k for k in self.st if k.startswith(f"ep{n:02d}-")]
        if not ids:
            return
        for k in ids:
            s = self.st[k]
            if not (s.get("image", {}).get("final") and s.get("last", {}).get("final")):
                return
        done = self.st.setdefault("_episodes", {})
        if done.get(str(n), {}).get("page"):
            return
        page = write_page(n, self.st)
        done[str(n)] = {"page": page, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        log("EPISODE_DONE", n, page)
        try:
            import register_takes as RT
            RT.mark_episode_done(n)
        except Exception as e:  # noqa: BLE001
            log("MARK_ERR", n, repr(e)[:200])
        (OUT / "episodes_done.jsonl").open("a", encoding="utf-8").write(json.dumps({"ep": n, "page": page}, ensure_ascii=False) + "\n")

    def run(self):
        jobs = build_jobs(self.eps)
        (OUT / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
        log("jobs", len(jobs), "preflight 阻断", [j["id"] for j in jobs if not j["preflight"]["ok"]])
        self.seed_job(jobs)
        for n in self.eps:
            self.check_episode(n)
        warmup()
        th = [threading.Thread(target=self.worker, args=(ln, LANES_ALL[ln]), daemon=True) for ln in self.lanes]
        th += [threading.Thread(target=self.pf_worker, daemon=True) for _ in range(PF_THREADS)]
        [t.start() for t in th]
        [t.join() for t in th]
        save(self.st)
        log("ALL_DONE")


# ------------------------------------------------------------------ 审阅页
def write_page(n: int, st: dict) -> str:
    import html
    import os
    from ns_agent.gen_contract import report as R      # 与 PRODUCER 的印样同一套排序 / 标注函数
    q4m = jl(OUT / "q4_metrics.json", {}) or {}         # tools/assetmaster/q4_backfill.py 补的 Q4 度量（不改结论）
    d = PAGES / f"ep{n:02d}"
    d.mkdir(parents=True, exist_ok=True)

    def src(p):
        return html.escape(os.path.relpath(ROOT / p, d).replace("\\", "/")) if p else ""

    old = jl(RUN / "images/state.json", {}) or {}
    rows, md = [], [f"# ep{n:02d} 首帧 / 尾帧 v2 契约逐项表（frame_v9，ASSETMASTER）", "",
                    "Q2 列 = 预期单品（参考槽里挂的造型图 / 单品 / 参考板）与出图区域匹配结果（CLIP + 颜色直方图；✓ 过线 ✗ 不过）。", "",
                    "| 镜 | 阶段 | 结果 | Q1 身份 | 造型 | 实际挂的参考图 | 预期单品 vs 匹配（Q2） | Q4 清晰度 | seed / 尝试 | 不过项 |",
                    "|---|---|---|---|---|---|---|---|---|---|"]
    passed, failed = [], []
    for sid in sorted((k for k in st if k.startswith(f"ep{n:02d}-")), key=lambda x: int(x.split("-S")[1])):
        for stage in ("image", "last"):
            r = st[sid].get(stage, {})
            f = r.get("final") or {}
            att = r.get("attempts", [])
            best = next((a for a in att if a.get("file") == f.get("file")), {})
            blk = (best.get("postflight") or {}).get("blocking") or f.get("why") or []
            bl = (best.get("postflight") or {}).get("borderline")
            if bl and f.get("status") == "通过":
                f = {**f, "status": "通过（临界 Laplacian " + str((best.get("postflight") or {}).get("lap768")) + "）"}
            pfi = {i["id"]: i for i in (best.get("postflight") or {}).get("items") or []}
            job = st[sid].get("image", {}).get("job") or {}
            q2rows = ((pfi.get("Q2") or {}).get("evidence") or {}).get("rows") or []
            q2 = "<br>".join(f"{'✓' if x.get('pass') else '✗'} {x.get('label')}（{x.get('clip')}）" for x in q2rows) or                  "<br>".join(job.get("expected") or []) or "—"
            refs = "<br>".join(Path(x).name for x in (best.get("refs") or job.get("refs") or []))
            looks = "、".join(f"{k}{v}" for k, v in (job.get("looks") or {}).items())
            q1 = (pfi.get("Q1") or {}).get("detail", "—")
            q4 = (best.get("postflight") or {}).get("lap768", "")
            md.append(f"| {sid} | {'首帧' if stage == 'image' else '尾帧'} | {f.get('status', '—')} | {q1} | {looks} | {refs} | {q2} "
                      f"| {q4} | {f.get('seed', '')} / {len(att)} | {', '.join(map(str, blk))[:120]} |")
            items = (best.get("postflight") or {}).get("items") or []
            cells = "".join(f"<td class='{i.get('status')}'>{html.escape(i['id'])}<br><small>{html.escape(str(i.get('detail', ''))[:80])}</small></td>"
                            for i in items)
            pf_best = best.get("postflight") or {}
            bq4 = q4m.get(f.get("file") or "") or {}
            if bq4.get("Q4"):                       # 2026-11-01f-q4metrics 补数：只换 Q4 的度量，不改结论
                its = pf_best.get("items") or []
                pf_best = {**pf_best, "items": ([bq4["Q4"] if i.get("id") == "Q4" else i for i in its]
                                                if any(i.get("id") == "Q4" for i in its) else [*its, bq4["Q4"]])}
            q2ev = (pfi.get("Q2") or {}).get("evidence") or {}
            shoe_review = bool(q2ev.get("review")) or "鞋待目检" in json.dumps(q2ev, ensure_ascii=False)
            cap = html.escape(R.q4_caption(pf_best))
            badge = "<div class=shoe>⚠ 鞋待目检</div>" if shoe_review else ""
            fig = (f"<img loading=lazy src='{src(f.get('file'))}'><div class=cap>{cap}</div>{badge}" if f.get("file") else "—")
            oldf = ""
            oj = (old.get("jobs") or {}).get(f"frame:{sid}") if stage == "image" else None
            if oj and oj.get("chosen"):
                a = next((x for x in oj.get("attempts", []) if x.get("id") == oj["chosen"]), None)
                if a and a.get("file"):
                    oldf = f"<img loading=lazy class=old src='{src(a['file'])}'>"
            row = (f"<tr><td>{sid}<br>{'首帧' if stage == 'image' else '尾帧'}<br><b>{f.get('status', '')}</b></td>"
                   f"<td>{oldf}</td><td>{fig}</td>{cells}</tr>")
            # 总调度：塑料 / 娃娃脸没有可靠自动判定 → 印样按 R.q4_sort_key 排（最可能塑料的在最前），总调度看图把关
            (passed if str(f.get("status", "")).startswith("通过") or f.get("status") == "不适用" else failed).append(
                (R.q4_sort_key(pf_best), row))
    (d / "contract.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    passed = [r_ for _, r_ in sorted(passed, key=lambda x: x[0])]
    failed = [r_ for _, r_ in sorted(failed, key=lambda x: x[0])]
    H = ["<!doctype html><meta charset=utf-8><title>ep%02d 首尾帧 v2</title><style>body{font:13px system-ui,'Microsoft YaHei';margin:16px}"
         "img{height:300px}img.old{height:200px;opacity:.85}td{border:1px solid #ddd;padding:4px;vertical-align:top;font-size:12px}"
         ".cap{font-size:11px;color:#333;margin-top:2px}.shoe{display:inline-block;margin-top:3px;padding:2px 6px;background:#e8590c;color:#fff;font-weight:700;border-radius:3px}"
         "table{border-collapse:collapse}.pass{background:#dff0e2}.fail{background:#f7d7d7}.untested{background:#f3ecd2}.na{color:#999}</style>" % n,
         f"<h1>ep{n:02d} 首帧 / 尾帧 v2（frame_v9 + REFLOCK 槽位；待总调度亲审）</h1><p>左：旧版首帧；中：新版（下方一行 = Q4 脸部质感度量）；"
         "右：契约逐项。排序：最可能塑料 / 娃娃脸的在最前（脸部高频从低到高，同分塑料探针高的在前，没检出脸的在最后）；"
         "橙色“鞋待目检”= Q2 鞋分 0.70–0.78。按 K-REN-133：上表只放通过契约的图；不合格折叠在下面。</p><table>", *passed, "</table>",
         f"<details><summary>未通过 / 阻断 {len(failed)} 项（不进候选）</summary><table>", *failed, "</table></details>"]
    (d / "index.html").write_text("\n".join(H), encoding="utf-8")
    return str((d / "index.html").relative_to(ROOT)).replace("\\", "/")


def rescore(eps: list[int]) -> dict:
    """总调度 11-01：REFLOCK 修了 Q5（林晚 5cm 甲指长比放宽到 ≤4.6）与 Q2（只判鞋 / 下装 / 造型图）。
    只因 Q2 / Q5 不过的尝试不重出、用新契约代码重打分；Q4 不过仍是真不过。救回数记 RSI_LEDGER"""
    st = jl(STATE, {}) or {}
    jobs = {j["id"]: j for j in build_jobs(eps)}
    out = {"rescored": 0, "rescued": [], "still_fail": []}
    for sid, s_ in st.items():
        if sid.startswith("_") or int(sid[2:4]) not in eps:
            continue
        j0 = jobs.get(sid)
        if not j0:
            continue
        for stage in ("image", "last"):
            r = s_.get(stage) or {}
            if (r.get("final") or {}).get("status") == "通过":
                continue
            j = j0
            if stage == "last":
                j = last_job(j0, (s_.get("image", {}).get("final") or {}).get("file") or "") or j0
            for a_ in r.get("attempts", []):
                blk = set((a_.get("postflight") or {}).get("blocking") or [])
                if not a_.get("file") or not blk or not blk <= {"Q2", "Q5"}:
                    continue
                try:
                    a_["postflight_before"] = a_["postflight"]
                    a_["postflight"] = postflight({**j, "refs": a_.get("refs") or j["refs"]}, a_)
                    a_["rescored"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    out["rescored"] += 1
                    tag = sid + ":" + stage + ":s" + str(a_["seed"])
                    (out["rescued"] if a_["postflight"].get("ok") else out["still_fail"]).append(tag)
                    log("RESCORE", sid, stage, a_["seed"], sorted(blk), "->", a_["postflight"].get("blocking"))
                except Exception as e:  # noqa: BLE001
                    log("RESCORE_ERR", sid, repr(e)[:200])
            if any((a_.get("postflight") or {}).get("ok") for a_ in r.get("attempts", [])) and r.get("final"):
                r.pop("final", None)                       # 让 run 重新收尾（登记 + 设当前）
    save(st)
    (OUT / "rescore.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def parse_eps(s):
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def main(argv=None) -> int:
    argv = RUNS.gate_legacy_tool(argv, __file__)
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "jobs", "page", "rescore"])
    ap.add_argument("--eps", default="1-10")
    # gpu36:2 = 长镜头视频专用道（--novram，出图一张 363 s；IMGPERF 11-01）→ 出图不派
    ap.add_argument("--lanes", default="gpu33:0,gpu33:1,gpu33:3,gpu36:0,gpu36:1")
    a = ap.parse_args(argv)
    eps = parse_eps(a.eps)
    if a.cmd == "jobs":
        js = build_jobs(eps)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "jobs_preview.json").write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
        for j in js:
            print(j["id"], j["preflight"]["ok"], j["preflight"]["blocking"], "; ".join(j["preflight"]["reasons"])[:200])
        return 0
    if a.cmd == "rescore":
        print(json.dumps(rescore(eps), ensure_ascii=False))
        return 0
    if a.cmd == "page":
        st = jl(STATE, {})
        for n in eps:
            print(write_page(n, st))
        return 0
    Orchestrator(eps, a.lanes.split(",")).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
