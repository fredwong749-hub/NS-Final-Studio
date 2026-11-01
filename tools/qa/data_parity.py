"""前端显示 = 后端数据 的对齐检查（DATAALIGN 2026-11-01；契约 docs/DATA_MAP.md；规则 K-DATA-001）。

项目方原话（11-01）：“S1、S2、S3、S4 的每一个 scene 里面，对应的剧本、对应的人头都不太一样，但我发现你都是一模一样，
所以里面的 content 都是错的……你全部 scan 一下整个 system，看看还有哪些地方 Backend 跟 Front end 的 data 没有对齐。”

做什么（只读：不写文件、不起停服务、不出图）：
  每集抽 N 镜（默认首 / 中 / 尾 3 镜；--all 全部），取接口值，再直接读源文件，逐项断言相等：
    D-SHOT   /api/episodes/{n} 的镜号列表 = 剧本 data/import/script_v2.json
    D-SCRIPT storyboard.img_prompt / motion_prompt / scene_id / cast_raw = 导入稿 data/import/script_v2.json 该镜字段
             （CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：⤴ 原来还拿写作运行 P4_epNN.md 原文比，导入 D-SCR-07 后 80 → 93 镜，P4 是旧稿；
              现在只在显式 NS_ALLOW_P4_SOURCE=1 时附加 P4 对照，供写作 / 调研排查）
    D-DUR    duration.seconds = 剧本时长（剧本写了的）
    D-DLG    dialogue[].text = 剧本对白
    D-CAST   characters[] 人选 = 剧本本镜 **人物** 行里 在画 / 局部 的人（画外不算）
    D-LOOK   characters[].look_label = 出图用的造型（资产中心整集排期 > <run>/assets/shot_looks.json 登记）
    D-FACE   characters[].face_url = 出图用的身份脸（data/looks/face_overrides.json > config/recipes/asset_refs.json faces）
    D-FRAME  first_frame / video 指向的文件在盘上
    D-SCENE  /api/sop/episode/{n} 的 scene_id（画布场景小卡）= 剧本 scene_id
    D-VARY   源数据里各镜不同的字段（人选 + 造型字母、剧本文字），接口里不能整集都一样
    D-COUNT  集摘要 /api/episodes/summary 的镜数 = 剧本；首帧数 = 详情里有首帧的镜数（摘要随 takes.json 同步刷新，不一致即失败）
    D-IMG    /api/story-images 默认运行 = 当前剧本自己的运行
    D-FRESH  当前首帧 / 尾帧晚于剧本最后一次改动（data/import/script_v2.json mtime）→ 不得标“剧本已改”；frame_v9 版本
             还晚于拼提示词的代码 → 连“编译器升级”也不得有
    D-CUR    takes.json 当前首帧 / 尾帧 = 接口 first_frame / last_frame_target（PW-011）
             （UIPIXEL 11-01 P1：unified 出图版本一出来就被标过期）
    D-VIDEO  VIDEO10 过了片子门的选中片（runs/<剧>/video/state_<host>.json status=done）已登记成视频版本，
             接口 shots[].video 指向它（项目方定稿了别的视频除外）；集摘要视频数 = 详情里有视频的镜数
    D-DURSUM 每集总秒数：/api/season（全剧总览）= /api/episodes/{n}（画布 / 批量出视频）
    D-LOOKGATE 顶栏 ②“造型待确认”的人物（/api/looks/episodes/{n}）= 剧本本集在画 / 局部的人
    D-SCENEUSE 场景卡“使用镜头数 / 集”（/api/assets/scenes）= 剧本 scene_id 统计
    D-CANDVER  UIRSI r40（项目方 11-02 00:0x：“我…看到很多错误的图”）：/api/candidates 当作可挑候选（ok 不是 false）的每一版，
               必须是现行剧本版本——出图时间不早于本集最后一次导入（import_log.jsonl，按路径 _epNN_ 归集），或带的 prompt_source.sha256
               = 现行剧本 sha；/api/season 的候选数 = 这样的版本数。独立按 takes.json + import_log 算，不调接口里的判定
  --ui EP：再用无头 Chrome（apps/web/e2e/dataalign/probe.mjs，只读查看令牌）打开剧本页第 EP 集，
           逐行比对页面上的人物小卡（名字 + 造型字母）= 接口。
  --inproc：不走 :8800，进程内调用 ns_api.app（:8800 还没重启时验证新代码；会 import 整个 API，较慢）

用法：.venv/Scripts/python.exe tools/qa/data_parity.py [--all] [--per-ep 3] [--eps 1,3] [--ui 3] [--inproc] [--json out.json]
退出码：0 = 全部一致；1 = 有不一致（逐条列出）；2 = 未测（接口取不到，或 :8800 还在跑旧代码需重启）。
"""
from __future__ import annotations

