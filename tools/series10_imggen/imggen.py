"""IMGGEN（2026-10-31）：series10_v1 十集图片批量生成——6 卡并行 + 自动质检 + 不合格自动换 seed 重出。

作业来源（SERIES 维护，系统不改内容；每次提交前重读文件，以最新为准）：
  data/pipeline/runs/series10_v1/assets/char_sheet_jobs.json   设定图（每条带 ComfyUI graph，LoadImage 写 @upload:<路径>）
  data/pipeline/runs/series10_v1/assets/first_frame_jobs.json  首帧（有 graph 用 graph；没有就用 tools/prompt_v2/plan_c_preview.graph）
放行控制：images/control.json {"frame_eps": [1,2,...]}（SERIES 回“定稿：epXX”后由 IMGGEN 加集）；运行中随时可改，循环会重读。

6 道（本机隧道）：gpu33 GPU0/1/3 → 18188/18189/18191；gpu36 GPU0/1/2 → 18288/18289/18290（gpu33 GPU2 坏，永不用）。
每道最多同时挂 2 个本工具的任务；某道第一次看到队列里没有别人的任务才启用（别人的任务一直不走 → 日志 LANE_FOREIGN）。

质检（gpu36 自己的 venv_idm，CPU，tools/series10_imggen/score_remote.py）：ArcFace 余弦（与 tools/identity_metric.py 同模型同阈值）、
脸高占画面比例 → 景别、rapidocr 文字/水印。多肢/坏手没有现成检测器 → 记“待人工看”。规则见 knowledge/rules/render_imggen_s10.yaml（K-REN-122/123、K-REV-121、K-AST-221/222、K-OPS-121/122）。
不合格 → 换 seed 重出（每个作业最多 3 次重出），3 次后取最好的一张标“尽力”。每个造型/每镜的入选标“暂定”，项目方可换。

输出：data/pipeline/runs/series10_v1/images/sheets/<char>/、frames/epNN/、state.json、imggen.log
审阅页：data/review_pages/series10_images/index.html

用法：.venv/Scripts/python.exe tools/series10_imggen/imggen.py run      （常驻，直到放行的作业全部出完）
      .venv/Scripts/python.exe tools/series10_imggen/imggen.py page     （只刷新审阅页）
"""
from __future__ import annotations

import copy
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "prompt_v2"))
RUN = ROOT / "data/pipeline/runs/series10_v1"
ASSETS = RUN / "assets"
IMG = RUN / "images"
STATE = IMG / "state.json"
CTRL = IMG / "control.json"
LOG = IMG / "imggen.log"
PAGE = ROOT / "data/review_pages/series10_images/index.html"
POSE = "data/ab/owner_workflows/aisley_char_sheet/character_sheet_pose.png"

LANES = {"gpu33:0": "http://127.0.0.1:18188", "gpu33:1": "http://127.0.0.1:18189", "gpu33:3": "http://127.0.0.1:18191",
         "gpu36:0": "http://127.0.0.1:18288", "gpu36:1": "http://127.0.0.1:18289", "gpu36:2": "http://127.0.0.1:18290"}
# 各道 ComfyUI 的输出目录（质检直接在出图那台机器上读，不经笔记本链路回传；K-OPS-122）
OUTDIR = {"gpu33:0": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu0",
          "gpu33:1": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu1",
          "gpu33:3": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu3",
          "gpu36:0": "/root/work/fredw/comfy/output/gpu0", "gpu36:1": "/root/work/fredw/comfy/output/gpu1",
          "gpu36:2": "/root/work/fredw/comfy/output/gpu2"}
PER_LANE = 2
CLIENT = "imggen-s10-"
MAX_RETRY = 3


def _ct():
    """ns_agent.comfy_tag（GPU 任务归属标签）；导入失败返回 None（照常提交，不带标签）"""
    try:
        sp = str(ROOT / "services" / "agent")
        if sp not in sys.path:
            sys.path.append(sp)
        from ns_agent import comfy_tag as CT
        return CT
    except Exception:  # noqa: BLE001
        return None


def _default_tag(CT, g) -> dict:
    """调用方没给标签：agent 按入口脚本认（ASSETMASTER / REFLOCK 借本工具的 Lane 投），kind/集/镜按图推断"""
    main = str(getattr(sys.modules.get("__main__"), "__file__", "") or (sys.argv[0] if sys.argv else "")).replace("\\", "/").lower()
    agent = "ASSETMASTER" if "/assetmaster/" in main else "REFLOCK" if "/gen_contract/" in main else "IMGGEN"
    inf = CT.infer(g, {"client_id": CLIENT})
    if inf.get("agent") == "ASSETMASTER":                 # 输出目录 assetmaster* 也算 ASSETMASTER
        agent = "ASSETMASTER"
    return CT.make(agent, inf.get("kind") or "frame", episode=inf.get("episode"), shot=inf.get("shot"), obj=inf.get("obj"),
                   label=os.path.basename(main) or None)
R36 = "/root/work/fredw/imggen"
FACE = {"lin_wan": "data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png",
        "gu_chen": "data/assets/identity_refs/gu_chen/gu_chen_face_ref2va.png",
        "chen_yu": "data/assets/identity_refs/chen_yu/chen_yu_face_ref2va.png"}
ALAN_FACE = ROOT / "data/assets/identity_refs/ch_a_lan/ch_a_lan_face_ref2va.png"   # 唯一身份脸（REFLOCK 11-01，出图 = 打分同一张）
NAME2ID = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}
ID2NAME = {v: k for k, v in NAME2ID.items()}
SAME, OTHER = 0.50, 0.40
# 景别（K-REN-101 的 LEAD：中近景 / 近景都是“胸部以上”→ 同一档）。脸框高 / 画面高（768×1344 竖构图）。
SIZE_IDX = {"极近特写": 0, "大特写": 0, "特写": 1, "近景": 2, "中近景": 2, "中景": 3, "中全景": 4, "全身": 5, "全景": 5,
            "远景": 6, "大远景": 6}
SIZE_NAME = ["大特写", "特写", "近景/中近景", "中景", "中全景", "全景", "远景"]
# 22:33 按首批 48 张实测校准（K-REN-122）：全身站姿脸高约 0.088，胸部以上 0.17–0.27，特写 0.27+。旧值 [0.40,0.24,0.14,0.08,0.055,0.03]
BANDS = [0.45, 0.27, 0.17, 0.115, 0.095, 0.05]          # ≥BANDS[i] → 档 i；全都不到 → 档 6
LOCAL_PARTS = ("手", "指", "甲", "鞋", "脚", "足", "腿", "膝", "腰", "锁骨", "背", "唇")
LOCAL_HOST = None        # --lanes local33 / local36：编排跑在出图机器上（INFRA server_deploy.py），只管本机 3 道
HAND_PY = "/root/work/fredw/venv_hand/bin/python"


def configure(mode):
    """--lanes local33|local36：直连本机 ComfyUI（不走隧道），状态 / 日志按机器分文件（state_gpu33.json …）"""
    global LANES, STATE, LOG, LOCAL_HOST
    if mode == "local33":
        LANES = {"gpu33:0": "http://127.0.0.1:8188", "gpu33:1": "http://127.0.0.1:8189", "gpu33:3": "http://127.0.0.1:8191"}
        LOCAL_HOST = "gpu33"
    elif mode == "local36":
        LANES = {"gpu36:0": "http://127.0.0.1:8188", "gpu36:1": "http://127.0.0.1:8189", "gpu36:2": "http://127.0.0.1:8190"}
        LOCAL_HOST = "gpu36"
    if LOCAL_HOST:
        STATE = IMG / f"state_{LOCAL_HOST}.json"
        LOG = IMG / f"imggen_{LOCAL_HOST}.log"


def shard_of(shot):
    """第二轮重出按镜号静态分两台（同一镜的换 seed 重出留在同一台）"""
    import zlib
    return "gpu33" if zlib.crc32(shot.encode("utf-8")) % 2 == 0 else "gpu36"


