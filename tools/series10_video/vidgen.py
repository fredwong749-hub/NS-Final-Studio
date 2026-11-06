"""VIDEO10（2026-10-31）：series10 视频出片编排器——在 gpu33 / gpu36 本机跑（K-OPS-I05），各管本机 3 道。

作业：video/jobs.json（或 validate_jobs.json），由笔记本 build_jobs.py 用系统编译器预编译（每镜一组变体，见 build_jobs 文档）。
本机只出 host == 本机 的镜（整集分机，成片在本机合成，片段不跨机）。

调度（K-OPS-I06 / K-REN-018）：每道总负载 ≤ 2（服务器 /queue 里本工具 + 别的会话的任务都算），出完立刻补交；取回 = 本机文件
复制（不走网络）；打分放独立线程池（score_clip.py，venv_idm，CPU 线程受限：gpu36 规则不同时压满全核 + 三卡）。
长镜头（> 260 帧）只派 gpu36:2：先挂住该道、等队列空且本工具未取回为 0（K-OPS-I04），lane.sh restart long，长镜头全部定下后
restart normal。

规则阶梯（每镜最多 3 次重出；validate 模式不走阶梯，全部变体都出）：
  脸部泛红 → b24（换配方）→ 换 seed；动作不足 / 镜内硬切 → 换 seed（s2 → s3 → s4）；身份偏离 → alt（换参考）→ b24 → 换 seed；
  4 帧一顿只记软项（合成时去抖），不重出。4 次都不过 → 取 penalty 最小的一版标“尽力”。
产物（仓库镜像目录，相对路径同笔记本）：video/clips/epNN/<镜>__<变体>_s<seed>.mp4、video/_preview/*.mp4（360×640，≤2 MB）、
  video/_thumbs/*.jpg（印样）、video/scores/<镜>__<变体>.json、video/state_<host>.json、video/vidgen_<host>.log
控制：video/control_<host>.json {"jobs": "jobs.json", "eps": [1,3,...], "hold_lanes": [], "stop": false, "per_lane": 2}

    python tools/series10_video/vidgen.py run gpu33|gpu36 --run <剧>      # MERGE-VID-O：剧必须显式给（--run 或 NS_RUN），不默认第一季
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ctx as RC  # noqa: E402

# MERGE-VID-O（ISS-1103-024206-3737，L-137）：视频目录按剧（main 里 set_run；服务器上没有 runs.py，剧必须由 --run / NS_RUN 显式给）
RUN_ID: str | None = None
RUN: Path | None = None
VID: Path | None = None
VID_REL: str | None = None


def set_run(run: str) -> str:
    global RUN_ID, RUN, VID, VID_REL
    RUN_ID, VID_REL = run, RC.vid_rel(run)
    RUN, VID = RC.run_dir(run), RC.vid_dir(run)
    os.environ["NS_RUN"] = run           # 打分子进程（score_clip）同一部剧
    return run
LIP_REDO = ROOT / "data" / "director" / "redo_requests.json"   # DIRECTOR K-EDT-805 口型重出单（finish.py 写，check_lip_redo 读）
PORTS = {"gpu33": {"gpu33:0": 8188, "gpu33:1": 8189, "gpu33:3": 8191},
         "gpu36": {"gpu36:0": 8188, "gpu36:1": 8189, "gpu36:2": 8190}}
OUTDIR = {"gpu33:0": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu0",
          "gpu33:1": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu1",
          "gpu33:3": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu3",
          "gpu36:0": "/root/work/fredw/comfy/output/gpu0", "gpu36:1": "/root/work/fredw/comfy/output/gpu1",
          "gpu36:2": "/root/work/fredw/comfy/output/gpu2"}
FFMPEG = {"gpu33": "/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin", "gpu36": "/root/work/fredw/tools_bin"}
SCORE_PY = "/root/work/fredw/venv_idm/bin/python"
LONG_LANE = "gpu36:2"
LANE_SH = "/root/work/fredw/longshot/lane.sh"
LANE_MODE = "/root/work/fredw/longshot/run/mode"
LANE_MAX_FRAMES = 260
CLIENT = "video10-"
MAX_RENDERS = 4
SEEDS = ["s2", "s3", "s4"]


def log(host, *a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(VID / f"vidgen_{host}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def jsave(p, d):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def api(port, path, data=None, ctype="application/json", timeout=60):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


POLICY = ROOT / "config/pipeline/video_policy.json"


def policy_hold(var: dict) -> str | None:
    """K-OPS-Q24（AUDIT 18:22，WORKFLOW 改，CONSENT VIDEO10 -> AUTOPILOT by 总调度）：派单前按现行配方政策再查一次——
    jobs.json 可能是政策改动之前编的（L-088 前编的清单里有 two_person_ref2va 108 个、establishing 7 个 ready 变体）。
    pika_only 打开时，变体配方不在 allowed → 不派，返回原因；政策文件读不到 → 不拦（编译时的政策仍在）"""
    try:
        pol = (json.loads(POLICY.read_text(encoding="utf-8")).get("pika_only") or {})
    except (OSError, ValueError):
        return "hold：读不到 config/pipeline/video_policy.json（MERGE-VID-O：政策缺失失败关闭，不派）"
    if pol.get("enabled") and var.get("recipe") not in (pol.get("allowed") or []):
        return f"hold：配方 {var.get('recipe')} 不在 video_policy.pika_only.allowed（L-088 视频全部用 Pika），等重编 jobs.json"
    return None


# RL-E3（AUDIT 20:15，K-OPS-Q24 扩到提示词）：与 services/recipes/ns_recipes/lint.SYS_CAMERA_FACING_RE 同一模式（vidgen 部署在
# video10_srv，不带 ns_recipes，所以抄一份；tests/test_recipe_pika_default.py 核对两边一致）
PROMPT_FACING_RE = re.compile(r"\b(?:facing|faces|turned toward|turns toward|toward)\s+(?:the\s+)?(?:camera|lens|viewer)\b", re.I)


def prompt_hold(var: dict) -> str | None:
    """变体提示词的系统锚点句（The frame keeps …）里有朝向镜头 → hold（16:56 旧编译稿 538 个里 125 个带 facing the camera）"""
    sys_txt = " ".join(re.findall(r"The frame keeps[^.]*\.", var.get("prompt") or ""))
    m = PROMPT_FACING_RE.search(sys_txt)
    return f"hold：编译稿含朝向镜头的系统句“{m.group(0)}”（RL-E3），等重编" if m else None


def policy_ok(var: dict) -> bool:
    why = policy_hold(var) or prompt_hold(var)
    if why and not var.get("_policy_logged"):
        var["_policy_logged"] = True
        print(time.strftime("%m-%d %H:%M:%S"), "POLICY_HOLD", var.get("variant"), why, flush=True)
    return why is None


# VID-LOOP（11-06，ep01-S1 口型重出 51 次死循环）：K-EDT-805 的重出单每次合成都换新的 timeline 版本号，check_lip_redo 按
# timeline@at 判“新请求”→ 每版都作废全部出片重出（ComfyUI 缓存，同 seed 出的还是同一条）→ 尽力 → 重合成 → 再开单。
# 上限：config/post/director.json lip_redo_max_per_shot（默认 1，每镜最多作废重出一次）；到上限后请求只记账不作废，
# 用尽采用最好一版（L-196）。重出视频改不了的兜底原因（no H3 audio：镜头本来就没进成片 / 没有 H3 音轨）一律不作废。
DIRECTOR_CFG = ROOT / "config/post/director.json"
LIP_REDO_CAP_DEFAULT = 1
LIP_REDO_UNFIXABLE = ("no H3 audio",)
LIP_REDO_RULE = "K-EDT-805"
IN_FLIGHT = ("submitted", "fetched", "scoring")
SETTLED = ("done", "best_effort", "blocked")


def lip_redo_cap(cfg_path: Path | None = None) -> int:
    try:
        v = json.loads((cfg_path or DIRECTOR_CFG).read_text(encoding="utf-8")).get("lip_redo_max_per_shot", LIP_REDO_CAP_DEFAULT)
        return max(0, int(v))
    except (OSError, ValueError, TypeError):   # arch-ok: 配置读不到 / 写坏 = 默认上限 1（不回到无上限）
        return LIP_REDO_CAP_DEFAULT


def lip_redo_count(rec: dict) -> int:
    """这一镜已用掉的口型重出次数：新记录看 lip_redo_n；旧记录（上限出现之前的 state）按已消费的请求键数算，
    所以线上已被打回 51 次的镜一升级就是“已到上限”"""
    n = rec.get("lip_redo_n")
    return int(n) if n is not None else len(rec.get("lip_redo_applied") or [])


def lip_unfixable(q: dict) -> bool:
    return str(q.get("fallback_reason") or "") in LIP_REDO_UNFIXABLE


def in_flight(rec: dict) -> bool:
    return any(x.get("state") in IN_FLIGHT for x in rec.get("renders") or [])


def restore_lip_superseded(rec: dict, first_frame: str | None) -> int:
    """口型重出作废（rule K-EDT-805）的版本里，首帧和现首帧一致的拿回 renders（按 变体+seed 去重，取最新一条；
    renders 里已有的不重复）→ 和现有版本一起挑最好的（L-196）。返回拿回的条数"""
    sup = rec.get("superseded") or []
    if not first_frame:          # 现首帧不明 → 不拿（别把旧首帧的版本混进来）
        return 0
    pick: dict[tuple, dict] = {}
    keep = []
    for x in sup:
        if x.get("rule") == LIP_REDO_RULE and x.get("state") == "scored" and x.get("file") and x.get("first_frame") == first_frame:
            k = (x.get("variant"), x.get("seed"))
            if k not in pick or float(x.get("t_done") or 0) >= float(pick[k].get("t_done") or 0):
                pick[k] = x
        else:
            keep.append(x)
    have = {(x.get("variant"), x.get("seed")) for x in rec.get("renders") or []}
    back = []
    for k, x in pick.items():
        if k in have:
            continue
        y = {kk: v for kk, v in x.items() if kk not in ("superseded_at", "why", "rule")}
        y["restored_from_lip_redo"] = True
        back.append(y)
    if not back and len(keep) == len(sup):
        return 0
    rec.setdefault("renders", []).extend(sorted(back, key=lambda x: float(x.get("t_done") or 0)))
    rec["superseded"] = keep
    return len(back)


def _VS():
    """视频分片模块（服务器镜像没带 = None → 不看领取，按 jobs.json 的 host）"""
    try:
        import video_shard as VS
        return VS
    except ImportError:   # arch-ok: 没有分片模块 = 不分片（原行为）
        return None


def _claims() -> dict:
    VS = _VS()
    return VS.load_claims(VID) if VS else {}


def undispatchable_reason(shot: dict, rec: dict) -> str | None:
    """FIX-VID D8：镜有变体、一条都没出过、却没有任何一个变体能派（编译状态不是 ready / preflight 不过 / 政策 hold）→ 原因串
    （按变体列：v1=no_last_frame；s2=preflight:…）。能派 / 没变体 / 已有出片 → None"""
    vs = shot.get("variants") or {}
    if not vs or rec.get("renders") or next_variant(shot, rec) is not None:
        return None
    why = []
    for v, var in vs.items():
        st = var.get("status")
        if st not in ("ready", "lint_error"):
            why.append(f"{v}={st}")
        elif not (var.get("preflight") or {}).get("ok", True):
            why.append(f"{v}=preflight:{'；'.join(map(str, (var.get('preflight') or {}).get('reasons') or []))[:80]}")
        else:
            why.append(f"{v}={policy_hold(var) or prompt_hold(var) or '不可派'}"[:120])
    return ("没有可派的变体（等重编 jobs.json；成片先用首帧静帧缓推占位）：" + "；".join(why))[:600]


# 只是“尾帧 / 首帧还没到”（no_last_frame / no_first_frame）的派不了：帧还在出，先等这么久再阻断（L-205：单集 ≤ 50 min）；
# 尾帧用尽的镜 producer 会写 last_frame_fallback=i2va → build_jobs 编成 I2VA，不会停在这里。其它原因（preflight / 编译错）当场阻断
UNDISPATCHABLE_GRACE_S = 1800


def frame_wait_only(shot: dict) -> bool:
    vs = shot.get("variants") or {}
    return bool(vs) and all(str(v.get("status") or "").startswith(("no_last_frame", "no_first_frame")) for v in vs.values())


def settle_rec(rec: dict) -> str:
    """没有在出 / 在打分的版本时定下这一镜（after_score 的收尾；L-196 用尽采用最好一版）：有过门的 → done 取 penalty 最小；
    只有没过门的 → best_effort 取 penalty 最小；一条打分都没有 → blocked。返回新状态"""
    scored = [x for x in rec.get("renders") or [] if x.get("state") == "scored" and not (x.get("score") or {}).get("error")]
    passed = [x for x in scored if (x["score"].get("gate") or {}).get("pass")]
    pool = passed or scored
    if pool:
        best = min(pool, key=lambda x: x["score"].get("penalty", 9))
        rec.update(status="done" if passed else "best_effort", chosen=best["variant"])
    else:
        rec.update(status="blocked")
    return rec["status"]


def first_take_first(todo: list, shots: dict, recs: dict, ctrl: dict | None = None) -> list:
    """W46（总调度 05:3x 冲刺规则）：每镜先各出 1 条，全部有片之前不出第 2 变体——作业里还有“一条都没出过”的镜
    （有变体、没完结、renders 为空）→ 本轮只派这些镜的第一条，失败镜的重试 / 换变体等它们都起跑后再排。
    control_<host>.json "first_take_first": false 关掉（恢复原来按集、镜顺序逐镜重试）"""
    if (ctrl or {}).get("first_take_first", True) is False:
        return todo
    # VID-LOOP（11-06）：只算本轮真能派出的“一条都没出过”的镜（在 todo 里）。以前按“有变体 + 没出过”算——变体全被政策 /
    # preflight 挡住（next_variant 永远 None）的镜也算“新鲜”，todo 被它们过滤成空，别的镜的重试永远排不上（整台空转）
    in_todo = {sid for sid, _v in todo}
    fresh = {sid for sid in in_todo if not (recs.get(sid) or {}).get("renders")
             and (recs.get(sid) or {}).get("status") not in ("done", "best_effort", "blocked")}
    if not fresh:
        return todo
    # FIX-NIGHT2 #8：失败镜的重试不能无限排在新镜后面——上一条出完 / 报错已超 RETRY_AGE_S 的重试和新镜一起派（按年龄放行）
    now = (ctrl or {}).get("_now") or time.time()
    aged = {sid for sid in in_todo if sid not in fresh and retry_age(recs.get(sid) or {}, now) >= RETRY_AGE_S}
    return [(sid, v) for sid, v in todo if sid in fresh or sid in aged]


RETRY_AGE_S = int(os.environ.get("NS_RETRY_AGE_S", "900"))


def retry_age(rec: dict, now: float | None = None) -> float:
    """这一镜等重试的时长：最后一条版本结束（t_done / t_sub）到现在；没有版本 = 0"""
    ts = [float(x.get("t_done") or x.get("t_sub") or 0) for x in rec.get("renders") or []]
    ts = [t for t in ts if t > 0]            # 没记时间的（旧记录 / 测试替身）不算“等很久”
    return ((now or time.time()) - max(ts)) if ts else 0.0


def render_sig(x: dict) -> tuple:
    """一条版本的“内容签名”：同（配方, 种子）= 同一条片（FIX-NIGHT2 #4）；旧记录没有种子就按变体名"""
    return (x.get("recipe"), x.get("seed")) if x.get("seed") is not None else ("variant", x.get("variant"))