import argparse
import os
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8800"
SCRIPT = ROOT / "data" / "import" / "script_v2.json"
CFG = ROOT / "config" / "recipes" / "asset_refs.json"
HUB_EP = ROOT / "data" / "looks" / "hub_episode_looks.json"
FACE_OV = ROOT / "data" / "looks" / "face_overrides.json"
ON_SCREEN = ("在画", "局部")
# frame_v9 提示词由这些代码拼出（ns_agent.frame_job.build_first → compiler.compile_shot + asset_refs 槽位 + S★ 后缀）
BUILDER_FILES = [ROOT / "services" / "agent" / "ns_agent" / f for f in
                 ("frame_job.py", "compiler.py", "asset_refs.py", "bible.py", "gen_contract/style.py")] +                 [ROOT / "config" / "visual_bible.toml", ROOT / "config" / "recipes" / "asset_refs.json"]


IMPORT_LOG = ROOT / "data" / "import" / "import_log.jsonl"


def last_import_at(log: Path = IMPORT_LOG, script: Path = SCRIPT) -> str:
    """现行导入稿的导入时刻（import_log.jsonl 最后一条的 at；没有日志时用 script_v2.json 修改时间）"""
    import time as _t
    try:
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        ats = [str(r.get("at") or "") for r in rows if r.get("at")]
        if ats:
            return max(ats)
    except (OSError, ValueError):
        pass
    return _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(script.stat().st_mtime)) if script.exists() else ""


def pending_redo(takes: dict, import_at: str) -> str | None:
    """CLEANUP 11-01（总调度定，L-088 全量重做期间）：新剧本已导入、出图还没跟上的镜 = pending_redo，不算不一致。
    判据：没有当前首帧，或当前首帧的 created_at 早于（含等于）现行导入时刻。该镜新首帧（导入之后出的）设为当前后自动转回比对。
    返回原因（None = 已跟上，照常比对）"""
    act = (takes or {}).get("active") or {}
    n = act.get("image")
    t = next((t for t in (takes or {}).get("takes") or [] if t.get("stage") == "image" and t.get("n") == n), None) if n is not None else None
    if t is None:
        return "无当前首帧"
    ca = str(t.get("created_at") or "")
    if not ca or (import_at and ca <= import_at):
        return f"当前首帧 #{n} {ca or '无时间'} 早于导入 {import_at}"
    return None


PARITY_CFG = ROOT / "config" / "data_parity.json"
ALERTS = ROOT / "data" / "qa" / "alerts.jsonl"
PENDING_ALERT_ID = "A-PARITY-PENDING"


def pending_max_hours(cfg: Path | None = None) -> float:
    """pending_redo 的上限小时数（config/data_parity.json pending_redo_max_hours，缺省 12；AUDIT P2）"""
    try:
        return float(json.loads(Path(cfg or PARITY_CFG).read_text(encoding="utf-8")).get("pending_redo_max_hours", 12))
    except (OSError, ValueError, TypeError):
        return 12.0