def open_page():
    if hasattr(os, "startfile"):                 # 只在笔记本（Windows）上打开；服务器上跳过
        os.startfile(PAGE)  # noqa: S606


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def api(url, path, data=None, ctype="application/json", timeout=120):
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def jsave(p, d):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(10):                      # Windows：别的进程正在读 state.json 时 replace 会 Access denied → 稍后重试
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.3 * (i + 1))
    log("WARN state.json 写入被占用，下次再存")


# ---------------------------------------------------------------- 作业


def sheet_jobs():
    d = jload(ASSETS / "char_sheet_jobs.json", {})
    return d.get("jobs", d if isinstance(d, list) else [])


def frame_jobs():
    return (jload(ASSETS / "first_frame_jobs.json", {}) or {}).get("jobs", [])


def char_of(look_key):            # "ch_a_lan_lookA" → "ch_a_lan"
    return look_key.rsplit("_look", 1)[0]


def size_class(h_ratio):
    for i, b in enumerate(BANDS):
        if h_ratio >= b:
            return i
    return len(BANDS)


def set_seed(g, seed):
    for n in g.values():
        ins = n.get("inputs") or {}
        for k in ("seed", "noise_seed"):
            if k in ins and isinstance(ins[k], int):
                ins[k] = seed


def set_prefix(g, prefix):
    for n in g.values():
        if n.get("class_type") == "SaveImage":
            n["inputs"]["filename_prefix"] = prefix


def sheet_graph(key, seed, variant):
    """设定图：用 SERIES 作业里的 graph；林晚/顾沉/陈宇 image1 换成项目方挑定的脸部裁切（总调度 2026-10-31 指令）。
    variant=alanref：阿岚 B/C 重出时以阿岚 A 暂定的脸部裁切为 image1、姿势模板为 image2（跨造型同一人，K-AST-221）。"""
    js = [j for j in sheet_jobs() if j["shot"] == key]
    if not js:
        raise KeyError(key)
    j = js[0]
    g = copy.deepcopy(j["graph"])
    ch = char_of(key)
    enc = next(n for n in g.values() if n.get("class_type") == "TextEncodeQwenImage21")
    if ch in FACE:
        for n in g.values():
            if n.get("class_type") == "LoadImage" and "char_sheets" in n["inputs"]["image"]:
                n["inputs"]["image"] = "@upload:" + FACE[ch]
    if variant == "alanref":
        p = enc["inputs"]["prompt"].replace("<image1>", "<image2>")
        enc["inputs"]["prompt"] = ("Use <image1> only for the character's identity, face, skin tone and hairstyle; do not keep the "
                                   "clothing from <image1>. " + p)
        g["480"] = {"class_type": "LoadImage", "inputs": {"image": "@upload:" + str(ALAN_FACE.relative_to(ROOT)).replace("\\", "/")}}
        pose_node = enc["inputs"]["images.image_1"]
        enc["inputs"]["images.image_1"] = ["480", 0]
        enc["inputs"]["images.image_2"] = pose_node
    set_seed(g, seed)
    set_prefix(g, f"imggen_s10/{key}_s{seed}")
    return g, enc["inputs"]["prompt"]


def frame_job(shot):
    return next((j for j in frame_jobs() if j["shot"] == shot), None)


def frame_graph(shot, seed):
    """K-REN-134（REFLOCK 接管，总调度 11-01）：首帧一律现场经唯一出图路径构建——ns_agent.frame_job.build_first（系统剧本 +
    asset_refs 槽位 + 编译器）→ ns_render.unified_frame.build_graph（frame_v9）。不再使用 first_frame_jobs.json 里存的旧图
    （其中有 lin_wan_qi_v1 / 非 v9），也不在这里拼提示词。出图后由 post_frame 按 frame_v9 做 lanczos 缩回 + USM。"""
    sys.path[:0] = [str(ROOT / p) for p in ("services/agent", "services/render_router", "packages/schema") if str(ROOT / p) not in sys.path]
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    script = P.load_script()
    project = UF.project_for(script)
    ep, sh = P.find_shot(script, shot)
    job = FJ.build_first(project, ep, sh, script.globals)
    g, _eff, prompt = UF.build_graph(job, seed, lambda p: "@upload:" + Path(p).resolve().relative_to(ROOT.resolve()).as_posix(),
                                     f"imggen_s10/{shot}_s{seed}")
    return g, prompt, list(job["refs"])


def post_frame(dest: Path) -> None:
    """frame_v9 交付后处理（与 ns_render.image_params.post_file 同参数）：原图另存 *_raw.png，dest 换成交付图"""
    sys.path[:0] = [str(ROOT / p) for p in ("services/render_router",) if str(ROOT / p) not in sys.path]
    from ns_render import image_params as IP
    from ns_render import unified_frame as UF
    eff = IP.resolve(UF.preset_id(), {"style_suffix": ""})
    post = IP.post_file(dest, eff)
    if post:
        raw = dest.with_name(dest.stem + "_raw.png")
        os.replace(dest, raw)
        os.replace(post["path"], dest)


# ---------------------------------------------------------------- ComfyUI


class Lane:
    def __init__(self, name, url):
        self.name, self.url = name, url
        self.enabled = False
        self.first_seen = time.time()
        self.foreign_warned = False
        self.enabled_at = None
        self.busy_s = 0.0
        self.uploads = {}
        self.inflight = {}            # pid → task
        self.inflight_seen = {}
        self.down = False

    def queue(self):
        d = json.loads(api(self.url, "/queue", timeout=20))
        items = d["queue_running"] + d["queue_pending"]
        mine = [it[1] for it in items if str((it[3] or {}).get("client_id", "")).startswith(CLIENT)]
        foreign = [it[1] for it in items if not str((it[3] or {}).get("client_id", "")).startswith(CLIENT)]
        running_mine = any(str((it[3] or {}).get("client_id", "")).startswith(CLIENT) for it in d["queue_running"])
        return mine, foreign, running_mine

    def upload(self, rel):
        if rel in self.uploads:
            return self.uploads[rel]
        p = ROOT / rel
        buf = io.BytesIO()
        Image.open(p).convert("RGB").save(buf, "JPEG", quality=95)
        b = "----imggen" + uuid.uuid4().hex
        name = "imggen_" + p.stem + ".jpg"
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n").encode() + buf.getvalue() + \
            (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nimggen_s10\r\n"
             f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n").encode()
        r = json.loads(api(self.url, "/upload/image", body, f"multipart/form-data; boundary={b}", timeout=300))
        nm = (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]
        self.uploads[rel] = nm
        return nm

    def submit(self, g, front=False, tag: dict | None = None):
        """tag：GPU 任务归属标签（ns_agent.comfy_tag.make 的结果，K-OPS-G01）；不给就按调用方脚本和图自动补一份"""
        g = copy.deepcopy(g)
        for n in g.values():
            for k, v in list((n.get("inputs") or {}).items()):
                if isinstance(v, str) and v.startswith("@upload:"):
                    n["inputs"][k] = self.upload(v[len("@upload:"):])
        body_d = {"prompt": g, "client_id": CLIENT + uuid.uuid4().hex[:8], **({"front": True} if front else {})}
        try:   # 打标签出错也照常提交（不带标签）
            CT = _ct()
            if CT is not None:
                CT.attach(body_d, tag or _default_tag(CT, g))
        except Exception:  # noqa: BLE001
            body_d.pop("extra_data", None)
        body = json.dumps(body_d).encode()
        return json.loads(api(self.url, "/prompt", body, timeout=120))["prompt_id"]

    def fetch(self, pid, dest: Path):
        h = json.loads(api(self.url, f"/history/{pid}", timeout=30))
        if pid not in h:
            return None
        st = h[pid].get("status", {})
        if st.get("status_str") == "error":
            return "error:" + json.dumps(st.get("messages", ""))[-300:]
        for node in h[pid].get("outputs", {}).values():
            for im in node.get("images", []):
                self.last_host_path = "/".join(x for x in (OUTDIR[self.name], im["subfolder"], im["filename"]) if x)
                q = f"/view?filename={urllib.parse.quote(im['filename'])}&subfolder={urllib.parse.quote(im['subfolder'])}&type={im['type']}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(api(self.url, q, timeout=180))
                return "ok"
        return None if not st.get("completed") else "error:no_output"


