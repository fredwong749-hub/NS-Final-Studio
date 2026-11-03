"""VIDEO10（2026-10-31）：series10 视频作业编译（MERGE-VID-O 11-03 起按剧：--run <剧> / NS_RUN / 当前剧，run_ctx.resolve；L-137）——Shot Spec → 配方引擎 → ComfyUI 图（笔记本端，纯编译，不提交）。

提示词 / 图一律由系统编译器生成（K-PRM-301，不手拼）：
  P4_epNN.md ─(tools/pipeline/p4_adapter.check_p4：拼现行全局头 + 真实导入器 + spec_import)→ Shot Spec v2
  ─(services/recipes ns_recipes.compiler.compile_shot：官方 ref-en 六段 / base-en、σ 表、两段式、PDD)→ RenderPlan.graph

每镜预编译一组“变体”，服务器端编排器（vidgen.py）按规则阶梯挑下一个变体，不在服务器上再编译：
  露脸镜（≥1 张在画露脸）：v1 = 默认配方第 1 次；s2/s3/s4 = 默认配方第 2–4 次（换 seed；第 2 次起插官方锚点句）；
      b24 = 纯 Ref2VA 24 步（two_person_ref2va，换配方）；alt = 默认配方 + 换参考（设定图造型版里裁出的脸）；
      i2v = 只给首帧 PDD 两段式（保构图）
  无人露脸镜：v1/s2/s3/s4 = i2va_pdd2（只给首帧）；b24 = establishing（基模 24 只给首帧）
默认配方由 S10V-1 对照决定（config：data/pipeline/runs/series10_v1/video/recipe_choice.json，validate.py 写）。

输出 data/pipeline/runs/series10_v1/video/：jobs.json（全部变体）、specs/<shot>.spec.json、prompts/<shot>.<variant>.txt
    .venv/Scripts/python.exe tools/series10_video/build_jobs.py            # 全量 80 镜
    .venv/Scripts/python.exe tools/series10_video/build_jobs.py --validate  # 只编 S10V-1 对照作业 → validate_jobs.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("tools/pipeline", "services/recipes", "packages/schema", "services/render_router", "services/agent",
          "packages/qc"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import chainlib  # noqa: E402,F401  （补 sys.path）
from p4_adapter import check_p4  # noqa: E402
from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import registry as R  # noqa: E402

import run_ctx as RC  # noqa: E402

# MERGE-VID-O（ISS-1103-024206-3737，L-137）：剧不再写死 series10_v1——set_run(<剧>) 换全部路径；导入时按 run_ctx.resolve() 取当前剧
RUN_ID: str | None = None
RUN = VID = IMG_STATE = CHOICE = FRAMES_OK = None   # set_run 填
RENDERS: Path | None = None   # 相对 ROOT：V1 = data/renders，其它剧 = data/renders/<剧>
NAME2ID_V1 = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}   # 只给 legacy 剧（V1）用
NAME2ID = dict(NAME2ID_V1)
# 换参考（身份低时）：从本角色 series10 造型设定图（项目方流程出的四栏图）里裁出的正脸，只含头脸
ALT_SHEET = {"lin_wan": "images/sheets/lin_wan/lin_wan_lookA_s202.png", "gu_chen": "images/sheets/gu_chen/gu_chen_lookA_s101.png",
             "chen_yu": "images/sheets/chen_yu/chen_yu_lookA_s202.png", "ch_a_lan": "images/sheets/ch_a_lan/ch_a_lan_lookA_s1108.png"}
# 主机按整集分（成片在出片那台机器上合成，片段不跨机）；ep09 有 328 帧长镜头 → gpu36（长镜头道 gpu36:2）
HOST_OF_EP_V1 = {1: "gpu33", 2: "gpu36", 3: "gpu33", 4: "gpu36", 5: "gpu33", 6: "gpu36", 7: "gpu33", 8: "gpu36",
                 9: "gpu36", 10: "gpu33"}
HOST_OF_EP = dict(HOST_OF_EP_V1)


def set_run(run: str) -> str:
    """切到这部剧的视频目录 / 渲染目录 / 人物表（失败关闭：run_ctx 校验登记表 + 视频政策 scope_runs）"""
    global RUN_ID, RUN, VID, IMG_STATE, CHOICE, FRAMES_OK, RENDERS, NAME2ID, HOST_OF_EP
    RUN_ID = run
    RUN = RC.run_dir(run)
    VID = RUN / "video"
    IMG_STATE = RUN / "images/state.json"
    CHOICE = VID / "recipe_choice.json"
    FRAMES_OK = VID / "frames_ok.json"
    RENDERS = Path(RC.renders_dir(run)).relative_to(RC.ROOT)   # 相对仓库根（测试换 ROOT 时跟着走）
    legacy = RC.is_legacy(run)
    NAME2ID = dict(NAME2ID_V1) if legacy else None      # 非 V1：按本剧人物表（name_ids）取，不用 V1 的人名表
    HOST_OF_EP = dict(HOST_OF_EP_V1) if legacy else {}  # 非 V1：只认 video/hosts.json（night 由 partition 生成），没有就不派
    global VIDEO_HOLD     # 按镜 hold 按剧分开（镜号 ep01-S8 跨剧同名，V1 的 hold 不许挡 V2）
    VIDEO_HOLD = ROOT / "data" / "autopilot" / ("video_hold.json" if legacy else f"runs/{run}/video_hold.json")
    return run


def name_ids() -> dict:
    """人名 → char_id：V1 = 写死的四人；其它剧 = 本剧资产清单 / P1 人物表（ns_agent.cast_table，失败关闭不退回 V1）"""
    if NAME2ID is not None:
        return NAME2ID
    from ns_agent import cast_table as CT
    sc = CT.speaker_cast(RUN_ID) or {}
    return {**CT.char_ids(RUN_ID), **(sc.get("names") or {})}
VALIDATE = {"shots": {"ep01-S5": "单人近景", "ep01-S6": "双人对白", "ep10-S5": "走动全身"},
            "seeds": [20261101, 20261102],
            "arms": {"pdd": "ref2va_pdd2", "b24": "two_person_ref2va"}}  # i2v 组撤掉：项目方判首帧不合格（10-31 夜），对照只走不依赖首帧的 Ref2VA
KITCHEN = {"sampling.attention": "comfy kitchen attention"}
# K-REN-302：“动作不足”的阶梯第一步——系统最低动作提示（只写物理，不写剧情）
MIN_MOTION_CUE = ("Throughout the shot every person keeps small continuous natural movement: visible breathing in the chest and "
                  "shoulders, slight weight shifts and blinks, and each described action is performed fully and clearly, never frozen.")
import re  # noqa: E402
BAD_LORA_RE = re.compile(r"lin_?wan|lnwan|_qi_|identity", re.I)
BAD_STYLE_RE = re.compile(r"creamy|f/1\.\d|oily|greasy|glossy skin|richly saturated|vivid saturated|奶油|油光|浓郁饱和", re.I)


VIDEO_HOLD = ROOT / "data" / "autopilot" / "video_hold.json"   # 按镜 hold（DEBUG-RSI，总调度 11-02 14:2x，fb-0001 ep02-S3 等写作补丁）


def video_holds(now: float | None = None) -> dict:
    """data/autopilot/video_hold.json {"active": true, "items": {sid: {reason_kind, reason, expires_at, by}}} → 当前生效的 {sid: 原因}。
    到期（expires_at，+09:00 本地时间串）自动失效；文件没有 / active=false → {}；文件坏 → raise（失败关闭：不能静默放行要 hold 的镜）"""
    if not VIDEO_HOLD.exists():
        return {}
    d = json.loads(VIDEO_HOLD.read_text(encoding="utf-8"))
    if not d.get("active", True):
        return {}
    t = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now or time.time()))
    return {sid: f"{v.get('reason_kind') or 'hold'}：{v.get('reason') or ''}"[:200]
            for sid, v in (d.get("items") or {}).items() if str(v.get("expires_at") or "9999")[:19] > t}


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def load_specs(eps=None, source: str | None = None) -> dict:
    """source = "import"（默认：本剧导入稿 runs.script_path(<剧>)；V1 = data/import/script_v2.json，V2 = data/import/runs/<剧>/script_v2.json）
    或 "p4"（runs 目录的 P4 稿经 p4_adapter.check_p4 生成；V1 在 epNN/ 下，其它剧在剧目录根）。eps 不给 = 导入稿里有的全部集"""
    source = source or ("p4" if "--from-p4" in sys.argv else "import")
    out = {}
    if source == "import":
        from ns_recipes.spec_import import specs_from_import
        from ns_schema.script import ScriptImport
        si = ScriptImport.model_validate_json(RC.script_path(RUN_ID).read_text(encoding="utf-8"))
        have = [e.number for e in si.episodes]
        for n in (eps if eps is not None else have):
            if n not in have:
                continue
            for s in specs_from_import(si, n):
                out[s.id] = s
        return out
    for n in (eps if eps is not None else range(1, 11)):
        f = (RUN / f"ep{n:02d}" / f"P4_ep{n:02d}.md") if RC.is_legacy(RUN_ID) else (RUN / f"P4_ep{n:02d}.md")
        if eps is None and not f.is_file():
            continue
        md = f.read_text(encoding="utf-8")
        rep, _shots, specs, _raw = check_p4(md, n)
        for s in specs:
            out[s.id] = s
    return out


def _vq():
    try:
        sp = str(ROOT / "services" / "agent")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from ns_agent.vqa import contract as VQ
        return VQ
    except Exception:  # noqa: BLE001
        return None


def _q9_ok(pf: dict) -> bool:
    """看图闸门先于视频（ISS-1103-024206-4b21，gate.video_requires_q9=true）：看图模块载不进来 = 判不过（失败关闭，原来是放行）"""
    VQ = _vq()
    return False if VQ is None else VQ.q9_passed(pf)


def _q9_ok_file(file: str) -> bool:
    """frames_ok.json（ASSETMASTER 通知）的首帧没有 postflight：按图片查本地看图判定（data/vqa/index.json）"""
    VQ = _vq()
    if VQ is None:
        return False          # 失败关闭（同 _q9_ok）
    if not VQ.enforced():
        return True
    st, _d, _ev = VQ.q9(VQ.cached_for(ROOT / file))
    return VQ.q9_passed({"items": [{"id": "Q9", "status": st}]})


def passed_frames() -> dict:
    """已过契约（GEN_CONTRACT §2 postflight）并设为当前的首帧 → {镜: {file, postflight}}。
    来源：① data/renders/epNN/SN/takes.json 的 active.image，且该版本带 postflight.ok（或 contract.ok）；
          ② video/frames_ok.json（ASSETMASTER 通知“契约通过并设为当前”的镜，notify.py 写入，记来源原话）。
    旧 IMGGEN 首帧（项目方 10-31 夜判不合格）不再使用。"""
    out = {}
    rows = _accept_rows()
    ANOMALY_SKIPPED.clear()
    for tj in sorted((ROOT / RENDERS).glob("ep*/S*/takes.json")):      # 本剧渲染根（V1 = data/renders，V2 = data/renders/<剧>）
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n = (d.get("active") or {}).get("image")
        t = next((t for t in d.get("takes") or [] if t.get("stage") == "image" and t.get("n") == n), None)
        pf = (t or {}).get("postflight") or (t or {}).get("contract") or {}
        # 总调度亲审打回（PRODUCER 写 take.master_reject）= 视同撤销，不算过契约（K-OPS-304）
        # VQAGATE（项目方 11-01：“image 做出来后用本地图像模型检测……再跑视频”）：只给图片闸门（Q9）通过的首帧派视频；
        # 没有看图结果 = 未通过（config/vqa.json gate.video_requires_q9；enforce 关掉时 q9_passed 恒真）
        sid_k = f"{tj.parent.parent.name}-{tj.parent.name}"
        why_block = anomaly_block(sid_k, t["file"], pf, rows) if t and t.get("file") and pf.get("ok") else None
        if why_block:
            ANOMALY_SKIPPED[sid_k] = f"v{n} 首帧 anomaly 判出：{why_block}，不进视频（等重出）"
            continue
        if ACCEPT_REQUIRED and t and t.get("file") and pf.get("ok"):
            acc = accept_status(sid_k, t["file"], pf, rows)
            if acc != "pass":
                ANOMALY_SKIPPED[sid_k] = (f"v{n} 首帧还没跑出图后验收，跑完通过再进视频" if acc is None
                                          else f"v{n} 首帧出图后验收 {acc}，不进视频")
                continue
        if t and t.get("file") and pf.get("ok") and not t.get("master_reject") and _q9_ok(pf) and (ROOT / "data" / t["file"]).exists():
            out[f"{tj.parent.parent.name}-{tj.parent.name}"] = {"file": "data/" + t["file"], "postflight": pf,
                                                               "status": "pass", "take": n, "created_at": str(t.get("created_at") or "")}
    ok = json.loads(FRAMES_OK.read_text(encoding="utf-8")) if FRAMES_OK.exists() else {}
    for sid, v in ok.items():
        if not sid.startswith("_") and v.get("file") and (ROOT / v["file"]).exists() and _q9_ok_file(v["file"]):
            if sid in out:
                continue
            if ACCEPT_REQUIRED and accept_status(sid, v["file"], {}, rows) != "pass":   # 通知来源同样要过第 8 步验收（不留旁路）
                ANOMALY_SKIPPED.setdefault(sid, "frames_ok 通知的首帧还没通过出图后验收，跑完通过再进视频")
                continue
            out.setdefault(sid, {"file": v["file"], "postflight": {"ok": True, "source": v.get("by")}, "status": "pass"})
    # 上传瘦身（K-OPS-302：笔记本上行很慢）：首帧转 JPEG q95 放 video/inputs/<镜>.jpg，原图路径记在 src
    from PIL import Image
    d = VID / "inputs"
    d.mkdir(parents=True, exist_ok=True)
    for sid, v in list(out.items()):
        src = ROOT / v["file"]
        dst = d / f"{sid}_{hashlib.sha256(src.read_bytes()).hexdigest()[:8]}.jpg"
        if not dst.exists():
            # K-OPS-306：首帧 PNG 还在写 / 拷了一半（离线 11-01 10:44 LOOP_ERR 'image file is truncated' 卡住整轮）
            # → 这一镜本轮不算就绪、下一轮再读；不放宽解码（LOAD_TRUNCATED_IMAGES 会把半张图当首帧送去出片）
            try:
                with Image.open(src) as im:
                    im.load()
                    im.convert("RGB").save(dst, "JPEG", quality=95)
            except (OSError, ValueError, SyntaxError) as e:
                dst.unlink(missing_ok=True)
                print(f"[passed_frames] 跳过 {sid}：首帧读不全（{v['file']}：{e}），下一轮重试", file=sys.stderr)
                out.pop(sid)
                continue
        v["src"] = v["file"]
        v["file"] = rel(dst)
    return out


HEAD_DEFECTS = ("duplicate_person", "extra_head")
ANOMALY_SKIPPED: dict = {}   # 本轮没进视频的镜 → 原因（等验收 / 验收没过 / 重复人头；写进 jobs 的 anomaly_skipped，看板可见）
# D-VQA-01（项目方 11-01“图片过闸门后才进视频”；总调度 11-02 17:4x 定收紧）：首帧必须有第 8 步出图后验收结果且通过才进视频；
# 按镜生效（某镜验收一通过，passed_frames 变 → night 的就绪签名变 → 重编作业放行这一镜），不用等全部跑完
ACCEPT_REQUIRED = True


def _accept_rows() -> dict:
    """VQAGATE 出图后验收批量结果 data/vqa/accept/<集>.json → {(镜, 文件名): count 项}"""
    out = {}
    for f in sorted((ROOT / "data/vqa/accept").glob("*.json")):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 验收结果文件坏 = 这批没有判定，不据此拦；闸门只拦“判出”的（总调度 17:3x 口径）
            continue
        for r in rows if isinstance(rows, list) else []:
            sid = str(r.get("key") or "").split("|")[0]
            out[(sid, Path(str(r.get("file") or "").replace("\\", "/")).name)] = r
    return out


def accept_status(sid: str, file: str, pf: dict, rows: dict) -> str | None:
    """这一版首帧的第 8 步验收结论：postflight Q10 优先，其次验收批量结果（同镜同文件名）→ pass | fail | untested | None（没跑过）"""
    q10 = next((i for i in pf.get("items") or [] if i.get("id") == "Q10"), None)
    if q10:
        return q10.get("status")
    r = rows.get((sid, Path(file).name))
    return (r or {}).get("ok")


def anomaly_block(sid: str, file: str, pf: dict, rows: dict) -> str | None:
    """总调度 11-02 17:3x：anomaly 判出重复人 / 多余人头的首帧不许进视频（ep04-S10 v6 就是这样进了视频）。
    依据：postflight Q10（出图后验收）人数项，或验收批量结果里同一版首帧的 count.defects。没判过的不拦"""
    q10 = next((i for i in pf.get("items") or [] if i.get("id") == "Q10"), None)
    cnt = ((q10 or {}).get("evidence") or {}).get("count") or (rows.get((sid, Path(file).name)) or {}).get("count") or {}
    hit = [d for d in cnt.get("defects") or [] if any(str(d).startswith(c) for c in HEAD_DEFECTS)]
    return "；".join(hit)[:300] if hit else None


LASTS_OF: dict = {}   # build_all 开头按 passed_lasts() 填；compile_variant 映射 @last_frame 用


def passed_lasts() -> dict:
    """视频尾帧关键帧（配方 last_frame_mode=use 且镜头 spec 有 last 关键帧时送）→ {镜: 文件}。
    项目方定稿锁 locked.last 优先（定稿就是定稿），其次当前尾帧且过契约；文件不在就不算。
    L-124 ep01-S1（总调度 16:4x）：以前这里根本没有 @last_frame 的映射，S1 七个变体提交全报 KeyError '@last_frame'，一条片都没有"""
    out = {}
    for tj in sorted((ROOT / RENDERS).glob("ep*/S*/takes.json")):
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 读不到这一镜 = 没有尾帧，对应变体标 no_last_frame 不提交（失败关闭）
            continue
        n = (d.get("locked") or {}).get("last")
        locked = n is not None
        if not locked:
            n = (d.get("active") or {}).get("last")
        t = next((x for x in d.get("takes") or [] if x.get("stage") == "last" and x.get("n") == n), None)
        pf = (t or {}).get("postflight") or (t or {}).get("contract") or {}
        if t and t.get("file") and (locked or pf.get("ok")) and not t.get("master_reject") and (ROOT / "data" / t["file"]).exists():
            out[f"{tj.parent.parent.name}-{tj.parent.name}"] = {"file": "data/" + t["file"], "created_at": str(t.get("created_at") or "")}
    return out


def chosen_frames() -> dict:
    """IMGGEN 旧首帧（只给 S10V-1 对照的 i2v 组用过；正式出片用 passed_frames）"""
    st = json.loads(IMG_STATE.read_text(encoding="utf-8"))["jobs"]
    out = {}
    for k, v in st.items():
        if not k.startswith("frame:") or not v.get("chosen"):
            continue
        a = next((a for a in v["attempts"] if a["id"] == v["chosen"]), None)
        if a and a.get("file") and (ROOT / a["file"]).exists():
            out[v["shot"]] = {"file": a["file"], "status": v.get("status")}
    return out


def alt_crops() -> dict:
    """设定图左栏最大脸 → 头脸裁切（同 identity_refs manifest 的方法：上扩 0.75×脸高、下到 1.0×脸高、宽 = 高×1.05）"""
    import cv2
    from ns_qc import face as QF
    out = {}
    if not RC.is_legacy(RUN_ID):
        return out            # 换参考裁切只有 V1 的设定图（ALT_SHEET）；其它剧不退回 V1 的脸（L-126）
    d = VID / "refs_alt"
    d.mkdir(parents=True, exist_ok=True)
    m = None
    for cid, sheet in ALT_SHEET.items():
        dst = d / f"{cid}_face_alt.png"
        if dst.exists():
            out[cid] = rel(dst)
            continue
        if m is False:
            continue
        if m is None:
            # K-OPS-307：人脸模型只在要新裁时才加载；找不到模型（离线服务器副本 11-01 10:46 FaceModels(*None) TypeError
            # 让 build_jobs 整个失败、全部集派不出）→ 已有裁切照用，缺的这几张跳过并报出，不拖垮编译
            paths = QF.find_models(ROOT)
            if not paths:
                print(f"[alt_crops] 找不到人脸模型（ns_qc.face.find_models），跳过新裁 {cid} 等；已有裁切照用", file=sys.stderr)
                m = False
                continue
            m = QF.FaceModels(*paths, score=0.6)
        img = cv2.imread(str(RUN / sheet))
        if img is None:
            continue
        H, W = img.shape[:2]
        f = QF.largest(m.faces(img[:, : W // 3]))     # 四栏图左栏 = 正面
        if f is None:
            f = QF.largest(m.faces(img))
        if f is None:
            continue
        x, y, w, h = (int(v) for v in f[:4])
        top, bot = max(0, int(y - 0.75 * h)), min(H, int(y + 2.0 * h))
        cw = int((bot - top) * 1.05)
        cx = x + w // 2
        l, r = max(0, cx - cw // 2), min(W, cx + cw // 2)
        cv2.imwrite(str(dst), img[top:bot, l:r])
        out[cid] = rel(dst)
    return out


class RecipeChoiceMissing(RuntimeError):
    """本剧没有 recipe_choice.json，视频政策也给不出默认配方：失败关闭（不退回 L-088 之前的 i2va_pdd2）"""


def recipe_choice() -> dict:
    """本剧 video/recipe_choice.json；没有 → 按 video_policy.json pika_only.allowed 派生（L-137：V1 的 Pika Flex 默认原样用在 V2，
    与 state_snapshot.init_run 同一口径）；政策也没有 → RecipeChoiceMissing"""
    if CHOICE.exists():
        return json.loads(CHOICE.read_text(encoding="utf-8"))
    pol = (C.video_policy().get("pika_only") or {})
    allowed = (pol.get("allowed") or [None])[0] if pol.get("enabled") else None
    if not allowed or RUN_ID not in (C.video_policy().get("scope_runs") or []):
        raise RecipeChoiceMissing(f"{RUN_ID} 没有 {CHOICE} 且 video_policy.json 给不出默认配方（失败关闭）")
    return {"face_default": allowed, "ref_default": allowed, "noface_default": allowed, "decided": True,
            "rule": "K-REN-301 / L-088 / L-137（MERGE-VID-O：本剧没有 recipe_choice.json，按 config/pipeline/video_policy.json 派生）",
            "decided_by": "config 默认（video_policy.pika_only.allowed）", "derived": True}


def compile_variant(spec, reg, rid, attempt, variant, frames_of, *, seed=None, extra=None):
    ov = dict(KITCHEN)
    ov.update(extra or {})
    if seed is not None:
        ov["seed.value"] = int(seed)
    plan = C.compile_shot(spec, reg, attempt=attempt, recipe_id=rid, overrides=ov, allow_experimental={rid})
    if plan["status"] == "needs_writer":
        return {"status": "needs_writer", "reason": plan.get("reason")}
    # K-PRM-302：视频侧不挂会拉偏脸的身份 / 出图 LoRA；系统风格后缀不得带“奶油柔焦 / 浓郁饱和 / 油光”类词
    bad_lora = [n["inputs"].get("lora_name") for n in plan["graph"].values()
                if n["class_type"].startswith("LoraLoader") and BAD_LORA_RE.search(str(n["inputs"].get("lora_name")))]
    if bad_lora:
        return {"status": f"bad_lora:{bad_lora}"}
    sys_style = (reg.resolve(rid).get("prompt") or {}).get("style_lead", "")
    if BAD_STYLE_RE.search(sys_style):
        return {"status": f"bad_style_lead:{sys_style}"}
    inputs = {}
    ff = frames_of.get(spec.id)
    for n in plan["graph"].values():
        for v in (n.get("inputs") or {}).values():
            if not isinstance(v, str) or not v.startswith("@"):
                continue
            if v == "@first_frame":
                if not ff:
                    return {"status": "no_first_frame"}
                inputs[v] = ff["file"]
            elif v == "@last_frame":          # 配方送尾帧时必须有尾帧输入，否则 vidgen 提交 KeyError（L-124 ep01-S1）
                lf = LASTS_OF.get(spec.id)
                if not lf or not ff:
                    return {"status": "no_last_frame"}
                if lf["created_at"] < str(ff.get("created_at") or ""):   # 首尾要成对：尾帧比所用首帧旧 = 由旧首帧做的，不能配（E13 同理）
                    return {"status": "no_last_frame:stale_pair"}
                inputs[v] = lf["file"]
            elif v.startswith("@look:"):      # Ref2VA 造型槽（REFLOCK 审过的 look_refs，K-REN-303）
                name = v[6:]
                slot = next((s for s in plan["ref_slots"] if s.get("role") == "outfit" and s.get("character") == name
                             and s.get("path")), None)
                if not slot:
                    return {"status": f"no_look:{name}"}
                inputs[v] = slot["path"]
            elif v.startswith("@ref:"):
                name = v[5:]
                slot = next((s for s in plan["ref_slots"] if s.get("character") == name and s.get("role") == "identity"), None)
                if not slot or not slot.get("path"):
                    return {"status": f"no_ref:{name}"}
                inputs[v] = slot["path"]
    # GEN_CONTRACT §0 preflight（REFLOCK ns_agent.gen_contract）：结果随作业带走；vidgen 在非 validate 模式下 ok=False 不提交
    loras = [[n["inputs"].get("lora_name"), n["inputs"].get("strength_model")] for n in plan["graph"].values()
             if n["class_type"].startswith("LoraLoader")]
    ffp = (frames_of.get(spec.id) or {}).get("postflight")
    try:
        from ns_agent.gen_contract import preflight as PF
        pf = PF("video", {"model": rid, "project": RUN_ID, "shot_id": spec.id,
                          "cast": [{"name": c.name, "presence": c.presence, "x": c.screen_x, "depth": c.depth}
                                   for c in spec.characters_on_screen],
                          "prompt": plan["prompt"]["text"], "refs": list(inputs.values()), "loras": loras,
                          "compiled_by": "ns_recipes.compiler.compile_shot", "mode": plan["mode"],
                          "look_refs": bool(ov.get("ref2va.look_refs")),
                          "ref_slots": plan["ref_slots"],
                          "first_frame_postflight": ffp or {}})
        pf = {"ok": bool(pf.get("ok")), "reasons": pf.get("reasons") or [],
              "items": [{k: i.get(k) for k in ("id", "status", "detail")} for i in pf.get("items") or []]}
    except Exception as e:  # noqa: BLE001
        pf = {"ok": False, "reasons": [f"preflight 调用失败：{e}"], "items": []}
    return {
        "preflight": pf,
        "status": plan["status"], "recipe": rid, "mode": plan["mode"], "attempt": attempt, "variant": variant,
        "seed": plan["seed"], "frames": plan["frames"], "long": plan["lane"]["long"], "prompt": plan["prompt"]["text"],
        "prompt_notes": plan["prompt"]["notes"], "graph": plan["graph"], "inputs": inputs,
        "ref_slots": plan["ref_slots"], "acceptance": plan["acceptance"], "plan_hash": plan["plan_hash"],
        "lint_errors": [i for i in plan["lint"] if i["level"] == "error"],
        "lint_warns": [i["code"] for i in plan["lint"] if i["level"] != "error"],
        "compiled_by": "ns_recipes.compiler.compile_shot", "compiler_version": plan["compiler_version"],
    }


def shot_meta(spec) -> dict:
    return {"shot": spec.id, "ep": spec.episode, "idx": spec.index, "seconds": float(spec.duration_s),
            "frames": spec.frames, "size": spec.camera.size,
            "faces": [c.name for c in spec.faces], "visible": [c.name for c in spec.visible],
            "dialogue": [{"speaker": d.speaker, "text": d.text, "off": d.off_screen} for d in spec.audio.dialogue],
            "voiceover": ({"speaker": spec.audio.voiceover.speaker, "text": spec.audio.voiceover.text}
                          if spec.audio.voiceover else None),
            "explicit": bool(spec.rating.explicit), "spec_hash": spec.spec_hash()}


def score_refs(spec, reg) -> dict:
    """视频打分的身份参考 = 当前身份脸，一律走 asset_refs.face_of（K-OPS-E29 身份脸唯一入口）。
    旧写法读配方 ref2va_pdd2 的 identity_crops，L-122 换脸后还是旧脸（帧打分已是新脸，两套口径分叉）"""
    from ns_agent import asset_refs as AR
    out = {}
    ids = name_ids()
    for c in spec.faces:
        cid = ids.get(c.name)
        f = AR.face_of(RUN.name, cid) if cid else None
        if f:
            out[c.name] = f
    return out


def build_all(validate_only=False) -> dict:
    if RUN_ID is None:
        raise RC.VideoRunError(_RUN_ERR or "build_jobs 没有设剧（set_run）")
    holds = video_holds()
    reg = R.load()
    specs = (sys.path.append(str(ROOT)) if str(ROOT) not in sys.path else None) or __import__("tools.master.sop_gate", fromlist=["_"]).filter_video_specs(RUN_ID, load_specs())  # HARNESS-O：SOP 阶段闸门（没过“视频”闸门的集不编作业）
    frames_of = chosen_frames() if validate_only else passed_frames()
    LASTS_OF.clear()
    LASTS_OF.update(passed_lasts())
    alts = alt_crops()
    VID.mkdir(parents=True, exist_ok=True)
    (VID / "specs").mkdir(exist_ok=True)
    (VID / "prompts").mkdir(exist_ok=True)
    ch = recipe_choice()
    # 配方里的身份裁切是 V1 的脸：只给 legacy 剧；其它剧的身份槽只走 asset_refs.face_of（compiler.ref_slots，L-126）
    crops = ((reg.resolve("ref2va_pdd2").get("ref2va") or {}).get("identity_crops") or {}) if RC.is_legacy(RUN_ID) else {}
    ids = name_ids()
    shots = []
    for sid, spec in specs.items():
        (VID / "specs" / f"{sid}.spec.json").write_text(spec.model_dump_json(indent=1, by_alias=True), encoding="utf-8")
        if validate_only and sid not in VALIDATE["shots"]:
            continue
        meta = shot_meta(spec)
        hosts = json.loads((VID / "hosts.json").read_text(encoding="utf-8")) if (VID / "hosts.json").exists() else {}
        meta["host"] = hosts.get(str(spec.episode)) or HOST_OF_EP.get(spec.episode)   # night.py 按卡空闲情况分集；非 V1 没有 hosts.json = None（不派）
        meta["first_frame"] = (frames_of.get(sid) or {}).get("file")
        meta["first_frame_status"] = (frames_of.get(sid) or {}).get("status")
        # DATAALIGN（register_takes from_first）：输入 JPEG 名里的 sha8 = 源 PNG 的 sha256 前 8 位；这里把源文件和版本号也写明
        meta["first_frame_src"] = (frames_of.get(sid) or {}).get("src")
        meta["first_frame_take"] = (frames_of.get(sid) or {}).get("take")
        meta["score_refs"] = score_refs(spec, reg)
        vs = {}
        if validate_only:
            for arm, rid in VALIDATE["arms"].items():
                for k, sd in enumerate(VALIDATE["seeds"], 1):
                    vs[f"{arm}_s{k}"] = compile_variant(spec, reg, rid, 1, f"{arm}_s{k}", frames_of, seed=sd)
        elif spec.faces:
            # S10V-1 结论（K-REN-301）：有通过的首帧 → 首帧路线 I2VA PDD 两段式（构图 / 景别跟首帧）；
            # 没有通过的首帧，或首帧路线身份不过 → 纯 Ref2VA 24 步（脸部裁切）。Ref2VA + PDD 两段式不用（景别 4/5 退成全景）
            ref = ch.get("ref_default", "two_person_ref2va")
            idc = {"ref2va.identity_crops": crops, "ref2va.look_refs": True}   # REFLOCK 11-01：Ref2VA 必带造型参考（I3）
            alt_map = {c.name: alts.get(ids.get(c.name, ""), crops.get(c.name)) for c in spec.faces}
            alt_crop = {"ref2va.identity_crops": {**crops, **{k: v for k, v in alt_map.items() if v}}, "ref2va.look_refs": True}
            if sid in frames_of:
                d = ch["face_default"]
                meta["route"] = "first_frame"
                vs["v1"] = compile_variant(spec, reg, d, 1, "v1", frames_of)
                for a in (2, 3, 4):
                    vs[f"s{a}"] = compile_variant(spec, reg, d, a, f"s{a}", frames_of)
                vs["mot"] = compile_variant(spec, reg, d, 2, "mot", frames_of, extra={"prompt.min_motion_cue": MIN_MOTION_CUE})
                vs["r24"] = compile_variant(spec, reg, ref, 1, "r24", frames_of, extra=idc)
                vs["alt"] = compile_variant(spec, reg, ref, 2, "alt", frames_of, extra=alt_crop)
            elif not validate_only:
                # 逐镜派单（总调度 11-01）：正式出片只给首帧已过契约的镜出变体；纯 Ref2VA 兜底要等造型参考槽（preflight I3）
                meta["route"] = "waiting_frame"
            else:
                meta["route"] = "ref2va"
                vs["v1"] = compile_variant(spec, reg, ref, 1, "v1", frames_of, extra=idc)
                for a in (2, 3, 4):
                    vs[f"s{a}"] = compile_variant(spec, reg, ref, a, f"s{a}", frames_of, extra=idc)
                vs["alt"] = compile_variant(spec, reg, ref, 2, "alt", frames_of, extra=alt_crop)
        elif sid not in frames_of:
            meta["route"] = "blocked_no_frame"      # 无人露脸镜只能走首帧；首帧没过契约 → 不出（资料不全不渲染）
        else:
            d = ch["noface_default"]
            vs["v1"] = compile_variant(spec, reg, d, 1, "v1", frames_of)
            for a in (2, 3, 4):
                vs[f"s{a}"] = compile_variant(spec, reg, d, a, f"s{a}", frames_of)
            vs["b24"] = compile_variant(spec, reg, "establishing", 1, "b24", frames_of)
            vs["mot"] = compile_variant(spec, reg, d, 2, "mot", frames_of, extra={"prompt.min_motion_cue": MIN_MOTION_CUE})
        if not validate_only and sid in holds:      # 按镜 hold：不出变体（vidgen 无变体 → waiting_frame，不派单）
            vs = {}
            meta["route"], meta["hold"] = "hold", holds[sid]
        for k, v in vs.items():
            if v.get("prompt"):
                (VID / "prompts" / f"{sid}.{k}.txt").write_text(v["prompt"], encoding="utf-8")
        meta["variants"] = vs
        meta["ladder_order"] = list(vs)
        shots.append(meta)
    if validate_only:   # 对照组按 seed 分到两台（seed1 → gpu33，seed2 → gpu36），6 道一起跑
        split = []
        for m in shots:
            for host, tag in (("gpu33", "_s1"), ("gpu36", "_s2")):
                mm = dict(m, host=host, variants={k: v for k, v in m["variants"].items() if k.endswith(tag)})
                mm["ladder_order"] = list(mm["variants"])
                split.append(mm)
        shots = split
    shots.sort(key=lambda m: (m["ep"], m["idx"]))
    out = {"schema": "series10_video.jobs/1", "run": RUN_ID, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "built_by": "tools/series10_video/build_jobs.py", "recipe_choice": ch,
           "validate": VALIDATE if validate_only else None, "anomaly_skipped": dict(ANOMALY_SKIPPED), "shots": shots}
    blob = json.dumps(out, ensure_ascii=False, indent=1)
    out_p = VID / ("validate_jobs.json" if validate_only else "jobs.json")
    out_p.write_text(blob, encoding="utf-8")
    bad = [(m["shot"], k, v.get("status"), [e["code"] for e in v.get("lint_errors", [])])
           for m in shots for k, v in m["variants"].items() if v.get("status") != "ready"]
    return {"file": rel(out_p), "shots": len(shots), "variants": sum(len(m["variants"]) for m in shots),
            "not_ready": bad, "sha": hashlib.sha256(blob.encode()).hexdigest()[:12]}


try:
    set_run(RC.resolve())
except RC.VideoRunError as _e:     # 导入时认不出剧：不炸导入方（night / 测试会 set_run），build_all 前再报（失败关闭）
    _RUN_ERR = str(_e)
else:
    _RUN_ERR = None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    set_run(RC.resolve())          # 失败关闭：--run / NS_RUN / 当前剧，必须登记且有视频政策
    if "--validate" in sys.argv and not RC.is_legacy(RUN_ID):
        raise SystemExit("--validate 是 V1 的 S10V-1 对照（IMGGEN 旧首帧），只给 legacy 剧")
    print(json.dumps(build_all("--validate" in sys.argv), ensure_ascii=False, indent=1))