def overdue_pending(pending: dict, import_at: str, max_h: float, now: float | None = None) -> tuple[list[str], float]:
    """待重做从现行导入时刻算起，超过 max_h 小时 = 过期待重做（全部 pending 镜一起过期）。→ (镜号, 已挂小时)"""
    import time as _t
    now = _t.time() if now is None else now
    try:
        t0 = _t.mktime(_t.strptime(import_at[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return [], 0.0
    age = (now - t0) / 3600
    return (sorted(pending) if pending and age > max_h else []), round(age, 1)


def sync_pending_alert(overdue: list[str], age_h: float, max_h: float, alerts: Path | None = None) -> str | None:
    """复用 infra_watchdog 的报警格式（data/qa/alerts.jsonl，监控看板 :8810 显示）：有过期待重做且没开着 → 写 open；
    清零且开着 → 写 closed。返回写入的 state（没写返回 None）"""
    import time as _t
    alerts = Path(alerts or ALERTS)
    last = None
    try:
        for ln in alerts.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                if r.get("id") == PENDING_ALERT_ID:
                    last = r
    except (OSError, ValueError):
        pass
    is_open = bool(last and last.get("state") == "open")
    rec = None
    if overdue and not is_open:
        rec = {"ts": _t.strftime("%Y-%m-%dT%H:%M:%S"), "t": _t.time(), "id": PENDING_ALERT_ID, "state": "open", "level": "warn",
               "msg": f"data_parity：{len(overdue)} 镜导入后出图未跟上已 {age_h} 小时（上限 {max_h:g} 小时，L-088 全量重做）：{','.join(overdue[:30])}",
               "by": "data_parity", "shots": overdue}
    elif not overdue and is_open:
        rec = {"ts": _t.strftime("%Y-%m-%dT%H:%M:%S"), "t": _t.time(), "id": PENDING_ALERT_ID, "state": "closed", "msg": "已恢复",
               "by": "data_parity", "opened": last.get("ts")}
    if rec:
        alerts.parent.mkdir(parents=True, exist_ok=True)
        with open(alerts, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec["state"]
    return None


def rj(p: Path, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


class Api:
    def __init__(self, inproc: bool):
        self.inproc = inproc
        self.app = None
        if inproc:
            for sub in ("services/api", "services/agent", "services/render_router", "packages/schema"):
                sys.path.insert(0, str(ROOT / sub))
            from ns_api import app as APP  # noqa: PLC0415
            self.app = APP
        try:
            self.tok = (ROOT / "data" / "auth" / "viewer_token").read_text(encoding="utf-8").strip()
        except OSError:
            self.tok = ""

    def get(self, path: str):
        if self.inproc:
            a = self.app
            m = re.match(r"^/api/episodes/(\d+)$", path)
            if m:
                return a.episode_detail(int(m.group(1)))
            if path == "/api/episodes/summary":
                return a.episodes_summary()
            m = re.match(r"^/api/sop/episode/(\d+)$", path)
            if m:
                return a.sop_episode(int(m.group(1)))
            m = re.match(r"^/api/looks/episodes/(\d+)$", path)
            if m:
                from ns_api.looks import get_episode  # noqa: PLC0415
                from ns_agent.looks import default_store  # noqa: PLC0415
                return get_episode(int(m.group(1)), default_store())
            if path == "/api/season":
                from ns_api import season as SEA  # noqa: PLC0415
                return SEA.season()
            if path == "/api/assets/scenes":
                from ns_api import scene_assets as SCA  # noqa: PLC0415
                from ns_agent.looks import default_store as _ds  # noqa: PLC0415
                return SCA.list_scenes(_ds())
            if path == "/api/story-images":
                from ns_api.story_runs import story_images  # noqa: PLC0415
                return story_images()
            m = re.match(r"^/api/candidates\?ep=(\d+)$", path)   # UIRSI r40：D-CANDVER
            if m:
                from ns_api import takes_ui as TU  # noqa: PLC0415
                return TU.candidates(int(m.group(1)))
            raise KeyError(path)
        req = urllib.request.Request(API + path, headers={"x-ns-viewer-token": self.tok} if self.tok else {})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))


def p4_shots(run_dir: Path, n: int) -> list[dict] | None:
    f = run_dir / f"ep{n:02d}" / f"P4_ep{n:02d}.md"
    if not f.is_file():
        return None
    t = re.sub(r"<!--[\s\S]*?-->", "", f.read_text(encoding="utf-8"))
    out = []
    for part in re.split(r"\n(?=\*\*镜\s*\d+)", t)[1:]:
        lines = part.split("\n")
        m0 = re.match(r"^\*\*镜\s*(\d+)[^*]*\*\*[：:]?\s*(.*)$", lines[0])
        fl = {"_img": m0.group(2) if m0 else ""}
        for ln in lines[1:]:
            m = re.match(r"^\*\*([^*]{1,16})\*\*[：:]\s*(.*)$", ln)
            if m:
                fl[m.group(1)] = m.group(2)
        out.append(fl)
    return out


def parse_cast(raw: str) -> list[tuple[str, str]]:
    """“林晚（在画｜中｜前）、顾沉（画外）” → [(林晚, 在画), (顾沉, 画外)]"""
    out = []
    for it in re.split(r"[、，,]", raw or ""):
        it = it.strip()
        if not it:
            continue
        m = re.match(r"^([^（(]+)[（(]([^）)]*)[）)]", it)
        out.append((m.group(1).strip(), m.group(2).split("｜")[0].split("|")[0].strip()) if m else (it, "在画"))
    return out


def sample(n: int, k: int, all_: bool) -> list[int]:
    if all_ or n <= k:
        return list(range(n))
    idx = {0, n // 2, n - 1}
    i = 1
    while len(idx) < k and i < n:
        idx.add(i)
        i += 2
    return sorted(idx)


def main() -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="每集全部镜头（默认每集抽 --per-ep 镜）")
    ap.add_argument("--per-ep", type=int, default=3)
    ap.add_argument("--eps", default="", help="只查这些集，逗号分隔")
    ap.add_argument("--ui", type=int, default=0, help="再用无头 Chrome 核对剧本页第 N 集的人物小卡")
    ap.add_argument("--inproc", action="store_true", help="进程内调用 ns_api.app（不走 :8800）")
    ap.add_argument("--json", default="", help="把结果写成 JSON")
    a = ap.parse_args()

    fails: list[str] = []
    warns: list[str] = []
    checked = {"shots": 0, "fields": 0}
    pending: dict[str, str] = {}          # 镜号 → pending_redo 原因（导入后出图未跟上，L-088 全量重做补）
    import_at = last_import_at()

    def eq(code: str, sid: str, what: str, got, want):
        checked["fields"] += 1
        if got != want:
            fails.append(f"{code} {sid} {what}: 显示/接口={str(got)[:120]!r} ≠ 源={str(want)[:120]!r}")

    script = rj(SCRIPT)
    if not script:
        print(f"UNTESTED 读不到剧本 {SCRIPT}")
        return 2
    cfg = (rj(CFG, {}) or {}).get("projects") or {}
    src_paths = [str(s.get("path") or "") for s in script.get("sources") or []]
    project = next((k for k in cfg if any(k in p for p in src_paths)), None)
    pc = cfg.get(project) or {}
    run_dir = ROOT / (pc.get("run_dir") or "_none_")
    reg = ((rj(ROOT / pc["shot_looks_file"], {}) or {}).get("shots") or {}) if pc.get("shot_looks_file") else {}
    hub_ep = ((rj(HUB_EP, {}) or {}).get(project) or {}) if project else {}
    face_ov = ((rj(FACE_OV, {}) or {}).get(project) or {}) if project else {}
    looks = rj(ROOT / pc.get("looks_file", "_none_"), []) or []
    name_id = {c.get("name"): c.get("char_id") for c in looks if c.get("name")}

    def face_file(cid: str) -> str | None:
        cands = ([face_ov[cid]] if isinstance(face_ov.get(cid), str) else []) + list((pc.get("faces") or {}).get(cid) or [])
        return next((f for f in cands if (ROOT / f).is_file()), None)

    def letter(cid: str, ep_n: int, sid: str) -> str | None:
        v = (hub_ep.get(cid) or {}).get(str(ep_n))
        if isinstance(v, str) and v:
            return v
        r = (reg.get(sid) or {}).get(cid)
        return (r or {}).get("look") if isinstance(r, dict) else r

    try:
        api = Api(a.inproc)
        summ = api.get("/api/episodes/summary")
    except Exception as e:  # noqa: BLE001
        print(f"UNTESTED 接口取不到（{'进程内' if a.inproc else API}）：{e}")
        return 2

    eps = script.get("episodes") or []
    if project and not a.inproc and eps:
        try:
            probe = api.get(f"/api/episodes/{eps[0]['number']}")
            chars = [c for x in probe.get("shots") or [] for c in x.get("characters") or []]
            if chars and not any(c.get("cast_source") for c in chars):
                print("UNTESTED :8800 还在跑旧代码（镜头卡人物没有 cast_source，DATAALIGN 的 shot_cast 未生效）——需要重启 :8800 后再测；"
                      "可先用 --inproc 验证新代码")
                return 2
        except Exception:  # noqa: BLE001
            pass
    want_eps = {int(x) for x in a.eps.split(",") if x.strip()} if a.eps else None
    s_eps = {e["number"]: e for e in (summ.get("episodes") or [])}
    if sorted(s_eps) != sorted(e["number"] for e in eps):
        fails.append(f"D-COUNT 集列表：摘要={sorted(s_eps)} ≠ 剧本={sorted(e['number'] for e in eps)}")

    ui_api: dict = {}
    for e in eps:
        n = e["number"]
        if want_eps and n not in want_eps:
            continue
        shots = e.get("shots") or []
        try:
            det = api.get(f"/api/episodes/{n}")
            sop = api.get(f"/api/sop/episode/{n}")
        except Exception as ex:  # noqa: BLE001
            fails.append(f"D-SHOT ep{n:02d} 接口失败：{ex}")
            continue
        ash = det.get("shots") or []
        ui_api[n] = ash
        ids = [s["id"] for s in ash]
        sids = [f"ep{n:02d}-S{s['index']}" for s in shots]
        eq("D-SHOT", f"ep{n:02d}", "镜号列表", ids, sids)
        # 摘要计数
        sm = (s_eps.get(n) or {}).get("summary") or {}
        if sm.get("shots") != len(shots):
            fails.append(f"D-COUNT ep{n:02d} 摘要镜数={sm.get('shots')} ≠ 剧本 {len(shots)}")
        ff = sum(1 for s in ash if s.get("first_frame"))
        if sm.get("first_frames") is not None and sm.get("first_frames") != ff:
            fails.append(f"D-COUNT ep{n:02d} 摘要首帧数={sm.get('first_frames')}，详情={ff}（摘要应随 takes.json 同步刷新）")
        p4 = p4_shots(run_dir, n) if project and os.environ.get("NS_ALLOW_P4_SOURCE") == "1" else None
        stale_ep = {}   # 当前首帧早于现行导入（或没有首帧）的镜：照常比对，比不上才记 pending_redo，不算不一致
        for s_ in shots:
            sid_ = f"ep{n:02d}-S{s_['index']}"
            why = pending_redo(rj(ROOT / "data" / "renders" / f"ep{n:02d}" / f"S{s_['index']}" / "takes.json", {}) or {}, import_at)
            if why:
                stale_ep[sid_] = why
        sop_scene = {x["id"]: x.get("scene_id") for x in sop.get("shots") or []}
        by_id = {s["id"]: s for s in ash}
        exp_keys, got_keys, exp_txt, got_txt, key_sids = [], [], [], [], []
        for i, s in enumerate(shots):
            sid = f"ep{n:02d}-S{s['index']}"
            x = by_id.get(sid)
            if x is None:
                continue
            cast = [(nm, pr) for nm, pr in parse_cast(s.get("cast_raw") or "") if pr in ON_SCREEN]
            ek = tuple(sorted((name_id.get(nm, nm), letter(name_id.get(nm, nm), n, sid) or "") for nm, _ in cast))
            gk = tuple(sorted((c["character"], c.get("look_label") or "") for c in x.get("characters") or []))
            exp_keys.append(ek)
            key_sids.append(sid)
            got_keys.append(gk)
            exp_txt.append(s.get("motion_prompt"))
            got_txt.append(x.get("script_text"))
            if i not in sample(len(shots), a.per_ep, a.all):
                continue
            checked["shots"] += 1
            sb = x.get("storyboard") or {}
            for k in ("img_prompt", "motion_prompt", "scene_id", "cast_raw"):
                eq("D-SCRIPT", sid, k, sb.get(k), s.get(k))
            if p4 is not None and i < len(p4):
                f = p4[i]
                eq("D-SCRIPT", sid, "img_prompt=P4", sb.get("img_prompt"), f.get("_img"))
                eq("D-SCRIPT", sid, "motion=P4", sb.get("motion_prompt"), f.get("motion"))
                eq("D-SCRIPT", sid, "scene=P4", sb.get("scene_id"), (f.get("场景") or "").split("｜")[0] or None)
                eq("D-SCRIPT", sid, "人物=P4", sb.get("cast_raw"), f.get("人物"))
            if s.get("duration_source") == "script":
                eq("D-DUR", sid, "时长", (x.get("duration") or {}).get("seconds"), s.get("duration"))
            eq("D-DLG", sid, "对白", [d.get("text") for d in x.get("dialogue") or []], [d.get("text") for d in s.get("dialogue") or []])
            if project:
                got_c = sorted(c["character"] for c in x.get("characters") or [])
                want_c = sorted(name_id.get(nm, nm) for nm, _ in cast)
                looks_bad = [c.get("name") for c in x.get("characters") or []
                             if letter(c["character"], n, sid) and c.get("look_label") != letter(c["character"], n, sid)]
                if sid in stale_ep and (got_c != want_c or looks_bad):
                    checked["fields"] += 1
                    pending[sid] = stale_ep[sid] + f"；人选 / 造型与导入稿不一致（{'人选' if got_c != want_c else ''}{' 造型' if looks_bad else ''}）"
                else:
                    eq("D-CAST", sid, "人选", got_c, want_c)
                for c in x.get("characters") or []:
                    want = letter(c["character"], n, sid)
                    if want and sid not in pending:
                        eq("D-LOOK", sid, f"{c.get('name')} 造型字母", c.get("look_label"), want)
                    ff_ = face_file(c["character"])
                    if ff_:
                        eq("D-FACE", sid, f"{c.get('name')} 脸", ff_.removeprefix("data/") in urllib.parse.unquote(c.get("face_url") or "")
                           or ff_ in urllib.parse.unquote(c.get("face_url") or ""), True)
            for k in ("first_frame", "video"):
                u = x.get(k)
                if u and u.startswith("/files/"):
                    rel = urllib.parse.unquote(u.split("?")[0][len("/files/"):])
                    eq("D-FRAME", sid, k, (ROOT / "data" / rel).is_file(), True)
            eq("D-SCENE", sid, "场景小卡 scene_id", sop_scene.get(sid), s.get("scene_id"))
        # D-FRESH：剧本最后改动之后出的当前首帧 / 尾帧，不能是“剧本已改”；
        #   frame_v9 版本（画布 unified_frame 或 frames_v2 登记，params.origin.recipe=frame_v9）若还晚于拼提示词的代码，
        #   连“编译器升级”也不能有（同一个 frame_job 拼的，PW 11-01 第 2 条）
        # D-CUR（PW-011）：takes.json 的当前首帧 / 尾帧 = 接口 first_frame / last_frame_target（gpu3 负责的镜头除外）
        import time as _t
        fmt = lambda ts: _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(ts))   # noqa: E731
        script_mt = fmt(SCRIPT.stat().st_mtime)
        builder_mt = fmt(max([SCRIPT.stat().st_mtime] + [f.stat().st_mtime for f in BUILDER_FILES if f.is_file()]))
        for x in ash:
            ep_s, sn = x["id"].split("-")
            tk = rj(ROOT / "data" / "renders" / ep_s / sn / "takes.json", {}) or {}
            act = tk.get("active") or {}
            for st, key, url_key, lab in (("image", "first_frame_take", "first_frame", "首帧"), ("last", "last_frame_take", "last_frame_target", "尾帧"),
                                       ("video", None, "video", "视频")):
                t = next((t for t in tk.get("takes") or [] if t.get("stage") == st and t.get("n") == act.get(st)), None)
                if t and x.get("owner") != "gpu3" and x.get("frames_source") != "gpu3":
                    checked["fields"] += 1
                    u = urllib.parse.unquote((x.get(url_key) or "").split("?")[0])
                    if not u.endswith(str(t.get("file") or "")):
                        fails.append(f"D-CUR {x['id']} 当前{lab} #{t.get('n')}={t.get('file')}，接口 {url_key}={x.get(url_key)!r}")
                if not t or str(t.get("created_at") or "") <= script_mt:
                    continue
                checked["fields"] += 1
                loc, glo = (x.get("stale") or {}).get(st) or [], (x.get("stale_global") or {}).get(st) or []
                if "剧本已改" in loc:
                    fails.append(f"D-FRESH {x['id']} {lab} #{t.get('n')}（{t.get('created_at')}，{t.get('workflow')}）晚于剧本改动 {script_mt}，却标“剧本已改”")
                v9 = t.get("workflow") == "frame_v9_unified" or ((t.get("params") or {}).get("origin") or {}).get("recipe") == "frame_v9"
                if v9 and str(t.get("created_at")) > builder_mt and (loc or glo):
                    fails.append(f"D-FRESH {x['id']} {lab} #{t.get('n')}（frame_v9，{t.get('created_at')}）晚于剧本和拼提示词代码（{builder_mt}），却标过期 {loc + glo}")
        for k, sid_ in enumerate(key_sids):
            if sid_ in stale_ep and k < len(got_keys) and got_keys[k] != exp_keys[k]:
                pending.setdefault(sid_, stale_ep[sid_] + "；人选 / 造型与导入稿不一致")
        live_i = [k for k, sid_ in enumerate(key_sids) if sid_ not in pending]
        exp_keys = [exp_keys[k] for k in live_i]
        got_keys = [got_keys[k] for k in live_i]
        live_ids = [key_sids[k].split("-")[1] for k in live_i]
        if project and len(set(exp_keys)) > 1 and len(set(got_keys)) == 1:
            fails.append(f"D-VARY ep{n:02d} 源里各镜人选 / 造型不同（{len(set(exp_keys))} 种），接口整集都是 {got_keys[0]}")
        if project:
            bad = [live_ids[k] for k, (g, w) in enumerate(zip(got_keys, exp_keys)) if g != w]
            if bad and not a.all:   # 抽样外的镜也报个数（全集逐镜比，只比人选 + 造型字母）
                fails.append(f"D-CAST ep{n:02d} 人选 / 造型字母与出图不一致的镜：{','.join(bad)}")
        if len(set(exp_txt)) > 1 and len(set(got_txt)) == 1:
            fails.append(f"D-VARY ep{n:02d} 源里各镜剧本不同，接口 script_text 整集都一样")

    try:
        im = api.get("/api/story-images")
        if project and (run_dir / "images").is_dir():
            eq("D-IMG", "-", "出图新图默认运行", im.get("run"), project)
    except Exception as ex:  # noqa: BLE001
        warns.append(f"D-IMG /api/story-images 取不到：{ex}")

    # D-VIDEO：VIDEO10 选中且过门的片子 → 已登记、是当前视频；摘要视频数 = 详情
    if project:
        vdir = run_dir / "video"
        api_by = {x["id"]: x for ash in ui_api.values() for x in ash}
        for sf in sorted(vdir.glob("state_*.json")):
            if sf.stem.endswith("_validate"):
                continue
            st = rj(sf, {}) or {}
            for sid, v in (st.get("shots") or {}).items():
                ch = v.get("chosen")
                r = next((x for x in v.get("renders") or [] if x.get("variant") == ch and x.get("state") == "scored"), None)
                if v.get("status") != "done" or not r or not ((r.get("score") or {}).get("gate") or {}).get("pass"):
                    continue
                x = api_by.get(sid)
                if x is None:
                    continue
                checked["fields"] += 1
                ep_s, sn = sid.split("-")
                tk = rj(ROOT / "data" / "renders" / ep_s / sn / "takes.json", {}) or {}
                vt = [t for t in tk.get("takes") or [] if t.get("stage") == "video"
                      and (((t.get("params") or {}).get("origin") or {}).get("variant") == ch)
                      and (((t.get("params") or {}).get("origin") or {}).get("host") == st.get("host"))]
                lock = (tk.get("locked") or {}).get("video")
                if not vt:
                    fails.append(f"D-VIDEO {sid} VIDEO10（{st.get('host')}）选中片 {ch} 过了门，没登记成视频版本（tools/pipeline/register_takes.py --video10）")
                elif lock is None and not x.get("video") and not (vt[-1].get("params") or {}).get("retracted"):
                    fails.append(f"D-VIDEO {sid} VIDEO10 片已登记为 v{vt[-1].get('n')}，接口 video 却为空")
        for n, ash in ui_api.items():
            sm = (s_eps.get(n) or {}).get("summary") or {}
            if sm.get("videos") is not None:
                eq("D-VIDEO", f"ep{n:02d}", "摘要视频数", sm.get("videos"), sum(1 for x in ash if x.get("video")))

    # D-LEDGER（警告）：PRODUCER 账本 data/producer/attempts.json 记“已通过”的首 / 尾帧，takes.json 里那一版仍过契约且是当前
    # （11-01 04:49 REFLOCK Q1 全脸重打分把 5 张已通过的首帧打成不过、撤下当前，账本仍写 passed → PRODUCER 不会重出）
    led = rj(ROOT / "data" / "producer" / "attempts.json", {}) or {}
    for obj, r in sorted(led.items()) if isinstance(led, dict) else []:
        if not isinstance(r, dict) or r.get("final") != "passed" or ":" not in obj:
            continue
        kind, sid = obj.split(":", 1)
        st = {"first": "image", "last": "last"}.get(kind)
        hist = [h for h in r.get("history") or [] if h.get("ok")]
        if not st or not hist or "-" not in sid:
            continue
        n = hist[-1].get("take")
        ep_s, sn = sid.split("-")
        tk = rj(ROOT / "data" / "renders" / ep_s / sn / "takes.json", {}) or {}
        t = next((x for x in tk.get("takes") or [] if x.get("stage") == st and x.get("n") == n), None)
        pf_ok = ((t or {}).get("postflight") or {}).get("ok")
        cur_n = (tk.get("active") or {}).get(st)
        cur = next((x for x in tk.get("takes") or [] if x.get("stage") == st and x.get("n") == cur_n), None)
        cur_ok = ((cur or {}).get("postflight") or {}).get("ok") is True
        # 当前是另一版、且它也过契约（例：驳回后替换版经总调度复核换上）→ 账本口径没问题，不报
        if (t is None or pf_ok is False or cur_n != n) and not cur_ok:
            warns.append(f"D-LEDGER {obj} PRODUCER 账本记已通过（v{n}），但 takes.json：契约 ok={pf_ok}，当前={(tk.get('active') or {}).get(st)}"
                         f"（重打分后账本没跟上 → PRODUCER 不会重出）")

    # D-DURSUM：全剧总览与画布的每集总秒数
    try:
        sea = api.get("/api/season")
        sea_eps = {e.get("number"): e for e in (sea.get("episodes") if isinstance(sea, dict) else sea) or []}
        for n, ash in ui_api.items():
            se = sea_eps.get(n)
            if se is None:
                continue
            eq("D-DURSUM", f"ep{n:02d}", "总秒数（总览 vs 画布）", sum((x.get("seconds") or 0) for x in se.get("shots") or []),
               sum(((x.get("duration") or {}).get("seconds") or 0) for x in ash))
    except Exception as ex:  # noqa: BLE001
        warns.append(f"D-DURSUM /api/season 取不到：{ex}")
    # D-CANDVER（UIRSI r40）：界面显示的候选必须属于现行剧本版本（旧剧本候选不得进总览 / 挑选 / 候选数）
    try:
        import hashlib as _hl
        import re as _re
        cut_ep: dict[int, str] = {}
        cut_all = ""
        for ln in (IMPORT_LOG.read_text(encoding="utf-8").splitlines() if IMPORT_LOG.exists() else []):
            try:
                ie = json.loads(ln)
            except ValueError:
                continue
            if ie.get("rc") not in (0, None) or not ie.get("at"):
                continue
            es = {int(x) for x in (ie.get("episodes") or []) if str(x).isdigit()}
            m_ = _re.search(r"_ep(\d{2})_", str(ie.get("path") or ""))
            es = es or ({int(m_.group(1))} if m_ else set())
            if es:
                for k in es:
                    cut_ep[k] = max(cut_ep.get(k, ""), ie["at"])
            else:
                cut_all = max(cut_all, ie["at"])
        cur_sha = _hl.sha256(SCRIPT.read_bytes()).hexdigest()

        def _cur(tk: dict, n_: int) -> bool:
            for src in (tk, tk.get("params") or {}):
                ps = src.get("prompt_source") if isinstance(src, dict) else None
                if isinstance(ps, dict) and ps.get("sha256") == cur_sha:
                    return True
            c_ = max(cut_ep.get(n_, ""), cut_all)
            return not c_ or (tk.get("created_at") or "") >= c_

        season_n: dict[str, int] = {}
        try:
            for se_ in api.get("/api/season").get("episodes") or []:
                for x in se_.get("shots") or []:
                    season_n[x["id"]] = x.get("cand_n") or 0
        except Exception as ex:  # noqa: BLE001
            warns.append(f"D-CANDVER /api/season 取不到：{ex}")
        for e in eps:
            n = e["number"]
            if want_eps and n not in want_eps:
                continue
            cd = api.get(f"/api/candidates?ep={n}").get("shots") or {}
            for sid, row in cd.items():
                m2 = _re.fullmatch(r"ep\d{2}-S(\d+)", sid)
                tj = rj(ROOT / "data" / "renders" / f"ep{n:02d}" / f"S{m2.group(1) if m2 else '0'}" / "takes.json", {}) or {}
                by_n = {(x.get("stage"), x.get("n")): x for x in tj.get("takes") or []}
                for stg in ("image", "last"):
                    x = row.get(stg) or {}
                    shown = [tk for tk in x.get("takes") or [] if tk.get("ok") is not False and not tk.get("bad")]
                    old = [tk["n"] for tk in shown if not _cur(by_n.get((stg, tk.get("n"))) or {}, n)]
                    checked["fields"] += 1
                    if old:
                        fails.append(f"D-CANDVER {sid} {stg}: 接口把旧剧本版本当候选 #{old}（出图早于本集最后一次导入 {max(cut_ep.get(n, ''), cut_all)}）")
                    if stg == "image" and sid in season_n and x.get("active") is None:
                        eq("D-CANDVER", sid, "总览候选数 = 现行剧本版本的合格候选数", season_n[sid], len(shown) - len(old))
    except Exception as ex:  # noqa: BLE001
        warns.append(f"D-CANDVER 取不到：{ex}")
    # D-LOOKGATE：顶栏 ② 造型确认的人物 = 剧本本集在画 / 局部的人
    if project:
        for e in eps:
            n = e["number"]
            if want_eps and n not in want_eps:
                continue
            want = []
            for s_ in e.get("shots") or []:
                for nm, pr in parse_cast(s_.get("cast_raw") or ""):
                    cid = name_id.get(nm, nm)
                    if pr in ON_SCREEN and cid not in want:
                        want.append(cid)
            try:
                got = list((api.get(f"/api/looks/episodes/{n}").get("characters") or {}))
                eq("D-LOOKGATE", f"ep{n:02d}", "造型待确认的人物", sorted(got), sorted(want))
            except Exception as ex:  # noqa: BLE001
                warns.append(f"D-LOOKGATE ep{n:02d} 取不到：{ex}")
        # D-SCENEUSE：场景卡使用镜头数 = 剧本 scene_id 统计
        try:
            sc = api.get("/api/assets/scenes")
            cnt: dict = {}
            for e in eps:
                for s_ in e.get("shots") or []:
                    if s_.get("scene_id"):
                        cnt[s_["scene_id"]] = cnt.get(s_["scene_id"], 0) + 1
            for x in sc.get("scenes") or []:
                if x.get("scene_id") in cnt:
                    eq("D-SCENEUSE", x["scene_id"], "使用镜头数", x.get("shot_count"), cnt[x["scene_id"]])
        except Exception as ex:  # noqa: BLE001
            warns.append(f"D-SCENEUSE /api/assets/scenes 取不到：{ex}")

    ui_note = ""
    if a.ui:
        ui_note = ui_check(a.ui, ui_api.get(a.ui), fails)

    max_h = pending_max_hours()
    overdue, age_h = overdue_pending(pending, import_at, max_h)
    try:
        sync_pending_alert(overdue, age_h, max_h)
    except OSError as ex:
        warns.append(f"D-PENDING 报警写不进 {ALERTS}：{ex}")
    res = {"project": project, "mode": "inproc" if a.inproc else API, "checked": checked, "fails": fails, "warns": warns, "ui": ui_note,
           "pending_redo": pending, "import_at": import_at, "pending_overdue": overdue, "pending_age_h": age_h, "pending_max_h": max_h}
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for w in warns:
        print("WARN", w)
    for f in fails:
        print("FAIL", f)
    if pending:
        by_ep: dict[str, list[str]] = {}
        for sid in sorted(pending, key=lambda x: (x.split("-")[0], int(x.split("-S")[1]))):
            by_ep.setdefault(sid.split("-")[0], []).append(sid.split("-")[1])
        print(f"PENDING_REDO {len(pending)} 镜（导入 {import_at} 后出图未跟上，L-088 全量重做补；新首帧设为当前后自动转回比对）：" +
              "；".join(f"{e} {','.join(v)}" for e, v in by_ep.items()))
    if overdue:
        print(f"PENDING_OVERDUE 过期待重做 {len(overdue)} 镜：导入后已 {age_h} 小时（上限 {max_h:g} 小时，config/data_parity.json），"
              f"已写报警 {PENDING_ALERT_ID} → data/qa/alerts.jsonl：{','.join(overdue)}")
    print(f"{'PASS' if not fails else 'FAIL'} data_parity：项目 {project} · 抽查 {checked['shots']} 镜 · {checked['fields']} 项 · "
          f"不一致 {len(fails)} · 待重做 {len(pending)}（过期 {len(overdue)}） · 警告 {len(warns)}{' · ' + ui_note if ui_note else ''}")
    return 0 if not fails else 1


def ui_check(ep: int, ash: list | None, fails: list[str]) -> str:
    """剧本页第 ep 集：每行人物小卡（名字 + 造型字母）= 接口 characters"""
    if not ash:
        fails.append(f"D-UI ep{ep:02d} 没有接口数据，无法比对")
        return "UI 未测"
    probe = ROOT / "apps" / "web" / "e2e" / "dataalign" / "probe.mjs"
    rows_js = ROOT / "apps" / "web" / "e2e" / "dataalign" / "rows.js"
    name = f"parity_ep{ep:02d}"
    try:
        subprocess.run(["node", str(probe), f"/#/script-create?run=series10_v1&ep={ep}", name, "14000", str(rows_js)],
                       cwd=ROOT, timeout=180, capture_output=True, check=False)
        d = json.loads((probe.parent / f"{name}.json").read_text(encoding="utf-8"))
    except Exception as ex:  # noqa: BLE001
        fails.append(f"D-UI ep{ep:02d} 截图探针失败：{ex}")
        return "UI 未测"
    rows = (d.get("result") or {}).get("rows") or []
    if len(rows) != len(ash):
        fails.append(f"D-UI ep{ep:02d} 页面 {len(rows)} 行 ≠ 接口 {len(ash)} 镜")
    for r, s in zip(rows, ash):
        got = [(p.get("name"), p.get("letter")) for p in r.get("people") or []]
        want = [(c["name"], c.get("look_label") or ("?" if c.get("cast_source") else "A")) for c in s.get("characters") or []]
        if got != want:
            fails.append(f"D-UI {s['id']} 页面人物小卡={got} ≠ 接口={want}")
    return f"UI ep{ep:02d} {len(rows)} 行已比对（截图 apps/web/e2e/dataalign/{name}.png）"


if __name__ == "__main__":
    sys.exit(main())