import urllib.parse  # noqa: E402


# ---------------------------------------------------------------- 质检（gpu36）


def ssh(cmd, timeout=600, host="gpu36", stdin=None):
    if host == LOCAL_HOST:
        return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                              errors="replace", input=stdin)
    return _rssh().run_retry(host, cmd, input=stdin, timeout=timeout, tries=1, text=True)   # 原来不重试：tries=1

def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rssh_41", Path(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod



def scp(srcs, dst, timeout=900):
    return subprocess.run(["scp", "-q", "-o", "BatchMode=yes", *srcs, "gpu36:" + dst], capture_output=True, text=True,
                          timeout=timeout)


def qc_batch(files: dict[str, tuple]):
    """files: id → (本地 png, 出图机器, 机器上的路径)。有机器路径的就在那台机器上打分（只传几 KB 清单）；
    没有的（旧记录）转 JPEG 传到 gpu36。返回合并后的 {"items", "ref_emb", "cross"}。"""
    by_host: dict[str, list] = {}
    legacy = {}
    for fid, (p, host, hp) in files.items():
        if host and hp:
            by_host.setdefault(host, []).append({"id": fid, "path": hp})
        else:
            legacy[fid] = p
    merged = {"items": {}, "ref_emb": {}, "cross": {}}
    for host, items in by_host.items():
        refs = {k: [f"{R36}/refs/{Path(v).name}"] for k, v in FACE.items()}
        man = json.dumps({"refs": refs, "items": items}, ensure_ascii=False)
        r = ssh(f"cd {R36} || exit 1; /root/work/fredw/venv_idm/bin/python score_remote.py - 2>/dev/null", host=host, stdin=man)
        out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
        if not out:
            raise RuntimeError(f"score@{host} " + r.stderr[-300:])
        d = json.loads(out[-1])
        fr = [{"id": it["id"], "path": it["path"], "faces": len((d["items"].get(it["id"]) or {}).get("faces", []))}
              for it in items if it["id"].startswith("frame:")]
        if fr:                                    # K-REV-123：坏手 / 多肢筛查（只标可疑）
            try:
                rh = ssh(f"cd {R36} || exit 1; {HAND_PY} hands_remote.py 2>/dev/null", host=host,
                         stdin=json.dumps({"items": fr}, ensure_ascii=False), timeout=600)
                ho = [ln for ln in rh.stdout.splitlines() if ln.startswith("{")]
                hd = json.loads(ho[-1]) if ho else {}
                for fid, v in hd.items():
                    if fid in d["items"]:
                        d["items"][fid]["hand_check"] = v
            except Exception as e:  # noqa: BLE001
                log("hand_check_err", host, repr(e)[:120])
        for k in ("items", "ref_emb", "cross"):
            merged[k].update(d.get(k, {}))
    if legacy:
        d = qc_batch_scp(legacy)
        for k in ("items", "ref_emb", "cross"):
            merged[k].update(d.get(k, {}))
    return merged


