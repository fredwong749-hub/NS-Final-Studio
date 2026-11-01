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

    python tools/series10_video/vidgen.py run gpu33|gpu36
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
RUN = ROOT / "data/pipeline/runs/series10_v1"
VID = RUN / "video"
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
        return None
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


def next_variant(shot: dict, rec: dict) -> str | None:
    """规则阶梯（见模块文档）；rec = 本镜状态"""
    used = {r["variant"] for r in rec["renders"]}
    vs = shot["variants"]
    # GEN_CONTRACT：preflight 不过的变体不提交（validate 对照模式除外，见 pending）
    ok = lambda v: (v in vs and v not in used and vs[v].get("status") in ("ready", "lint_error")  # noqa: E731
                    and (vs[v].get("preflight") or {}).get("ok", True) and policy_ok(vs[v]))
    fn = rec.get("force_next")          # 系统修复后指定先出的变体（如 K-REN-302 的 mot），用一次就清
    if fn and ok(fn):              # 只在真正派出时清掉（dispatch 里），没派出（道被挂住）下一轮还认
        return fn
    if len(rec["renders"]) >= MAX_RENDERS:
        return None
    last = rec["renders"][-1] if rec["renders"] else None
    if last is None:
        return "v1" if ok("v1") else None
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
        self.last_foreign = time.time()      # 新起的编排器先观察 yield_s 秒再在让道道上提交

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


class Runner:
    def __init__(self, host):
        self.host = host
        self.ctrl_p = VID / f"control_{host}.json"
        jf = (jload(self.ctrl_p, {}) or {}).get("jobs", "jobs.json")
        self.state_p = VID / (f"state_{host}.json" if jf == "jobs.json" else f"state_{host}_validate.json")
        self.lanes = {n: Lane(n, p) for n, p in PORTS[host].items()}
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
        return {s["shot"]: s for s in d["shots"] if s["host"] == self.host and s["ep"] in eps}, c

    def rec(self, sid):
        return self.st["shots"].setdefault(sid, {"renders": [], "status": "pending", "chosen": None})

    def pending(self, shots, validate):
        """→ [(shot, variant)] 可提交的作业（按集、镜顺序；正在出 / 正在打分的镜不发下一版）"""
        out = []
        for sid, sh in shots.items():
            r = self.rec(sid)
            if not validate:
                self.check_stale(sid, sh, r)
                self.check_lip_redo(sid, r)
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
        return out

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
        with self.lock:
            r.setdefault("superseded", []).extend({**x, "superseded_at": time.time(), "why": q.get("reason"), "rule": "K-EDT-805"}
                                                  for x in r["renders"])
            r["renders"] = []
            r["status"] = "pending"
            r["chosen"] = None
            r["lip_redo_applied"] = sorted(done | {f"{x.get('timeline')}@{x.get('at')}" for x in new})
        log(self.host, "LIP_REDO", sid, q.get("reason"), q.get("timeline"))
        self.event("lip_redo", shot=sid, reason=q.get("reason"), timeline=q.get("timeline"), rule="K-EDT-805")

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
        for name, lane in self.lanes.items():
            if name in hold or (name == LONG_LANE and self.hold_long):
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
                x["preview"] = f"data/pipeline/runs/series10_v1/video/_preview/{sid}__{v}.mp4"
                x["thumb"] = f"data/pipeline/runs/series10_v1/video/_thumbs/{sid}__{v}.jpg"
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
            best = min(passed, key=lambda x: x["score"].get("penalty", 9))
            r.update(status="done", chosen=best["variant"])
            self.event("shot_done", shot=sid, chosen=best["variant"], renders=len(r["renders"]))
            log(self.host, "SHOT_PASS", sid, best["variant"], f"renders={len(r['renders'])}")
            return
        if next_variant(sh, r) is None:
            if scored:
                best = min(scored, key=lambda x: x["score"].get("penalty", 9))
                r.update(status="best_effort", chosen=best["variant"])
                log(self.host, "SHOT_BEST_EFFORT", sid, best["variant"], best["score"].get("gate", {}).get("fails"))
            else:
                r.update(status="blocked")
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
    out_dir = VID / "episodes" / f"ep{ep:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    man = {"ep": ep, "host": host, "t": time.time(), "shots": []}
    for sid, r in sorted(st.get("shots", {}).items(), key=lambda kv: int(kv[0].split("-S")[1])):
        if int(sid[2:4]) != ep:
            continue
        x = next((x for x in r["renders"] if x["variant"] == r.get("chosen") and x.get("file")), None)
        ent = {"shot": sid, "index": int(sid.split("-S")[1]), "status": r.get("status"), "chosen": r.get("chosen")}
        if x and r.get("status") != "done":       # 尽力 / 未达契约：不进合成，只在审阅页“未达契约”组里出现
            ent["excluded"] = "未达契约（尽力版不进合成，ITERATION_PROTOCOL §3）"
            x = None
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