def distinct_renders(rec: dict) -> int:
    return len({render_sig(x) for x in rec.get("renders") or []})


def lane_order(lanes: dict, k: int) -> list:
    """道的轮换顺序：第 k 轮从第 k % n 条道起（保持原相对顺序）——FIX-NIGHT2 #8，gpu36:2 不被前两道饿死"""
    items = list(lanes.items())
    if not items:
        return items
    i = k % len(items)
    return items[i:] + items[:i]


def next_variant(shot: dict, rec: dict) -> str | None:
    """规则阶梯（见模块文档）；rec = 本镜状态"""
    used = {r["variant"] for r in rec["renders"]}
    used_sig = {render_sig(r) for r in rec["renders"]}    # FIX-NIGHT2 #4：同（配方, 种子）已出过 = 跳过，不重渲同一条片
    vs = shot["variants"]
    # GEN_CONTRACT：preflight 不过的变体不提交（validate 对照模式除外，见 pending）
    ok = lambda v: (v in vs and v not in used and vs[v].get("status") in ("ready", "lint_error")  # noqa: E731
                    and (vs[v].get("preflight") or {}).get("ok", True) and policy_ok(vs[v])
                    and (vs[v].get("seed") is None or (vs[v].get("recipe"), vs[v].get("seed")) not in used_sig))
    fq = [v for v in rec.get("force_queue") or [] if ok(v)]   # 总调度批的“加 N 个变体再试”（redo_requests 带 variants）：不受 MAX_RENDERS 限制
    if fq:
        return fq[0]
    fn = rec.get("force_next")          # 系统修复后指定先出的变体（如 K-REN-302 的 mot），用一次就清
    if fn and ok(fn):              # 只在真正派出时清掉（dispatch 里），没派出（道被挂住）下一轮还认
        return fn
    if distinct_renders(rec) >= MAX_RENDERS:      # FIX-NIGHT2 #4：按不同的片数计（重复渲染不吃阶梯）
        return None
    last = rec["renders"][-1] if rec["renders"] else None
    if last is None:   # 第一条：v1；v1 派不了（如 preflight 不过）→ 阶梯里第一个能派的（FIX-VID D8：别让整镜一条都不出）
        return next((v for v in ["v1", *(shot.get("ladder_order") or list(vs))] if ok(v)), None)
    fails = ((last.get("score") or {}).get("gate") or {}).get("fails") or ["出片失败"]
    order = []
    if "身份偏离" in fails:          # 首帧路线身份不过 → 纯 Ref2VA 24 步（r24）→ 换参考（alt）
        order += ["r24", "alt", "b24"]
    if "脸部泛红" in fails:          # Ref2VA 线泛红最低（lab_recipes 批 2–3）
        order += ["r24", "b24"]
    if "景别不符" in fails:          # Ref2VA 构图来自提示词；保构图走只给首帧（需首帧已过契约）
        order += ["i2v"]
    if "动作不足" in fails:          # K-REN-302：先加系统最低动作提示（mot），再换 seed
        order += ["mot"]
    order += SEEDS
    return next((v for v in order if ok(v)), None)