def qc_batch_scp(files: dict[str, Path]):
    """files: id → 本地 png。转 JPEG q92 传到 gpu36 打分，返回 score_remote 的 items 与 ref_emb。"""
    b = time.strftime("%H%M%S") + uuid.uuid4().hex[:4]
    tmp = IMG / "_qc" / b
    tmp.mkdir(parents=True, exist_ok=True)
    items = []
    for i, (fid, p) in enumerate(files.items()):
        q = tmp / f"{i:03d}.jpg"
        im = Image.open(p).convert("RGB")
        im = im.resize((im.width * 3 // 4, im.height * 3 // 4))      # 只影响像素数，脸高占比不变
        im.save(q, "JPEG", quality=88)
        items.append({"id": fid, "path": f"{R36}/in/{b}/{q.name}"})
    refs = {k: [f"{R36}/refs/{Path(v).name}"] for k, v in FACE.items()}
    (tmp / "manifest.json").write_text(json.dumps({"refs": refs, "items": items}, ensure_ascii=False), encoding="utf-8")
    ssh(f"mkdir -p {R36}/in/{b}")
    r = scp([str(x) for x in sorted(tmp.iterdir())], f"{R36}/in/{b}/")
    if r.returncode:
        raise RuntimeError("scp " + r.stderr[-300:])
    r = ssh(f"cd {R36} || exit 1; /root/work/fredw/venv_idm/bin/python score_remote.py in/{b}/manifest.json 2>/dev/null; "
            f"rm -rf {R36}/in/{b}")
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not out:
        raise RuntimeError("score " + r.stderr[-300:])
    for x in tmp.iterdir():
        x.unlink()
    tmp.rmdir()
    return json.loads(out[-1])


def cos(a, b):
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# ---------------------------------------------------------------- 主循环


class Runner:
    def __init__(self):
        IMG.mkdir(parents=True, exist_ok=True)
        self.st = jload(STATE, None) or {"jobs": {}, "ref_emb": {}, "events": [], "milestones": {}}
        self.lanes = {n: Lane(n, u) for n, u in LANES.items()}
        self.lk = threading.RLock()
        self.stopping = False
        self.todo: list[dict] = []           # 待提交任务
        self.qc_in: dict[str, tuple] = {}    # attempt id → (job key, attempt)
        self.qc_out: queue.Queue = queue.Queue()
        self.qc_busy = False
        self.t0 = time.time()
        for j in self.st["jobs"].values():   # 断点续跑：已提交的按 pid 接回原道；没提交的重排；出完没打分的补打分
            for a in j["attempts"]:
                dest = self.dest(j, a)
                if a.get("state") == "submitted" and a.get("pid") and a.get("lane") in self.lanes:
                    if not self.lanes[a["lane"]].enabled:
                        ln = self.lanes[a["lane"]]
                        ln.enabled, ln.enabled_at = True, time.time()
                    self.lanes[a["lane"]].inflight[a["pid"]] = {"key": j["key"], "aid": a["id"]}
                elif a.get("state") == "queued":
                    a["state"] = "lost"
                elif a.get("state") == "done" or (a.get("state") == "scored" and any(
                        f.get("emb") is None for f in (a.get("qc_raw") or {}).get("faces", []))):
                    a["state"] = "done"                  # 旧版打分没带向量 → 重打
                    a.pop("qc", None)
                    a.setdefault("t_done", time.time())
                    self.qc_in[a["id"]] = dest

    # ---- 作业表
    def save(self):
        with self.lk:
            jsave(STATE, self.st)

    def job(self, key, **init):
        if key not in self.st["jobs"]:
            self.st["jobs"][key] = {"key": key, "attempts": [], "status": "open", **init}
        return self.st["jobs"][key]

    def add_attempt(self, key, seed, variant="", prio=50):
        j = self.st["jobs"][key]
        a = {"id": f"{key}#{len(j['attempts'])}", "seed": seed, "variant": variant, "state": "queued", "t": time.time()}
        j["attempts"].append(a)
        self.todo.append({"key": key, "aid": a["id"], "prio": prio, "n": len(self.todo)})

    def attempt(self, aid):
        key = aid.rsplit("#", 1)[0]
        return self.st["jobs"][key], next(a for a in self.st["jobs"][key]["attempts"] if a["id"] == aid)

    def plan(self):
        """把放行的作业补进 state（只补没有的）。"""
        ctrl = jload(CTRL, {}) or {}
        redo = ctrl.get("redo") or []
        if redo:                                  # 第二轮：只重出点名的镜（新编译器提示词，新 seed，每镜 ≤3 次）
            for fj in frame_jobs():
                if fj["shot"] not in redo or (LOCAL_HOST and shard_of(fj["shot"]) != LOCAL_HOST):
                    continue
                key = "frame:" + fj["shot"]
                if key in self.st["jobs"]:
                    continue
                self.job(key, kind="frame", shot=fj["shot"], ep=fj["ep"], size=fj["size"], on_screen=fj.get("on_screen", []),
                         round=int(ctrl.get("round", 2)), max_retry=int(ctrl.get("max_tries", 3)) - 1)
                self.add_attempt(key, int(fj["seed"]) + 50000, "", 100 + fj["ep"])
            return
        for sj in (sheet_jobs() if ctrl.get("sheets", True) else []):
            key = "sheet:" + sj["shot"]
            ch = char_of(sj["shot"])
            if key not in self.st["jobs"]:
                j = self.job(key, kind="sheet", look=sj["shot"], char=ch, outfit=sj.get("outfit_zh", ""), use=sj.get("use", ""))
                prio = 10 if ch == "ch_a_lan" else 20
                # 阿岚 B/C 先等 A 选出，再决定用纯文字还是带 A 脸（见 sheets_eval）；纯文字两 seed 照常先出
                self.add_attempt(key, sj["seed"], "", prio)
            else:
                j = self.st["jobs"][key]
                if not any(a["seed"] == sj["seed"] and not a["variant"] for a in j["attempts"]):
                    self.add_attempt(key, sj["seed"], "", 10 if ch == "ch_a_lan" else 20)
        eps = set(ctrl.get("frame_eps", []))
        for fj in frame_jobs():
            if fj["ep"] not in eps:
                continue
            key = "frame:" + fj["shot"]
            if key in self.st["jobs"]:
                continue
            st_ = str(fj.get("status", ""))
            refs_ok = bool(fj.get("refs")) and all((ROOT / r).exists() for r in fj["refs"]) and all(
                any(n.get("class_type") == "LoadImage" and n["inputs"].get("image") == "@upload:" + r
                    for n in (fj.get("graph") or {}).values()) for r in fj["refs"])
            if not (st_.startswith("ready") or (st_.startswith("blocked:缺身份参考") and refs_ok)):
                continue                     # 阿岚 4 镜：image_jobs.py 补上参考（文件存在且 graph 已挂）即视为解除
            self.job(key, kind="frame", shot=fj["shot"], ep=fj["ep"], size=fj["size"], on_screen=fj.get("on_screen", []))
            self.add_attempt(key, fj["seed"], "", 100 + fj["ep"])

    # ---- 提交 / 回收
    def lane_loop(self, ln):
        """每道一个线程（K-OPS-121）：一条隧道卡住只影响自己那道。网络调用在锁外，改状态在锁内。"""
        last = time.time()
        while not self.stopping:
            dt, last = time.time() - last, time.time()
            try:
                self.pump_lane(ln, dt)
            except Exception as e:  # noqa: BLE001
                log("LANE_ERR", ln.name, repr(e)[:200])
            time.sleep(4)

    def pump_lane(self, ln, dt):
        try:
            mine, foreign, running_mine = ln.queue()
            if ln.down:
                log("LANE_UP", ln.name)
            ln.down = False
        except Exception as e:  # noqa: BLE001
            if not ln.down:
                log("LANE_DOWN", ln.name, str(e)[:80])
            ln.down = True
            return
        if not ln.enabled:
            if not foreign:
                ln.enabled, ln.enabled_at = True, time.time()
                log("LANE_ON", ln.name)
            elif time.time() - ln.first_seen > 600 and not ln.foreign_warned:
                ln.foreign_warned = True
                log("LANE_FOREIGN", ln.name, f"10 分钟后仍有别人的任务 {len(foreign)} 个")
                with self.lk:
                    self.st["events"].append({"t": time.strftime("%F %T"), "lane_foreign": ln.name, "n": len(foreign)})
            return
        if running_mine:
            ln.busy_s += dt
        ln.mine = set(mine)
        for pid in mine:
            ln.inflight_seen.pop(pid, None)
        # 提交（INFRA 22:20：道深度按服务器队列里还没跑完的算，图一出完就补交；取回在 fetch_loop 线程里）
        if ln.name in set((jload(CTRL, {}) or {}).get("hold_lanes", [])):
            if not getattr(ln, "held", False):
                ln.held = True
                log("LANE_HOLD", ln.name, "暂停新提交（control.json hold_lanes）；队列剩", len(mine))
            if not mine and not ln.inflight and not getattr(ln, "held_empty", False):   # K-OPS-I04：出完未取回的也要为 0
                ln.held_empty = True
                log("LANE_HELD_EMPTY", ln.name)
            return
        if getattr(ln, "held", False):
            ln.held = ln.held_empty = False
            log("LANE_RESUME", ln.name)
        depth = len(mine)
        while depth < PER_LANE:
            with self.lk:
                if not self.todo:
                    return
                self.todo.sort(key=lambda t: (t["prio"], t["n"]))
                task = self.todo.pop(0)
                j, a = self.attempt(task["aid"])
            try:
                if j["kind"] == "sheet":
                    g, p = sheet_graph(j["look"], a["seed"], a["variant"])
                    refs = None
                else:
                    g, p, refs = frame_graph(j["shot"], a["seed"])
                tag = None
                try:   # GPU 任务归属标签（K-OPS-G01）
                    CT = _ct()
                    if CT is not None:
                        n_try = next((i for i, x in enumerate(j["attempts"]) if x is a), len(j["attempts"]) - 1) + 1
                        sh = str(j.get("shot") or "")
                        tag = CT.make("IMGGEN", "sheet" if j["kind"] == "sheet" else "first_frame",
                                      episode=j.get("ep"), shot=sh.rsplit("-", 1)[-1] if sh else None,
                                      obj=j.get("look") if j["kind"] == "sheet" else None,
                                      label=a.get("variant") or None, attempt=n_try,
                                      max_attempts=int(j.get("max_retry", MAX_RETRY)) + 1, job=a.get("id"))
                except Exception:  # noqa: BLE001
                    tag = None
                pid = ln.submit(g, tag=tag)
            except Exception as e:  # noqa: BLE001
                log("submit_err", ln.name, a["id"], str(e)[:160])
                with self.lk:
                    self.todo.append(task)
                return
            depth += 1
            with self.lk:
                a["prompt"] = p
                if refs is not None:
                    a["refs"] = refs
                a.update(state="submitted", pid=pid, lane=ln.name, t_sub=time.time())
                ln.inflight[pid] = task
                ln.mine.add(pid)
                log("submit", ln.name, a["id"], "seed", a["seed"], a["variant"])
                self.save()

    def fetch_loop(self, ln):
        while not self.stopping:
            try:
                self.fetch_lane(ln)
            except Exception as e:  # noqa: BLE001
                log("FETCH_ERR", ln.name, repr(e)[:200])
            time.sleep(3)

    def fetch_lane(self, ln):
        # 服务器上已经不在队列里、但我们以为还挂着的 → 回收（成功 / 失败），队列里有的不必查 history
        for pid, task in list(ln.inflight.items()):
            if pid in getattr(ln, "mine", set()):
                continue
            with self.lk:
                j, a = self.attempt(task["aid"])
                dest = self.dest(j, a)
            try:
                r = ln.fetch(pid, dest)
            except Exception as e:  # noqa: BLE001
                log("fetch_err", ln.name, str(e)[:80])
                continue
            if r is None:
                if time.time() - ln.inflight_seen.get(pid, time.time()) > 900:   # 不在队列也没有结果 15 分钟 → 当丢失重交
                    with self.lk:
                        del ln.inflight[pid]
                        a["state"] = "lost"
                    log("LOST", ln.name, a["id"])
                ln.inflight_seen.setdefault(pid, time.time())
                continue
            with self.lk:
                del ln.inflight[pid]
                a["t_done"] = time.time()
                if r == "ok":
                    if j["kind"] != "sheet":
                        post_frame(dest)                  # K-REN-134：frame_v9 的 1.5× 出图 → 交付尺寸
                    a["host"], a["host_path"] = a["lane"].split(":")[0], getattr(ln, "last_host_path", None)
                    a["state"], a["file"] = "done", str(dest.relative_to(ROOT)).replace("\\", "/")
                    a["render_s"] = round(a["t_done"] - a["t_sub"], 1)
                    self.qc_in[a["id"]] = dest
                    log("done", ln.name, a["id"], a["seed"], f"{a['render_s']}s")
                    try:
                        thumb(a["file"])                  # 服务器上就地出 360 px 缩略图，笔记本 sync_thumbs 只拉它
                    except Exception:  # noqa: BLE001
                        pass
                    self.save()
                else:
                    a["state"], a["err"] = "error", r
                    log("ERROR", ln.name, a["id"], r[:200])
                    self.after_attempt(j)

    def dest(self, j, a):
        if j["kind"] == "sheet":
            v = "_alanref" if a["variant"] == "alanref" else ""
            return IMG / "sheets" / j["char"] / f"{j['look']}_s{a['seed']}{v}.png"
        return IMG / "frames" / f"ep{j['ep']:02d}" / f"{j['shot']}_s{a['seed']}.png"

    # ---- 质检
    def pump_qc(self):
        while not self.qc_out.empty():
            res = self.qc_out.get()
            self.qc_busy = False
            if isinstance(res, Exception):
                log("QC_ERR", str(res)[:200])
                continue
            batch, out = res
            self.st["ref_emb"].update(out.get("ref_emb", {}))
            self.st["ref_cross"] = out.get("cross", {})
            touched = set()
            for aid in batch:
                j, a = self.attempt(aid)
                a["qc_raw"] = out["items"].get(aid)
                a["state"] = "scored"
                touched.add(j["key"])
            for k in touched:
                self.after_attempt(self.st["jobs"][k])
            self.save()
        if self.qc_busy or not self.qc_in:
            return
        inflight = sum(len(ln.inflight) for ln in self.lanes.values())
        oldest = min(self.attempt(a)[1]["t_done"] for a in self.qc_in)
        if len(self.qc_in) >= 4 or time.time() - oldest > 45 or inflight == 0:
            batch = dict(list(self.qc_in.items())[:24])
            for k in batch:
                del self.qc_in[k]
            self.qc_busy = True
            info = {}
            for k, v in batch.items():
                a = self.attempt(k)[1]
                info[k] = (v, a.get("host"), a.get("host_path"))

            def work():
                try:
                    self.qc_out.put((list(batch), qc_batch(info)))
                except Exception as e:  # noqa: BLE001
                    with self.lk:
                        for k, v in batch.items():
                            self.qc_in[k] = v
                    self.qc_out.put(e)
            threading.Thread(target=work, daemon=True).start()

    # ---- 判定
    def thr_other(self, me, other):
        c = (self.st.get("ref_cross") or {})
        x = c.get(f"{me}~{other}", c.get(f"{other}~{me}"))
        return max(OTHER, x + 0.05) if x is not None else OTHER   # K-REV-121：参考彼此就像时，“不像他人”门槛跟着抬

    def refs_now(self):
        r = {k: v for k, v in self.st["ref_emb"].items()}
        if self.st.get("alan_emb"):
            r["ch_a_lan"] = self.st["alan_emb"]
        return r

    def sims(self, emb):
        return {k: round(cos(emb, v), 4) for k, v in self.refs_now().items()}

    def eval_sheet(self, j, a):
        q = a.get("qc_raw") or {}
        fs = q.get("faces", [])
        ch = j["char"]
        res = {"faces": len(fs), "text": [t["text"] for t in q.get("text", [])], "hands": "待人工看"}
        if not fs:
            res.update(ok=False, why="无脸", score=-1)
            return res
        main = fs[0]
        s = self.sims(main["emb"])
        if ch == "ch_a_lan" and "ch_a_lan" not in s:
            # 阿岚 A 尚无参考：左栏特写脸 vs 第二栏正面全身脸 的自洽度
            sec = fs[1] if len(fs) > 1 else None
            selfc = round(cos(main["emb"], sec["emb"]), 4) if sec else 0.0
            others = {k: v for k, v in s.items()}
            ok = selfc >= SAME and all(v < self.thr_other(ch, k) for k, v in others.items())
            res.update(self_consistency=selfc, others=others, ok=ok, score=selfc - max(others.values() or [0]),
                       why="" if ok else f"自洽{selfc:.2f}/他人{max(others.values() or [0]):.2f}")
            return res
        me = s.get(ch, 0.0)
        others = {k: v for k, v in s.items() if k != ch}
        bad = {k: v for k, v in others.items() if v >= self.thr_other(ch, k)}
        ok = me >= SAME and not bad and not res["text"]
        res.update(self_sim=me, others=others, ok=ok, score=me - max(others.values() or [0]),
                   why="" if ok else (f"本人{me:.2f}" if me < SAME else "") + (f" 像{list(bad)}" if bad else "")
                   + (" 有字" if res["text"] else ""))
        return res

    def eval_frame(self, j, a):
        q = a.get("qc_raw") or {}
        fs = q.get("faces", [])
        fj = frame_job(j["shot"]) or {}
        prompt = a.get("prompt", fj.get("prompt", ""))
        refs = self.refs_now()
        exp = [NAME2ID[c] for c in j["on_screen"] if c in NAME2ID and NAME2ID[c] in refs]
        texts = [t["text"] for t in q.get("text", [])]
        res = {"faces": len(fs), "text": texts, "hands": "待人工看", "expect": exp}
        # 身份：贪心配对（每张脸只配一个角色，取余弦最高的组合）
        pairs = sorted(((cos(f["emb"], refs[c]), i, c) for i, f in enumerate(fs) for c in exp), reverse=True)
        used_f, got = set(), {}
        for s_, i, c in pairs:
            if i in used_f or c in got:
                continue
            used_f.add(i)
            got[c] = (round(s_, 4), i)
        ids, id_ok = {}, True
        for c in exp:
            if c not in got:
                ids[c] = None
                id_ok = False
                continue
            s_, i = got[c]
            oth = {k: round(cos(fs[i]["emb"], v), 4) for k, v in refs.items() if k != c}
            okc = s_ >= SAME and all(v < self.thr_other(c, k) for k, v in oth.items())
            ids[c] = {"sim": s_, "max_other": max(oth.values() or [0]), "ok": okc}
            id_ok = id_ok and okc
        res["ids"] = ids
        # 坏手 / 多肢（K-REV-123：只标可疑，不判不合格）
        hc = q.get("hand_check")
        res["hands"] = ("可疑：" + "；".join(hc["flags"])) if hc and hc.get("flags") else ("自动未见异常" if hc else "待人工看")
        # 景别
        want = SIZE_IDX.get(j["size"])
        head = prompt[:40]
        subject = fj.get("framing_subject")
        local = want is not None and want <= 1 and any(w in head for w in LOCAL_PARTS) and not fs
        if subject in ("part", "object"):
            # K-REN-123：局部特写不判身份；画面里出现完整人物（脸高 < 胸部以上档）= 退成了人物镜头
            wide = [f for f in fs if f["h_ratio"] < BANDS[2]]
            id_ok, res["ids"] = True, {c: "局部" for c in exp}
            res.update(framing="局部特写" + ("（出现完整人物）" if wide else ""), frame_ok=not wide)
            if wide:
                res["size_got"] = SIZE_NAME[size_class(wide[0]["h_ratio"])]
        elif local:
            res.update(framing="局部特写（无脸，跳过身份/景别）", frame_ok=True)
            id_ok, res["ids"] = True, {c: "局部" for c in exp}
        elif want is None or not exp:
            res.update(framing="无指定角色脸，未判", frame_ok=True)
        else:
            mains = [fs[got[c][1]] for c in exp if c in got]
            if mains:
                hr = max(m["h_ratio"] for m in mains)
                got_c = size_class(hr)
                res.update(face_h=hr, size_got=SIZE_NAME[got_c], size_want=j["size"], frame_ok=abs(got_c - want) <= 1,
                           size_delta=got_c - want)
                res["framing"] = f"{SIZE_NAME[got_c]}（脸高 {hr:.0%}）"
            else:
                res.update(framing="未检出指定角色脸", frame_ok=False)
        if not exp and not local:
            id_ok = True
        res["id_ok"] = id_ok
        res["text_ok"] = not texts
        res["ok"] = bool(id_ok and res["frame_ok"] and res["text_ok"])
        mins = [v["sim"] for v in ids.values() if isinstance(v, dict)]
        res["score"] = (2 if id_ok else 0) + (1 if res["frame_ok"] else 0) + (1 if res["text_ok"] else 0) + (min(mins) if mins else 0.5)
        why = []
        if not id_ok:
            why.append("身份" + ",".join(f"{ID2NAME[c]}{(v or {}).get('sim', 0):.2f}" if isinstance(v, dict) or v is None else c
                                         for c, v in ids.items()))
        if not res["frame_ok"]:
            why.append(f"景别 要{j['size']} 得{res.get('size_got', '?')}")
        if texts:
            why.append("有字")
        res["why"] = "；".join(why)
        return res

    def after_attempt(self, j):
        if any(a["state"] in ("queued", "submitted", "done") for a in j["attempts"]):
            return                                   # 还有没出完 / 没打分的
        for a in j["attempts"]:
            if a["state"] == "scored" and "qc" not in a:
                a["qc"] = self.eval_sheet(j, a) if j["kind"] == "sheet" else self.eval_frame(j, a)
                log("qc", a["id"], "通过" if a["qc"]["ok"] else "不过", a["qc"].get("why", ""))
        if j["kind"] == "sheet" and j["char"] == "ch_a_lan" and not j["look"].endswith("A") and not self.st.get("alan_emb"):
            return                                   # 阿岚 B/C 等 A 暂定后再判
        self.decide(j)

    def decide(self, j):
        scored = [a for a in j["attempts"] if a.get("qc")]
        passed = [a for a in scored if a["qc"]["ok"]]
        retries = sum(1 for a in j["attempts"] if a.get("retry"))
        # K-REV-122：双人镜只差“第二个人没出脸”（背对 / 出画），换 seed 基本救不回 → 重出 1 次后停，标待人工看
        def only_missing(a):
            q = a["qc"]
            ids = q.get("ids") or {}
            miss = [k for k, v in ids.items() if v is None]
            rest_ok = all(v.get("ok") for v in ids.values() if isinstance(v, dict))
            return j["kind"] == "frame" and len(j.get("on_screen", [])) > 1 and miss and rest_ok                 and q.get("frame_ok") and q.get("text_ok")
        if not passed and scored and retries >= 1 and all(only_missing(a) for a in scored[-2:]):
            retries = j.get("max_retry", MAX_RETRY)
            j["review_note"] = "第二人未出脸（可能背对 / 出画），待人工看"
        if not passed and retries < j.get("max_retry", MAX_RETRY):
            base = j["attempts"][0]["seed"]
            seed = base + 1000 * (retries + 1) + 7
            variant = "alanref" if (j["kind"] == "sheet" and j["char"] == "ch_a_lan" and not j["look"].endswith("A")
                                    and ALAN_FACE.exists()) else ""
            self.add_attempt(j["key"], seed, variant, prio=5)
            j["attempts"][-1]["retry"] = retries + 1
            j["status"] = "retry"
            log("retry", j["key"], "第", retries + 1, "次", seed, variant)
            return
        pool = passed or scored
        if not pool:
            j["status"] = "failed"
            return
        best = max(pool, key=lambda a: a["qc"]["score"])
        j["chosen"], j["status"] = best["id"], ("pass" if passed else "best_effort")
        if not passed and j["kind"] == "frame":
            try:
                self.reframe(j, best)
            except Exception as e:  # noqa: BLE001
                log("reframe_err", j["key"], repr(e)[:120])
        j["tentative"] = True
        log("CHOSEN", j["key"], best.get("file"), j["status"])
        if j["kind"] == "sheet" and j["look"] == "ch_a_lan_lookA":
            self.make_alan_ref(best)
        self.save()
        self.milestones()

    def reframe(self, j, a):
        """K-REN-123 兜底：脸部特写出成了更远的景别 → 以主角色脸为中心按 9:16 裁切重构图（脸高约 0.33），放大回 768×1344。
        只作为另一张候选（标“裁切重构图”），不替换暂定；裁切框高 < 560 px（放大 >2.4 倍）时按 560 裁（脸会小一些）。"""
        q = a.get("qc") or {}
        fj = frame_job(j["shot"]) or {}
        if SIZE_IDX.get(j["size"], 9) > 1 or (fj.get("framing_subject") or "face") != "face" or q.get("size_delta", 0) <= 0:
            return
        faces = (a.get("qc_raw") or {}).get("faces") or []
        if not faces or not a.get("file") or not (ROOT / a["file"]).exists():
            return
        f = faces[0]
        x1, y1, x2, y2 = f["bbox"]
        im = Image.open(ROOT / a["file"]).convert("RGB")
        ch = max((y2 - y1) / 0.33, 560)
        if ch >= im.height * 0.95:
            return
        cw = ch * im.width / im.height
        cx, cy = (x1 + x2) / 2, y1 + (y2 - y1) * 0.55
        left = min(max(0, cx - cw / 2), im.width - cw)
        top = min(max(0, cy - ch * 0.42), im.height - ch)
        out = im.crop((int(left), int(top), int(left + cw), int(top + ch))).resize(im.size, Image.LANCZOS)
        dst = ROOT / a["file"].replace(".png", "_reframe.png")
        out.save(dst)
        j["reframe"] = {"file": str(dst.relative_to(ROOT)).replace(chr(92), "/"), "from": a["id"],
                        "face_h_after": round((y2 - y1) / ch, 3), "upscale": round(im.height / ch, 2)}
        try:
            thumb(j["reframe"]["file"])
        except Exception:  # noqa: BLE001
            pass
        log("REFRAME", j["key"], j["reframe"]["file"], j["reframe"]["upscale"])

    def make_alan_ref(self, a):
        """阿岚 A 暂定 → 裁左栏特写脸（同 identity_refs 的裁法：上扩 0.75×脸高、下到 1.0×脸高、宽=高×1.05）作阿岚身份参考。"""
        if ALAN_FACE.exists():                       # 已登记的身份脸不覆盖（一个角色只有一张身份脸；换脸走资产中心“设为当前身份脸”）
            log("ALAN_REF", "已有身份脸，不重裁", ALAN_FACE.relative_to(ROOT))
            return
        q = a["qc_raw"]
        f = q["faces"][0]
        x1, y1, x2, y2 = f["bbox"]
        im = Image.open(ROOT / a["file"]).convert("RGB")
        fh = y2 - y1
        top, bot = max(0, y1 - 0.75 * fh), min(im.height, y2 + 1.0 * fh)
        w = (bot - top) * 1.05
        cx = (x1 + x2) / 2
        crop = im.crop((int(max(0, cx - w / 2)), int(top), int(min(im.width, cx + w / 2)), int(bot)))
        ALAN_FACE.parent.mkdir(parents=True, exist_ok=True)
        crop.save(ALAN_FACE)
        self.st["alan_emb"] = f["emb"]
        self.st["alan_ref_from"] = a["file"]
        log("ALAN_REF", a["file"], "→", ALAN_FACE.relative_to(ROOT))
        try:                                         # PROMPT：由 image_jobs.py 把阿岚参考 + 说明补进首帧作业
            r = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "tools/pipeline/image_jobs.py",
                                "data/pipeline/runs/series10_v1"], cwd=ROOT, capture_output=True, text=True, timeout=600,
                               encoding="utf-8", errors="replace")
            log("image_jobs", r.returncode, (r.stdout + r.stderr).strip().replace("\n", " | ")[-300:])
        except Exception as e:  # noqa: BLE001
            log("ERROR image_jobs", str(e)[:200])
        for jj in self.st["jobs"].values():          # 把等着的阿岚 B/C 判掉
            if jj["kind"] == "sheet" and jj["char"] == "ch_a_lan" and jj["key"] != "sheet:ch_a_lan_lookA" \
                    and jj["status"] in ("open", "retry"):
                for x in jj["attempts"]:             # 之前按自洽度判的作废，改按与 A 的余弦重判
                    x.pop("qc", None)
                self.after_attempt(jj)

    # ---- 里程碑 / 页面
    def counts(self):
        sh = [j for j in self.st["jobs"].values() if j["kind"] == "sheet"]
        fr = [j for j in self.st["jobs"].values() if j["kind"] == "frame"]
        fin = lambda js: [j for j in js if j["status"] in ("pass", "best_effort", "failed")]  # noqa: E731
        return sh, fin(sh), fr, fin(fr)

    def stats(self):
        sh, shf, fr, frf = self.counts()
        att = [a for j in self.st["jobs"].values() for a in j["attempts"] if a.get("qc")]
        first = [j["attempts"][0] for j in self.st["jobs"].values() if j["attempts"] and j["attempts"][0].get("qc")]
        util = {}
        for ln in self.lanes.values():
            if ln.enabled_at:
                util[ln.name] = round(ln.busy_s / max(1, time.time() - ln.enabled_at), 2)
        rs = [a["render_s"] for j in self.st["jobs"].values() for a in j["attempts"] if a.get("render_s")]
        return {"sheets": f"{len(shf)}/{len(sh)}", "frames": f"{len(frf)}/{len(fr)}", "renders": len(att),
                "first_pass": round(sum(a["qc"]["ok"] for a in first) / max(1, len(first)), 2),
                "final_pass": round(sum(j["status"] == "pass" for j in self.st["jobs"].values()) /
                                    max(1, len([j for j in self.st["jobs"].values() if j.get("chosen")])), 2),
                "lane_util": util, "avg_render_s": round(sum(rs) / max(1, len(rs)), 1)}

    def milestones(self):
        ms = self.st["milestones"]
        sh, shf, fr, frf = self.counts()
        total_frames = len(frame_jobs()) or 80
        if sh and len(shf) == len(sh) and "sheets" not in ms:
            ms["sheets"] = time.strftime("%F %T")
            write_page(self.st)
            log("MILESTONE sheets_done", json.dumps(self.stats(), ensure_ascii=False))
            open_page()
        for ep in sorted({j["ep"] for j in fr}):
            e = [j for j in fr if j["ep"] == ep]
            tot = len([x for x in frame_jobs() if x["ep"] == ep])
            if len([j for j in e if j in frf]) == tot and f"ep{ep}" not in ms:
                ms[f"ep{ep}"] = time.strftime("%F %T")
                write_page(self.st)
                log("MILESTONE ep_done", ep, json.dumps(self.stats(), ensure_ascii=False))
        if len(frf) >= total_frames / 2 and "frames50" not in ms:
            ms["frames50"] = time.strftime("%F %T")
            log("MILESTONE frames_50", json.dumps(self.stats(), ensure_ascii=False))
        if len(frf) >= total_frames and "frames100" not in ms:
            ms["frames100"] = time.strftime("%F %T")
            write_page(self.st)
            log("MILESTONE frames_100", json.dumps(self.stats(), ensure_ascii=False))
            open_page()

    def run(self):
        last_plan = 0
        last_page = time.time()
        with self.lk:
            self.plan()
        for ln in self.lanes.values():
            threading.Thread(target=self.lane_loop, args=(ln,), daemon=True, name=ln.name).start()
            threading.Thread(target=self.fetch_loop, args=(ln,), daemon=True, name=ln.name + "-fetch").start()
        while True:
            t = time.time()
            with self.lk:
                if t - last_plan > 30:
                    self.plan()
                    last_plan = t
                    # 之前丢掉的提交（断点）重新排队
                    for j in self.st["jobs"].values():
                        for a in j["attempts"]:
                            if a.get("state") == "lost":
                                a["state"] = "queued"
                                self.todo.append({"key": j["key"], "aid": a["id"], "prio": 5, "n": len(self.todo)})
                self.pump_qc()
                snap = None
                if time.time() - last_page > 300:
                    snap, stats = copy.deepcopy(self.st), self.stats()   # 锁里只拷一份，锁外写页面（INFRA d）
                    self.save()
                    last_page = time.time()
            if snap is not None:
                try:
                    write_page(snap, stats)
                except Exception as e:  # noqa: BLE001
                    log("page_err", repr(e)[:200])
            ctrl = jload(CTRL, {}) or {}
            if ctrl.get("stop"):
                self.stopping = True
                with self.lk:
                    self.save()
                log("stop requested")
                break
            time.sleep(3)


# ---------------------------------------------------------------- 审阅页


def rel(p):
    return os.path.relpath(ROOT / p, PAGE.parent).replace("\\", "/")


def thumb(p, w=360):
    src = ROOT / p
    t = IMG / "_thumbs" / (Path(p).stem + ".jpg")
    if not src.exists():                         # 原图留在服务器（第二轮），只同步了缩略图
        return rel(str(t.relative_to(ROOT)))
    if not t.exists() or t.stat().st_mtime < src.stat().st_mtime:
        t.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(src).convert("RGB")
        im.thumbnail((w * 2 if im.width > im.height else w, 2000))
        im.save(t, "JPEG", quality=85)
    return rel(str(t.relative_to(ROOT)))


def merged_state():
    """笔记本审阅页：第一轮 state.json + 服务器第二轮 state_gpu33.json / state_gpu36.json（sync_thumbs 拉回）。
    同一镜两轮的候选都保留（第二轮的 id 加 r2: 前缀）；暂定取：第二轮通过 > 第一轮通过 > 两轮里分数高的。"""
    st = copy.deepcopy(jload(IMG / "state.json", {}) or {"jobs": {}})
    for h in ("gpu33", "gpu36"):
        s2 = jload(IMG / f"state_{h}.json", None)
        if not s2:
            continue
        for k, j2 in s2.get("jobs", {}).items():
            for a in j2["attempts"]:
                a["id"] = "r2:" + a["id"]
                a["round"] = 2
                a["host"] = h
            if k not in st["jobs"]:
                j2["chosen"] = "r2:" + j2["chosen"] if j2.get("chosen") else None
                st["jobs"][k] = j2
                continue
            j1 = st["jobs"][k]
            c1 = next((a for a in j1["attempts"] if a["id"] == j1.get("chosen")), None)
            c2 = next((a for a in j2["attempts"] if a["id"] == "r2:" + str(j2.get("chosen"))), None)
            j1["attempts"] = j1["attempts"] + j2["attempts"]
            j1["round2"] = {"status": j2.get("status"), "host": h, "review_note": j2.get("review_note")}
            if j2.get("reframe"):
                j1["reframe"] = j2["reframe"]
            if c2 is None:
                continue
            s1 = (c1 or {}).get("qc", {}).get("score", -9)
            s2_ = c2.get("qc", {}).get("score", -9)
            if j2.get("status") == "pass" or (j1.get("status") != "pass" and s2_ >= s1):
                j1["chosen"], j1["status"] = c2["id"], j2.get("status")
                j1["review_note"] = j2.get("review_note")
    return st