class Lane:
    def __init__(self, name, port):
        self.name, self.port = name, port
        self.uploads: dict[str, str] = {}
        self.busy_s = 0.0
        self.down = False
        self.last_foreign = 0.0              # FIX-VID（L-205 KPI）：新起 / 重启的编排器不再先空等 yield_s；道上有别人的任务照样让（foreign 当场判）

    def queue(self):
        d = json.loads(api(self.port, "/queue", timeout=15))
        items = d["queue_running"] + d["queue_pending"]
        mine = [it[1] for it in items if str((it[3] or {}).get("client_id", "")).startswith(CLIENT)]
        return mine, len(items) - len(mine)

    def upload(self, rel: str) -> str:
        if rel in self.uploads:
            return self.uploads[rel]
        p = ROOT / rel
        b = "----v10" + uuid.uuid4().hex
        name = "v10_" + p.name
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
                f"Content-Type: image/png\r\n\r\n").encode() + p.read_bytes() + \
            (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nvideo10\r\n"
             f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n").encode()
        r = json.loads(api(self.port, "/upload/image", body, f"multipart/form-data; boundary={b}", timeout=120))
        nm = (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]
        self.uploads[rel] = nm
        return nm

    def submit(self, var: dict, prefix: str, tag: dict | None = None) -> str:
        g = json.loads(json.dumps(var["graph"]))
        for n in g.values():
            for k, v in list((n.get("inputs") or {}).items()):
                if isinstance(v, str) and v.startswith("@"):
                    n["inputs"][k] = self.upload(var["inputs"][v])
            if n["class_type"] == "SaveVideo":
                n["inputs"]["filename_prefix"] = prefix
        cid = CLIENT + uuid.uuid4().hex[:8]
        body_d = {"prompt": g, "client_id": cid}
        try:   # GPUVIEW：GPU 任务归属标签放 extra_data.ns_tag（K-OPS-G01）；打标签出错也照常提交
            t = dict(tag or {})
            try:   # 镜像目录里有 comfy_tag.py 就用它（补 family/步数 label）；没有就用 tag 原样
                sp = str(ROOT / "services" / "agent")
                if sp not in sys.path:
                    sys.path.insert(0, sp)
                from ns_agent import comfy_tag as CT  # type: ignore
                st = CT.steps_of(g)
                lab = " ".join(x for x in (CT.family(g), f"{st} 步" if st else "") if x)
                if t.get("label"):
                    lab = f"{lab} · {t['label']}" if lab else t["label"]
                t = CT.make(t.get("agent") or "VIDEO10", t.get("kind") or "video",
                            **{k: v for k, v in {**t, "label": lab}.items() if k in CT.FIELDS[2:]})
            except Exception:  # noqa: BLE001
                t.setdefault("agent", "VIDEO10")
                t.setdefault("kind", "video")
                t.setdefault("v", 1)
                t.setdefault("t", round(time.time(), 1))
            body_d["extra_data"] = {"ns_tag": t}
        except Exception:  # noqa: BLE001
            body_d.pop("extra_data", None)
        body = json.dumps(body_d).encode()
        r = json.loads(api(self.port, "/prompt", body, timeout=120))
        if r.get("node_errors"):
            raise RuntimeError(json.dumps(r["node_errors"], ensure_ascii=False)[:600])
        return r["prompt_id"]

    def result(self, pid):
        h = json.loads(api(self.port, f"/history/{pid}", timeout=30))
        if pid not in h:
            return None
        st = h[pid].get("status", {})
        t0 = t1 = None
        for m in st.get("messages") or []:
            if m[0] == "execution_start":
                t0 = m[1].get("timestamp")
            if m[0] in ("execution_success", "execution_error", "execution_interrupted"):
                t1 = m[1].get("timestamp")
        gpu_s = round((t1 - t0) / 1000.0, 1) if t0 and t1 else None
        if st.get("status_str") == "error":
            err = [m for m in st.get("messages") or [] if m[0] == "execution_error"]
            if not err:
                # K-OPS-310：ComfyUI 记 error 但没有 execution_error（ep03-S3 s3 / ep04-S4 v1 只留下 "[]"）= 被中断 / 撤回 / 进程重启；
                # 写明“interrupted”，不再留空串让人以为是图本身坏了
                intr = [m for m in st.get("messages") or [] if m[0] == "execution_interrupted"]
                node = ((intr[-1][1] or {}).get("node_type") if intr and len(intr[-1]) > 1 else None)
                return {"error": f"interrupted（ComfyUI 无 execution_error{'，停在 ' + str(node) if node else ''}）",
                        "gpu_s": gpu_s, "interrupted": True}
            return {"error": json.dumps(err, ensure_ascii=False)[-500:], "gpu_s": gpu_s}
        for node in h[pid].get("outputs", {}).values():
            for key in ("images", "videos", "gifs"):
                for im in node.get(key, []) or []:
                    if str(im.get("filename", "")).endswith(".mp4"):
                        path = "/".join(x for x in (OUTDIR[self.name], im.get("subfolder"), im["filename"]) if x)
                        return {"path": path, "gpu_s": gpu_s}
        return {"error": "no_output", "gpu_s": gpu_s} if st.get("completed") else None


BROKEN_LANES = {"gpu33:2"}   # CLAUDE.md 红线：坏卡，任何情况都不派（L-194 11-05：gpu36:2 归 NS，视频可派）


def gpu_free_mib(lane_name: str) -> int | None:
    """本机该道所在卡的空闲显存（MiB，nvidia-smi 只读查询）；查不到 → None（调用方按“不够”处理，失败关闭）"""
    try:
        gpu = lane_name.split(":")[1]
        r = subprocess.run(["nvidia-smi", "-i", gpu, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        return int(r.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def vram_gate_ok(name: str, gate: dict, free_fn=None) -> bool:
    """VIDEO-PAR（开关默认关）：control 的 vram_gate = {"gpu36:1": 21000}——这条道所在卡被别的服务（看图 8870 / 人数检测 8893）
    共用时，只有空闲显存 >= 阈值（Pika 约 19 GB + 余量）才提交；没配该道 = 不设限（原行为）"""
    need = (gate or {}).get(name)
    if need is None:
        return True
    free = (free_fn or gpu_free_mib)(name)
    return free is not None and free >= int(need)


def usable_lanes(host: str, hosts_file: Path | None = None) -> dict:
    """W41（11-04）：本机可派视频的道 = PORTS 去掉坏卡 / config/factory/hosts.json 里 enabled=false、不含 video 角色、
    broken_gpus 的道。以前 Runner 直接用 PORTS 全部三道：gpu36:2（坏卡，hosts.json 已 enabled=false）不在 shared_lanes，
    按专用道每道 2 个照派——只是 :8190 没起才没出事。hosts.json 读不到 → 只去掉写死的坏卡（失败关闭到更少的道）"""
    lanes = {n: p for n, p in PORTS.get(host, {}).items() if n not in BROKEN_LANES}
    try:
        h = json.loads(Path(hosts_file or ROOT / "config/factory/hosts.json").read_text(encoding="utf-8"))["hosts"][host]
    except (OSError, ValueError, KeyError):
        return lanes
    broken = {f"{host}:{g}" for g in h.get("broken_gpus") or []}
    spec = h.get("lanes") or {}
    return {n: p for n, p in lanes.items() if n not in broken and n in spec and spec[n].get("enabled", True)
            and "video" in (spec[n].get("roles") or ["video"])}


class Runner:
    def __init__(self, host):
        self.host = host
        self.ctrl_p = VID / f"control_{host}.json"
        jf = (jload(self.ctrl_p, {}) or {}).get("jobs", "jobs.json")
        self.state_p = VID / (f"state_{host}.json" if jf == "jobs.json" else f"state_{host}_validate.json")
        self.lanes = {n: Lane(n, p) for n, p in usable_lanes(host).items()}
        self.st = jload(self.state_p) or {"host": host, "started": time.time(), "shots": {}, "events": []}
        if jf == "jobs.json" and any(x.get("variant", "").startswith(("pdd_", "b24_", "i2v_"))
                                     for r in self.st["shots"].values() for x in r["renders"]):
            # 旧版对照（S10V-1）的状态混在正式状态文件里 → 挪成 _validate，正式从空开始
            os.replace(self.state_p, VID / f"state_{host}_validate.json")
            self.st = {"host": host, "started": time.time(), "shots": {}, "events": []}
        self.lock = threading.Lock()
        # 回填（11-01 之前的出片没记 first_frame）：取出片提交前最近一张 inputs/<镜>_*.jpg
        for sid, r in self.st["shots"].items():
            for x in r["renders"]:
                if not x.get("first_frame") and x.get("t_sub"):
                    c = [p for p in (VID / "inputs").glob(f"{sid}_*.jpg") if p.stat().st_mtime <= x["t_sub"]]
                    if c:
                        x["first_frame"] = str(max(c, key=lambda p: p.stat().st_mtime).relative_to(ROOT))
                        x["first_frame_backfilled"] = True
        self.pool = cf.ThreadPoolExecutor(max_workers=3 if host == "gpu33" else 2)
        self.scoring: dict[str, cf.Future] = {}
        self.env = dict(os.environ, PATH=FFMPEG[host] + ":" + os.environ.get("PATH", ""), OMP_NUM_THREADS="4",
                        OPENBLAS_NUM_THREADS="4", PYTHONUTF8="1")
        self.lane_mode = Path(LANE_MODE).read_text().strip() if host == "gpu36" and Path(LANE_MODE).exists() else "normal"
        self.hold_long = False

    # ------------------------------------------------------------------ 作业
    def ctrl(self):
        return jload(self.ctrl_p, {}) or {}

    def jobs(self):
        c = self.ctrl()
        d = jload(VID / c.get("jobs", "jobs.json"), {"shots": []})
        eps = set(c.get("eps") or range(1, 11))
        claims = _claims() if c.get("jobs", "jobs.json") == "jobs.json" else {}
        now = time.time()
        out = {}
        for s in d["shots"]:
            if s["ep"] not in eps:
                continue
            mine = s["host"] == self.host
            if claims:   # FIX-VID D13：笔记本仲裁的领取（shard_claims.json）不等 night 重编 jobs.json 就生效，两台不会同时出同一镜
                started = bool((self.st["shots"].get(s["shot"]) or {}).get("renders"))
                mine = _VS().effective_mine(self.host, s["shot"], s.get("host"), claims.get(s["shot"]), started, now)
            if mine:
                out[s["shot"]] = s
        return out, c

    def rec(self, sid):
        return self.st["shots"].setdefault(sid, {"renders": [], "status": "pending", "chosen": None})

    def pending(self, shots, validate):
        """→ [(shot, variant)] 可提交的作业（按集、镜顺序；正在出 / 正在打分的镜不发下一版）"""
        out = []
        # K-OPS-E30（L-124）：显式按（集号, 镜号）排，不依赖 jobs.json 的写入顺序——两台道都先吃最小的未完成集
        for sid, sh in sorted(shots.items(), key=lambda kv: (int(kv[1].get("ep") or 99), int(kv[1].get("idx") or str(kv[0]).rsplit("S", 1)[-1] or 99))):
            r = self.rec(sid)
            if not validate:
                self.check_stale(sid, sh, r)
                self.check_lip_redo(sid, r)
                self.repair_idle(sid, sh, r)
            if r["status"] in ("done", "best_effort", "blocked"):
                continue
            if not sh.get("variants"):           # 无可出变体（如无人露脸镜首帧未过契约）→ 等资料，不出
                r["status"] = "waiting_frame"
                continue
            busy = any(x.get("state") in ("submitted", "fetched", "scoring") for x in r["renders"])
            if validate:
                used = {x["variant"] for x in r["renders"]}
                for v, var in sh["variants"].items():
                    if v not in used and var.get("status") in ("ready", "lint_error"):
                        out.append((sid, v))
                continue
            if busy:
                continue
            v = next_variant(sh, r)
            if v:
                out.append((sid, v))
        return out if validate else first_take_first(out, shots, self.st["shots"], self.ctrl())

    def check_lip_redo(self, sid, r):
        """DIRECTOR K-EDT-805（总调度 11-02 批复 r2 第 3 条）：成片里画内对白被 TTS 兜底的镜（data/director/redo_requests.json，
        tools/director/finish.py 写）→ 走和“首帧换版”同一条作废路径：现有视频挪进 superseded（带原因），状态回到待出，
        变体从头算（不计次）。每条请求只用一次（r.lip_redo_applied 记请求键），不写回请求文件"""
        reqs = [q for q in (jload(LIP_REDO, {}) or {}).get("requests") or []
                if q.get("shot") == sid and q.get("status", "pending") == "pending"]
        done = set(r.get("lip_redo_applied") or [])
        new = [q for q in reqs if f"{q.get('timeline')}@{q.get('at')}" not in done]
        if not new or any(x.get("state") in ("submitted", "scoring") for x in r["renders"]):
            return
        q = new[-1]
        keys = sorted(done | {f"{x.get('timeline')}@{x.get('at')}" for x in new})
        n, cap = lip_redo_count(r), lip_redo_cap()
        # VID-LOOP（11-06）：重出视频改不了的兜底原因（no H3 audio）→ 只记账，不作废（镜头没进成片 / 没音轨，重出同一条也一样）
        if lip_unfixable(q) and not q.get("variants"):
            with self.lock:
                r["lip_redo_applied"] = keys
                r["lip_redo_n"] = n            # 记账不计次（lip_redo_count 对旧记录按键数算，这里要写死）
                r["lip_redo_skipped"] = int(r.get("lip_redo_skipped") or 0) + len(new)
            log(self.host, "LIP_REDO_SKIP", sid, q.get("fallback_reason"), "重出视频改不了，不作废", q.get("timeline"))
            self.event("lip_redo_skip", shot=sid, fallback_reason=q.get("fallback_reason"), timeline=q.get("timeline"), rule=LIP_REDO_RULE)
            return
        if n >= cap:                     # 每镜最多作废重出 cap 次（config/post/director.json lip_redo_max_per_shot）；到上限只记账
            with self.lock:
                r["lip_redo_applied"] = keys
                r["lip_redo_n"] = n
                r["lip_redo_capped"] = True
            log(self.host, "LIP_REDO_CAPPED", sid, f"已重出 {n}/{cap} 次，不再作废（L-196 用尽采用最好一版）", q.get("timeline"))
            self.event("lip_redo_capped", shot=sid, n=n, cap=cap, timeline=q.get("timeline"), rule=LIP_REDO_RULE)
            return
        if q.get("variants"):            # 加变体再试（不作废已有出片，最后在全部出片里挑最好的；L-124 ep01-S4）
            with self.lock:
                r["force_queue"] = [v for v in q["variants"] if v not in {x["variant"] for x in r["renders"]}]
                r["status"] = "pending"
                r["lip_redo_applied"] = keys
                r["lip_redo_n"] = n + 1
            log(self.host, "EXTRA_VARIANTS", sid, r["force_queue"], q.get("reason"))
            self.event("extra_variants", shot=sid, variants=r["force_queue"], reason=q.get("reason"))
            return
        with self.lock:
            r.setdefault("superseded", []).extend({**x, "superseded_at": time.time(), "why": q.get("reason"), "rule": LIP_REDO_RULE}
                                                  for x in r["renders"])
            r["renders"] = []
            r["status"] = "pending"
            r["chosen"] = None
            r["lip_redo_applied"] = keys
            r["lip_redo_n"] = n + 1
        log(self.host, "LIP_REDO", sid, q.get("reason"), q.get("timeline"), f"第 {n + 1}/{cap} 次")
        self.event("lip_redo", shot=sid, reason=q.get("reason"), timeline=q.get("timeline"), rule=LIP_REDO_RULE)

    def repair_idle(self, sid, sh, r):
        """VID-LOOP（11-06）状态修复：没有在出 / 在打分的版本却停在 rendering / retry / pending 的镜不能一直挂着——
        ① 口型重出已到上限 → 作废的同首帧版本拿回来一起挑（L-196）；② 已有出片且阶梯用尽（next_variant 为 None）→ 当场定下
        （done / best_effort / blocked，与 after_score 同一条路）。还有变体能出的照常派，不在这里动。
        FIX-VID D8：③ 有变体、没出过、一个都派不了 → blocked（写明原因；整集能落定，成片用静帧占位）；重编后有变体能派 → 自动解封"""
        if r["status"] == "blocked" and r.get("block_kind") == "undispatchable" and not r["renders"] \
                and sh.get("variants") and next_variant(sh, r) is not None:
            with self.lock:
                r["status"] = "pending"
                r.pop("block_kind", None)
                r.pop("block_reason", None)
            log(self.host, "UNBLOCK", sid, "重编后有可派的变体")
            self.event("unblock", shot=sid)
            return
        if r["status"] in SETTLED or r["status"] == "waiting_frame" or in_flight(r):
            return
        why = undispatchable_reason(sh, r)
        if not why:
            r.pop("undispatchable_since", None)
        elif frame_wait_only(sh) and time.time() - float(r.setdefault("undispatchable_since", time.time())) < UNDISPATCHABLE_GRACE_S:
            return                      # 帧还在出：先等（宽限内不阻断，免得整集提前拿占位合成）
        if why:
            with self.lock:
                r.pop("undispatchable_since", None)
                r.update(status="blocked", block_kind="undispatchable", block_reason=why, chosen=None)
            log(self.host, "SHOT_BLOCKED_NO_VARIANT", sid, why[:300])
            self.event("shot_done", shot=sid, chosen=None, status="blocked", renders=0, why="undispatchable")
            return
        if r.get("lip_redo_capped") and sh.get("first_frame"):   # 只在“又来了请求但已到上限”之后拿回；允许的那一次作废照常重出
            with self.lock:
                n = restore_lip_superseded(r, sh.get("first_frame"))
            if n:
                log(self.host, "LIP_REDO_RESTORE", sid, f"口型重出到上限，拿回 {n} 条同首帧的作废版本一起挑")
                self.event("lip_redo_restore", shot=sid, n=n, rule=LIP_REDO_RULE)
        if r["renders"] and next_variant(sh, r) is None:
            with self.lock:
                st = settle_rec(r)
            log(self.host, "SETTLE_IDLE", sid, st, r.get("chosen"), f"renders={len(r['renders'])}（没有在出的版本、阶梯用尽）")
            self.event("shot_done", shot=sid, chosen=r.get("chosen"), status=st, renders=len(r["renders"]), why="settle_idle")

    def repair_orphans(self, shots):
        """VID-LOOP（11-06）：state 里有、本机作业里已没有的镜（分片抢活 / 控制文件 eps 改了之后换了主机）停在 rendering / retry
        且没有在出的版本 → 用已有打分定下（done / best_effort），没有打分的回 pending。分片的整集视图按 jobs.json 的 host 取记录，
        这里只是不让本机记录永远挂在 rendering（ep01-S1 11-06 06:14 起被 gpu33 领走后 gpu36 记录空挂）"""
        for sid, r in list(self.st["shots"].items()):
            if sid in shots:
                if r.pop("orphan", None):           # 镜又回到本机作业里 → 撤掉孤儿标记（领取回来 / control eps 改回）
                    log(self.host, "ORPHAN_BACK", sid, r.get("status"))
                continue
            if r.get("status") not in ("rendering", "retry", "pending", "blocked") or in_flight(r) or r.get("orphan"):
                continue
            with self.lock:
                if any(x.get("state") == "scored" for x in r.get("renders") or []):
                    st = settle_rec(r)
                else:
                    # FIX-NIGHT2 #8：被领走的 pending / 阻断（没变体可派）镜也标孤儿：阻断字段清掉（别台在出，合并视图不再显示本机旧阻断）
                    r.pop("block_kind", None)
                    r.pop("block_reason", None)
                    r["status"], st = "pending", "pending"
                r["orphan"] = True
                r["orphan_settled"] = {"t": time.time(), "status": st}
            log(self.host, "ORPHAN_SETTLED", sid, st, r.get("chosen"), "镜已不在本机作业里，记录不再挂在 rendering")
            self.event("orphan_settled", shot=sid, status=st, chosen=r.get("chosen"))

    def check_stale(self, sid, sh, r):
        """首帧换版或被撤（postflight 不再 ok）→ 旧片作废：挪进 superseded，状态回到待出 / 等首帧（总调度 11-01：
        镜头视频必须跟当前过契约的首帧；DATAALIGN 按 from_first 判过期）"""
        used = {x.get("first_frame") for x in r["renders"] if x.get("first_frame")}
        cur = sh.get("first_frame")
        busy = any(x.get("state") in ("submitted", "scoring") for x in r["renders"])
        if busy or not r["renders"] or not used:
            return
        if cur in used and len(used) == 1:
            return
        if cur is None or cur not in used or len(used) > 1:
            with self.lock:
                r.setdefault("superseded", []).extend({**x, "superseded_at": time.time(), "why": "首帧换版 / 撤销"}
                                                      for x in r["renders"])
                r["renders"] = []
                r["status"] = "pending" if cur else "waiting_frame"
                r["chosen"] = None
            log(self.host, "STALE", sid, "旧首帧", sorted(used), "→ 现首帧", cur)
            self.event("stale", shot=sid, old=sorted(used), new=cur)

    # ------------------------------------------------------------------ 长镜头道
    def set_lane_mode(self, mode):
        if LONG_LANE not in self.lanes:   # W41：长镜头道是坏卡 / 已停用 → 不切模式；超长镜头留 pending（V2 单镜 ≤6 s 不会走到）
            if mode == "long":
                log(self.host, "LONG_LANE_UNAVAILABLE", LONG_LANE, "坏卡 / hosts.json 停用，超长镜头不派")
            return False
        lane = self.lanes[LONG_LANE]
        mine, foreign = lane.queue()
        unfetched = [x for r in self.st["shots"].values() for x in r["renders"]
                     if x.get("lane") == LONG_LANE and x.get("state") == "submitted"]
        if mine or foreign or unfetched:
            return False
        log(self.host, "LANE_MODE", LONG_LANE, self.lane_mode, "→", mode)
        r = subprocess.run(["bash", LANE_SH, "restart", mode], capture_output=True, text=True, timeout=180)
        log(self.host, "lane.sh", (r.stdout + r.stderr).strip()[-300:])
        for _ in range(60):
            try:
                api(lane.port, "/system_stats", timeout=5)
                break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        lane.uploads.clear()
        self.lane_mode = mode
        self.event("lane_mode", lane=LONG_LANE, mode=mode)
        return True

    # ------------------------------------------------------------------ 主循环
    def event(self, kind, **kw):
        with self.lock:
            self.st["events"].append({"t": time.time(), "kind": kind, **kw})
            self.st["events"] = self.st["events"][-400:]

    def save(self):
        with self.lock:
            self.st["saved"] = time.time()
            self.st["lane_busy_s"] = {n: round(ln.busy_s, 1) for n, ln in self.lanes.items()}
            jsave(self.state_p, self.st)

    def submit_round(self, shots, c):
        validate = c.get("mode") == "validate"
        per_lane = int(c.get("per_lane", 2))
        hold = set(c.get("hold_lanes") or [])
        # 让道（项目方 10-31 夜：图片先于视频）：shared_lanes 里的道只有连续 yield_s 秒没有别人的任务才提交，
        # 且本工具每道最多 1 个，保证出图任务随时能插进来
        shared = set(c.get("shared_lanes") or [])
        yield_s = float(c.get("yield_s", 180))
        gate = c.get("vram_gate") or {}
        # L-206 工位分卡（night 按 config/pipeline/lane_roles.json 写进 control）：lane_roles.video = 本阶段本机视频道，
        # 不在清单里的道一律不派（出图位 / 审图位）；video_lanes = 专用视频道，不受让道（FIX-VID-2）。没写 = 旧行为
        role_video = (c.get("lane_roles") or {}).get("video")
        dedicated = set(c.get("video_lanes") or [])
        shared -= dedicated
        todo = self.pending(shots, validate)
        long_todo = [(s, v) for s, v in todo if shots[s]["variants"][v]["frames"] > LANE_MAX_FRAMES]
        long_inflight = any(x.get("state") == "submitted" and x.get("long") for r in self.st["shots"].values()
                            for x in r["renders"])
        if self.host == "gpu36":
            want = "long" if (long_todo or long_inflight) else "normal"
            if want != self.lane_mode:
                self.hold_long = True
                if self.set_lane_mode(want):
                    self.hold_long = False
            else:
                self.hold_long = False
        normal = [t for t in todo if t not in long_todo]
        for name, lane in lane_order(self.lanes, self.rr_next()):   # FIX-NIGHT2 #8：道按轮换起点派，gpu36:2 不被前两道饿死
            if name in hold or (name == LONG_LANE and self.hold_long):
                continue
            if isinstance(role_video, list) and name not in role_video:
                continue                      # L-206：本阶段这条道不是视频位
            if gate and not vram_gate_ok(name, gate):
                continue
            try:
                mine, foreign = lane.queue()
                lane.down = False
            except Exception as e:  # noqa: BLE001
                if not lane.down:
                    log(self.host, "LANE_DOWN", name, str(e)[:120])
                lane.down = True
                continue
            cap = per_lane
            if foreign:
                lane.last_foreign = time.time()
            if name in shared:
                if foreign or time.time() - getattr(lane, "last_foreign", 0) < yield_s:
                    continue
                cap = 1
            pool = normal
            if name == LONG_LANE and self.lane_mode == "long":
                cap = 1
                pool = long_todo if long_todo else ([] if long_inflight else normal)
            while len(mine) + foreign < cap and pool:
                sid, v = pool.pop(0)
                if (sid, v) in long_todo and name != LONG_LANE:
                    continue
                self.dispatch(shots[sid], v, lane)
                mine.append("x")
                if pool is normal:
                    pass
                todo = [t for t in todo if t != (sid, v)]

    def rr_next(self) -> int:
        self._rr = getattr(self, "_rr", -1) + 1
        return self._rr

    def dispatch(self, sh, v, lane):
        var = sh["variants"][v]
        sid = sh["shot"]
        prefix = f"video10/{sid}/{v}_s{var['seed']}"
        r = self.rec(sid)
        ent = {"variant": v, "recipe": var["recipe"], "seed": var["seed"], "lane": lane.name, "t_sub": time.time(),
               "state": "submitted", "long": var["frames"] > LANE_MAX_FRAMES, "first_frame": sh.get("first_frame"),
               "first_frame_take": sh.get("first_frame_take")}
        try:
            ent["pid"] = lane.submit(var, prefix, {"agent": "VIDEO10", "kind": "video", "episode": sh["ep"],
                                                   "shot": str(sid).rsplit("-", 1)[-1],
                                                   "label": f"{v} {var['recipe']} s{var['seed']}",
                                                   "attempt": len(r["renders"]) + 1, "max_attempts": MAX_RENDERS,
                                                   "job": f"{sid}|{v}"})
        except Exception as e:  # noqa: BLE001
            ent.update(state="submit_error", error=str(e)[:600])
            log(self.host, "SUBMIT_ERR", sid, v, lane.name, str(e)[:300])
        with self.lock:
            r["renders"].append(ent)
            r["status"] = "rendering"
            if r.get("force_next") == v and ent.get("pid"):
                r.pop("force_next", None)
            if ent.get("pid") and v in (r.get("force_queue") or []):
                r["force_queue"] = [x for x in r["force_queue"] if x != v]
            # L-124（DEBUG-RSI，ep01-S1）：提交报错是系统错误，不会触发 collect——以前 4 次报错后这镜永远停在 rendering、看不出卡住。
            # 连续 2 次提交报错 → 标 blocked 并写明原因（看板可见、可开单），修好后用重出请求（redo_requests）放回
            errs = [x for x in r["renders"][-2:] if x.get("state") == "submit_error"]
            if len(errs) >= 2:
                r.update(status="blocked", block_reason="提交报错（系统问题，不是出片质量）：" + str(errs[-1].get("error"))[:200])
                log(self.host, "SHOT_BLOCKED_SUBMIT", sid, r["block_reason"][:200])
                self.event("shot_done", shot=sid, chosen=None, status="blocked", renders=len(r["renders"]))
        log(self.host, "SUBMIT", sid, v, var["recipe"], var["seed"], lane.name, ent.get("pid", "")[:8])

    def poll(self, shots):
        for sid, r in list(self.st["shots"].items()):
            for x in r["renders"]:
                if x.get("state") != "submitted":
                    continue
                lane = self.lanes[x["lane"]]
                try:
                    res = lane.result(x["pid"])
                except Exception:  # noqa: BLE001
                    continue
                if res is None:
                    # 排队里被删掉的（让道时撤回 / 别人清队列）：不在队列、也没有历史 → 记 lost，这一版不算，重新派
                    try:
                        mine, _f = lane.queue()
                    except Exception:  # noqa: BLE001
                        continue
                    if x["pid"] not in mine and time.time() - x.get("t_sub", 0) > 30:
                        x["lost_n"] = x.get("lost_n", 0) + 1
                        if x["lost_n"] >= 3:
                            with self.lock:
                                r["renders"].remove(x)
                                r.setdefault("lost", []).append({**x, "t_lost": time.time()})
                            log(self.host, "LOST", sid, x["variant"], x["lane"], "→ 重新排")
                            break
                    continue
                x["gpu_s"] = res.get("gpu_s")
                x["t_done"] = time.time()
                lane.busy_s += res.get("gpu_s") or 0
                if res.get("error"):
                    x.update(state="error", error=res["error"])
                    log(self.host, "RENDER_ERR", sid, x["variant"], res["error"][:300])
                    self.after_score(shots, sid)
                    continue
                sh = shots.get(sid)
                ep = int(sid[2:4])
                dst = VID / "clips" / f"ep{ep:02d}" / f"{sid}__{x['variant']}_s{x['seed']}.mp4"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(res["path"], dst)
                x.update(state="scoring", file=str(dst.relative_to(ROOT)), src=res["path"])
                log(self.host, "DONE", sid, x["variant"], x["lane"], f"{x['gpu_s']}s")
                var = (sh or {}).get("variants", {}).get(x["variant"], {})
                meta = {"refs": (sh or {}).get("score_refs") or {}, "prompt": var.get("prompt", ""), "size": (sh or {}).get("size"),
                        "first_frame": (sh or {}).get("first_frame")}
                self.scoring[f"{sid}|{x['variant']}"] = self.pool.submit(self.score, sid, x, meta)

    def score(self, sid, x, meta):
        stem = f"{sid}__{x['variant']}"
        clip = ROOT / x["file"]
        sheet = VID / "_thumbs" / f"{stem}.jpg"
        prev = VID / "_preview" / f"{stem}.mp4"
        sheet.parent.mkdir(parents=True, exist_ok=True)
        prev.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = subprocess.run([SCORE_PY, str(ROOT / "tools/series10_video/score_clip.py"), str(clip), str(sheet),
                                json.dumps(meta, ensure_ascii=False)], capture_output=True, text=True, timeout=1500,
                               env=self.env, cwd=str(ROOT))
            line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
            s = json.loads(line[-1]) if line else {"error": r.stderr[-800:]}
        except Exception as e:  # noqa: BLE001
            s = {"error": str(e)[:500]}
        subprocess.run([FFMPEG[self.host] + "/ffmpeg", "-v", "error", "-y", "-threads", "4", "-i", str(clip),
                        "-vf", "scale=360:640", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                        "-maxrate", "1500k", "-bufsize", "3000k", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
                        str(prev)], capture_output=True, timeout=600)
        jsave(VID / "scores" / f"{stem}.json", s)
        return s

    def collect(self, shots):
        for key, fut in list(self.scoring.items()):
            if not fut.done():
                continue
            del self.scoring[key]
            sid, v = key.split("|")
            s = fut.result()
            r = self.rec(sid)
            x = next(x for x in r["renders"] if x["variant"] == v and x.get("state") == "scoring")
            with self.lock:
                x["score"] = s
                x["state"] = "scored"
                x["preview"] = f"{VID_REL}/_preview/{sid}__{v}.mp4"
                x["thumb"] = f"{VID_REL}/_thumbs/{sid}__{v}.jpg"
            g = (s.get("gate") or {})
            log(self.host, "SCORE", sid, v, "PASS" if g.get("pass") else "/".join(g.get("fails") or ["ERR"]),
                "mean", s.get("mean"), "J4", s.get("J4"), "red", s.get("cheek_red_max"), "cuts", len(s.get("cuts") or []),
                "id", {k: (it or {}).get("sface_med") for k, it in (s.get("identity") or {}).items()},
                s.get("error", "")[:200] if s.get("error") else "")
            self.after_score(shots, sid)

    def after_score(self, shots, sid):
        c = self.ctrl()
        r = self.rec(sid)
        sh = shots.get(sid)
        if sh is None:
            return
        if any(x.get("state") in ("submitted", "scoring") for x in r["renders"]):
            return
        scored = [x for x in r["renders"] if x.get("state") == "scored" and not (x.get("score") or {}).get("error")]
        if c.get("mode") == "validate":
            done = {x["variant"] for x in r["renders"] if x.get("state") in ("scored", "error", "submit_error")}
            if done >= {v for v, var in sh["variants"].items() if var.get("status") in ("ready", "lint_error")}:
                r["status"] = "done"
            return
        passed = [x for x in scored if (x["score"].get("gate") or {}).get("pass")]
        if passed:
            settle_rec(r)
            self.event("shot_done", shot=sid, chosen=r["chosen"], renders=len(r["renders"]))
            log(self.host, "SHOT_PASS", sid, r["chosen"], f"renders={len(r['renders'])}")
            return
        if next_variant(sh, r) is None:
            st = settle_rec(r)     # 用尽采用最好一版（L-196）/ 一条打分都没有 → blocked
            if st == "best_effort":
                best = next(x for x in scored if x["variant"] == r["chosen"])
                log(self.host, "SHOT_BEST_EFFORT", sid, best["variant"], best["score"].get("gate", {}).get("fails"))
            else:
                log(self.host, "SHOT_BLOCKED", sid)
            self.event("shot_done", shot=sid, chosen=r.get("chosen"), status=r["status"], renders=len(r["renders"]))
        else:
            r["status"] = "retry"

    def run(self):
        log(self.host, "START vidgen", self.host, "lanes", list(self.lanes), "lane_mode", self.lane_mode)
        # 重启恢复：打分中断的重新打分
        shots, c = self.jobs()
        for sid, r in self.st["shots"].items():
            for x in r["renders"]:
                if x.get("file") and (x.get("state") == "scoring" or (x.get("score") or {}).get("error")):
                    x["state"] = "scoring"
                    sh = shots.get(sid) or {}
                    var = sh.get("variants", {}).get(x["variant"], {})
                    self.scoring[f"{sid}|{x['variant']}"] = self.pool.submit(
                        self.score, sid, x, {"refs": sh.get("score_refs") or {}, "prompt": var.get("prompt", ""), "size": sh.get("size"),
                         "first_frame": sh.get("first_frame")})
        last_save = 0
        while True:
            shots, c = self.jobs()
            if c.get("stop"):
                log(self.host, "STOP requested")
                self.save()
                return
            try:
                self.poll(shots)
                self.collect(shots)
                if c.get("mode") != "validate":
                    self.repair_orphans(shots)
                self.submit_round(shots, c)
            except Exception as e:  # noqa: BLE001
                log(self.host, "LOOP_ERR", repr(e)[:300])
            if time.time() - last_save > 10:
                self.save()
                last_save = time.time()
            if shots and all(self.rec(s)["status"] in ("done", "best_effort", "blocked", "waiting_frame") for s in shots) \
                    and not self.scoring:
                if self.host == "gpu36" and self.lane_mode != "normal":
                    self.set_lane_mode("normal")
                self.save()
                if not c.get("linger"):
                    log(self.host, "ALL_DONE", len(shots))
                    return
            time.sleep(5)


def rescore(host):
    """打分器升级后：本机所有已出片重新打分（不提交、不碰 ComfyUI），更新 scores/ 与 state 里的 score"""
    r = Runner(host)
    shots, _c = r.jobs()
    for sid, rec in r.st["shots"].items():
        sh = shots.get(sid) or {}
        for x in rec["renders"]:
            if not x.get("file"):
                continue
            var = sh.get("variants", {}).get(x["variant"], {})
            x["score"] = r.score(sid, x, {"refs": sh.get("score_refs") or {}, "prompt": var.get("prompt", ""),
                                          "size": sh.get("size"), "first_frame": sh.get("first_frame")})
            x["state"] = "scored"
            g = x["score"].get("gate") or {}
            log(host, "RESCORE", sid, x["variant"], "PASS" if g.get("pass") else "/".join(g.get("fails") or ["ERR"]),
                "size", x["score"].get("size_measured"), "want", sh.get("size"))
    r.save()


def proxies(host, ep):
    """整集出完后：每镜入选版本转 540×960 合成代理（≤2 MB，crf 26），写 video/episodes/epNN/manifest.json，供笔记本合成预览版"""
    st = jload(VID / f"state_{host}.json", {}) or {}
    try:   # 视频按镜分片（默认关）：分片集合并各台 state（helper 的 state / 片子由 shard_relay 送来）；关 = 原样
        import video_shard as VS
        sc = VS.ep_cfg(RUN_ID, ep)
        if sc:
            st = {"shots": VS.merged_shots(VID, ep, VS.ep_hosts(RUN_ID, ep, host), jload(VID / "jobs.json", {}) or {})}
    except ImportError:   # arch-ok: 没有分片模块 = 不分片
        pass
    out_dir = VID / "episodes" / f"ep{ep:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    man = {"ep": ep, "host": host, "t": time.time(), "shots": []}
    # FIX-VID D10：当前作业里每镜的首帧输入（没过闸门的镜 build_jobs 也留在 jobs 里、route=hold）；片子的首帧和它不一致 = 过期片，不进成片
    jobs_ff = {s["shot"]: s for s in (jload(VID / "jobs.json", {}) or {}).get("shots", []) if int(s.get("ep") or 0) == ep}
    for sid, r in sorted(st.get("shots", {}).items(), key=lambda kv: int(kv[0].split("-S")[1])):
        if int(sid[2:4]) != ep:
            continue
        x = next((x for x in r["renders"] if x["variant"] == r.get("chosen") and x.get("file")), None)
        ent = {"shot": sid, "index": int(sid.split("-S")[1]), "status": r.get("status"), "chosen": r.get("chosen")}
        js_ = jobs_ff.get(sid)
        if js_ is not None:
            ent["first_frame"] = js_.get("first_frame")
        if r.get("status") == "blocked":
            ent["block_reason"] = str(r.get("block_reason") or "阻断（没有打分 / 提交报错）")[:300]
        # VID-LOOP（11-06，L-196 用尽采用最好一版）：尽力版（best_effort 的 chosen）也进合成，manifest 标 best_effort；
        # 以前只进 done → 尽力镜在成片里是黑场 / 静帧占位（ep01 S3=black/none），还被当“没 H3 音轨”开口型重出单（S1 死循环）
        if x and r.get("status") not in ("done", "best_effort"):
            ent["excluded"] = f"未达契约（状态 {r.get('status')}，不进合成）"
            x = None
        elif x and js_ is not None and (x.get("first_frame") or None) != (js_.get("first_frame") or None):
            ent["excluded"] = f"过期片：片子首帧 {x.get('first_frame')} ≠ 当前首帧 {js_.get('first_frame')}（D10，不进合成）"
            ent["stale"] = True
            x = None
        elif x and r.get("status") == "best_effort":
            ent["best_effort"] = "尽力版：阶梯用尽采用最好一版（L-196），进合成；闸门不过项见 gate"
        if x:
            dst = out_dir / f"{sid}.mp4"
            subprocess.run([FFMPEG[host] + "/ffmpeg", "-v", "error", "-y", "-threads", "4", "-i", str(ROOT / x["file"]),
                            "-vf", "scale=540:960", "-c:v", "libx264", "-preset", "medium", "-crf", "26", "-maxrate", "1800k",
                            "-bufsize", "3600k", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)],
                           capture_output=True, timeout=900)
            ent.update(proxy=str(dst.relative_to(ROOT)), source=x["file"], recipe=x.get("recipe"), seed=x.get("seed"),
                       gate=(x.get("score") or {}).get("gate"), renders=len(r["renders"]))
        man["shots"].append(ent)
    jsave(out_dir / "manifest.json", man)
    print(json.dumps({"ep": ep, "shots": len(man["shots"]), "with_proxy": sum(1 for e in man["shots"] if e.get("proxy"))}))


def main(argv):
    try:
        set_run(RC.resolve(argv, server=True))   # 失败关闭：没给剧就不跑
    except RC.VideoRunError as e:
        print(f"vidgen：{e}")
        return 2
    (ROOT / "tools/master/sop_gate.py").is_file() and ((sys.path.append(str(ROOT)) if str(ROOT) not in sys.path else None) or __import__("tools.master.sop_gate", fromlist=["_"]).vidgen_guard(RUN_ID, VID, ROOT))  # HARNESS-O：SOP 阶段闸门（服务器上没有证据 = 不挡）
    argv = RC.strip_run(argv)
    if len(argv) == 3 and argv[0] == "proxies" and argv[1] in PORTS:
        proxies(argv[1], int(argv[2]))
        return 0
    if len(argv) == 2 and argv[0] == "rescore" and argv[1] in PORTS:
        rescore(argv[1])
        return 0
    if len(argv) < 2 or argv[0] != "run" or argv[1] not in PORTS:
        print(__doc__)
        return 2
    VID.mkdir(parents=True, exist_ok=True)
    Runner(argv[1]).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