def write_page(st, stats=None):
    import html
    E = html.escape
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    jobs = st["jobs"]
    css = """:root{--bg:#f6f5f2;--fg:#1d1d1b;--mut:#6b6a65;--card:#fff;--line:#e2e0da;--ok:#1f7a3d;--bad:#b3261e;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--mut:#a09e97;--card:#21201e;--line:#34332f;--ok:#5fc27e;--bad:#f2867d;--warn:#e0b04a}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif;margin:0;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:16px 0 6px}.mut{color:var(--mut)}.grid{display:flex;flex-wrap:wrap;gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px;width:220px}
.card.wide{width:440px}.card img{width:100%;border-radius:4px;display:block}.card.best{outline:3px solid var(--ok)}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.tag{font-size:12px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}"""
    out = [f"<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>十日图片审阅</title><style>{css}</style></head><body>",
           "<h1>《漆皮之下·十日》图片审阅（series10_v1）</h1>",
           f"<div class=mut>更新 {time.strftime('%F %T')}。绿框 = 系统自动选的<b>暂定</b>（项目方可换）。身份余弦：与本人参考 ≥0.50 为同人；"
           f"坏手/多肢暂无自动检测，标“待人工看”。</div>"]
    if stats:
        out.append(f"<div class=mut>设定图 {stats['sheets']}｜首帧 {stats['frames']}｜首次通过率 {stats['first_pass']:.0%}｜"
                   f"最终通过率 {stats['final_pass']:.0%}｜平均每张 {stats['avg_render_s']} s</div>")
    out.append("<h2>设定图（每个造型的候选与暂定最佳）</h2>")
    for ch in ("ch_a_lan", "lin_wan", "gu_chen", "chen_yu"):
        looks = sorted((j for j in jobs.values() if j["kind"] == "sheet" and j["char"] == ch), key=lambda j: j["look"])
        if not looks:
            continue
        out.append(f"<h3>{ID2NAME[ch]}</h3>")
        for j in looks:
            out.append(f"<div class=mut>造型 {E(j['look'][-1])}：{E(j.get('outfit', ''))}｜{E(j.get('use', ''))}｜"
                       f"状态 {E(j['status'])}</div><div class=row>")
            for a in j["attempts"]:
                if not a.get("file"):
                    continue
                q = a.get("qc") or {}
                best = j.get("chosen") == a["id"]
                sc = q.get("self_sim", q.get("self_consistency"))
                lab = ("本人" if "self_sim" in q else "自洽") + (f" {sc:.2f}" if sc is not None else " —")
                mo = max((q.get("others") or {}).values() or [0])
                verdict = "<span class=ok>通过</span>" if q.get("ok") else (f"<span class=bad>不过 {E(q.get('why', ''))}</span>" if q else "待打分")
                out.append(f"<div class='card wide{' best' if best else ''}'><a href='{rel(a['file'])}'><img loading=lazy src='{thumb(a['file'])}'></a>"
                           f"<div class=tag>seed {a['seed']}{'（带阿岚A脸）' if a['variant'] == 'alanref' else ''}｜{lab}｜他人最高 {mo:.2f}｜{verdict}"
                           f"{'｜<b class=ok>暂定</b>' if best else ''}</div></div>")
            out.append("</div>")
    out.append("<h2>首帧（按集）</h2>")
    fjs = {f["shot"]: f for f in frame_jobs()}
    for ep in range(1, 11):
        shots = [f for f in frame_jobs() if f["ep"] == ep]
        done = [j for j in jobs.values() if j["kind"] == "frame" and j["ep"] == ep]
        out.append(f"<h3>第 {ep} 集 <span class=mut>（{len([j for j in done if j.get('chosen')])}/{len(shots)}）</span></h3><div class=grid>")
        for f in shots:
            j = jobs.get("frame:" + f["shot"])
            if not j or not j.get("chosen"):
                out.append(f"<div class=card><div class=mut>{E(f['shot'])}｜{E(f['size'])}｜{E('、'.join(f.get('on_screen', [])))}"
                           f"<br>{'出图中' if j else '未放行（等剧本定稿）'}</div></div>")
                continue
            a = next(x for x in j["attempts"] if x["id"] == j["chosen"])
            q = a.get("qc", {})
            ids = []
            for c, v in (q.get("ids") or {}).items():
                if isinstance(v, dict):
                    ids.append(f"<span class={'ok' if v['ok'] else 'bad'}>{ID2NAME[c]} {v['sim']:.2f}</span>")
                else:
                    ids.append(f"{ID2NAME.get(c, c)} {E(str(v) if v else '未检出')}")
            st_ = "<span class=ok>通过</span>" if j["status"] == "pass" else f"<span class=warn>尽力（{E(q.get('why', ''))}）</span>"
            n_try = len([x for x in j["attempts"] if x.get("file")])
            rnd = "第二轮" if a.get("round") == 2 else "第一轮"
            hands = q.get("hands") or "待人工看"
            rf = j.get("reframe")
            rf_html = (f"<br><a href='{rel(rf['file'])}'><img loading=lazy style='width:40%' src='{thumb(rf['file'])}'></a>"
                       f" 裁切重构图候选（放大 {rf['upscale']}×）") if rf else ""
            out.append(f"<div class='card best'><a href='{rel(a['file'])}'><img loading=lazy src='{thumb(a['file'])}'></a>"
                       f"<div class=tag><b>{E(f['shot'])}</b>｜要 {E(f['size'])}｜得 {E(q.get('framing', '—'))}<br>"
                       f"在画：{E('、'.join(f.get('on_screen', [])) or '无')}<br>身份：{' '.join(ids) or '—'}<br>"
                       f"{st_}｜<b>暂定</b>｜{rnd}｜共 {n_try} 张｜手：{E(hands)}{'｜有字' if q.get('text') else ''}"
                       f"{'｜' + E(j['review_note']) if j.get('review_note') else ''}{rf_html}</div></div>")
        out.append("</div>")
    out.append("</body></html>")
    PAGE.write_text("\n".join(out), encoding="utf-8")


def findings(st):
    """把 state.json 归纳成规则证据（knowledge/rules/render_imggen_s10.yaml 引用）。"""
    import collections
    jobs = st["jobs"].values()
    out = {"generated": time.strftime("%F %T"), "sheets": {}, "frames": {}}
    for j in jobs:
        if j["kind"] != "sheet":
            continue
        out["sheets"][j["look"]] = {"status": j["status"], "chosen": j.get("chosen"), "attempts": [
            {"seed": a["seed"], "variant": a["variant"], "ok": (a.get("qc") or {}).get("ok"),
             "self": (a.get("qc") or {}).get("self_sim", (a.get("qc") or {}).get("self_consistency")),
             "others": (a.get("qc") or {}).get("others")} for a in j["attempts"] if a.get("qc")]}
    fr = [j for j in jobs if j["kind"] == "frame"]
    first_fail = collections.Counter()
    rescued = collections.Counter()
    tried = collections.Counter()
    table = []
    for j in fr:
        sc = [a for a in j["attempts"] if a.get("qc")]
        if not sc:
            continue
        q0 = sc[0]["qc"]
        reasons = [] if q0["ok"] else ([w[:2] for w in q0.get("why", "").split("；") if w] or ["?"])
        for r in reasons:
            first_fail[r] += 1
            tried[r] += 1
            if j["status"] == "pass":
                rescued[r] += 1
        for a in sc:
            q = a["qc"]
            table.append({"shot": j["shot"], "seed": a["seed"], "size_want": j["size"], "face_h": q.get("face_h"),
                          "size_got": q.get("size_got"), "frame_ok": q.get("frame_ok"), "id_ok": q.get("id_ok"),
                          "ids": {k: (v.get("sim") if isinstance(v, dict) else v) for k, v in (q.get("ids") or {}).items()},
                          "on_screen": j["on_screen"], "ok": q["ok"]})
    n_first = len([j for j in fr if any(a.get("qc") for a in j["attempts"])])
    out["frames"] = {
        "jobs_scored": n_first,
        "first_pass": sum(1 for j in fr if j["attempts"] and (j["attempts"][0].get("qc") or {}).get("ok")),
        "final_pass": sum(1 for j in fr if j["status"] == "pass"),
        "best_effort": sum(1 for j in fr if j["status"] == "best_effort"),
        "renders": sum(1 for j in fr for a in j["attempts"] if a.get("qc")),
        "first_fail_reasons": dict(first_fail), "rescued_by_reseed": {k: f"{rescued[k]}/{tried[k]}" for k in tried},
        "table": table}
    jsave(IMG / "findings.json", out)
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if "--lanes" in sys.argv:
        configure(sys.argv[sys.argv.index("--lanes") + 1])
    if cmd == "findings":
        o = findings(jload(STATE))
        print(json.dumps({k: v for k, v in o["frames"].items() if k != "table"}, ensure_ascii=False))
        return
    if cmd == "page":
        st = merged_state()
        r = Runner.__new__(Runner)
        r.st, r.lanes = st, {}
        write_page(st, r.stats())
        print(PAGE)
        return
    r = Runner()
    r.run()


if __name__ == "__main__":
    main()






