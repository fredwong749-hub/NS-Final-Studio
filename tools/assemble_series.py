"""ASSEMBLY（FOCUS 第 6 条，2026-11-02）：series10 任意一集一键装配（成片 v 版 / 整集“当前最新预览”）。

    .venv/Scripts/python.exe tools/assemble_series.py ep01            # 成片版 → data/renders/ep01/_final/ep01_v1.mp4（尽力版当占位）
    .venv/Scripts/python.exe tools/assemble_series.py ep02 --variant v2 --no-pull
    .venv/Scripts/python.exe tools/assemble_series.py ep01 --preview  # 当前最新预览 → _final/preview_latest.mp4（尽力版也放进去）
    .venv/Scripts/python.exe tools/assemble_series.py --all --preview # 10 集都拼一遍
    .venv/Scripts/python.exe tools/assemble_series.py --sweep         # 巡检：哪集有新定稿 / 首帧换版就重拼（同集 10 分钟内最多一次）；
                                                                      # infra_watchdog 每拍调 sweep()，不另起守护进程

做什么：
 1. 读负责该集的服务器 state_<host>.json（经 tools/netfix/rssh，只读，不占出图卡）→ 每镜入选版本；
 2. 状态 done 的镜 = 视频（本机没有就拉原片）；preview 模式下 best_effort 也是视频（manifest 标 best_effort）；
    其余镜 = 首帧静帧缓推占位（首帧取 state 里最新的，没有就取本机 images/frames 最新一张，再没有 = 黑场）；
 3. 走 ns_post 同一条后期链：配音 = TTS 缓存 / H3 原声，BGM = 集级一条（data/music/series10/epNN.wav，L-118，
    剪辑锁定后再重配），转场 = 规则化（同场硬切 + J-cut，assemble.py 内置），响度 -14 LUFS；
 4. 字幕：硬规则“不烧字幕”（L-002 / ffmpeg.NO_SUBTITLES），只出外挂 .srt；
 5. 产物 _final/：成片版 epNN_<v>.mp4 + .timeline.json + .srt + _manifest.json；预览版 preview_latest.mp4 + .srt + _manifest.json
    （manifest.signature = 每镜入选来源的指纹，和当前 state 指纹不同 = 预览过期）。预览只是看效果，不是交付。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.autopilot import runs as RUNS  # noqa: E402
from tools.factory import hosts as HOSTS  # noqa: E402
from tools.netfix import rssh as RSSH  # noqa: E402

RUN_ID = RUNS.primary_run()
RUN_REL = f"data/pipeline/runs/{RUN_ID}"
RUN = ROOT / RUN_REL
VID = RUN / "video"
SWEEP_STATE = ROOT / "data/state/preview_sweep.json"
BUILD_LOCK = ROOT / "data/state/preview_build.lock"
MIN_GAP_S = 600          # 同一集预览两次重拼的最小间隔（防抖）
EST_BUILD_S = 150        # “约 N 分钟”的估计（实测 ep01 约 2 分钟）
N_EPS = 10


def rsh(host: str, cmd: str, out: Path | None = None) -> bytes:
    r = RSSH.run_retry(host, cmd, timeout=900)   # 统一远程命令入口（tools/netfix/rssh.py）
    if r.returncode != 0:
        raise RuntimeError(f"rsh {host} rc={r.returncode}: {(r.stderr or b'')[-200:]!r}")
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_bytes(r.stdout)
        os.replace(tmp, out)
    return r.stdout


def srv(host: str) -> str:
    return HOSTS._host(host)["video_root"]


def pull(host: str, rel: str) -> Path:
    dst = ROOT / rel
    if not dst.is_file() or dst.stat().st_size == 0:
        rsh(host, f"cat {srv(host)}/{rel}", dst)
    return dst


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def read_json(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def host_of(ep: int) -> str | None:
    """W41：没派过视频的剧（V2 ep01 11-04）没有 hosts.json → None（不拉片），以前 FileNotFoundError 整集预览拼不出"""
    d = read_json(VID / "hosts.json", None)
    return (d or {}).get(str(ep))


def refresh_state(host: str) -> dict:
    """拉服务器 state；通道抖动时 cat 可能 rc=0 但内容为空 / 截断（11-02 ep03 / ep05 被误拼成 0 条视频的根因）→ 解析不过就抛，
    不覆盖本机上一份好的"""
    p = VID / f"state_{host}.json"
    raw = rsh(host, f"cat {srv(host)}/{RUN_REL}/video/state_{host}.json")
    try:
        shots = json.loads(raw.decode("utf-8"))["shots"]
    except (ValueError, KeyError) as e:
        raise RuntimeError(f"state_{host}.json 拉回来不完整（{len(raw)} 字节）") from e
    tmp = p.with_suffix(".json.tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    return shots


def local_state(host: str) -> dict:
    return read_json(VID / f"state_{host}.json", {}).get("shots", {})


RECIPE_ZH = {"i2va_pika_flex": "皮卡出片", "i2va_pdd2": "旧版出片"}   # 来源行用大白话；配方名 / seed 收进 origin_detail
RANK = {"done": 4, "best_effort": 3, "rendering": 2, "pending": 1}


def hosts_all() -> list[str]:
    """W41：没有 hosts.json（还没派过视频）= 没有服务器 state 可读 → []（每镜走首帧占位），不抛"""
    return sorted(set((read_json(VID / "hosts.json", None) or {}).values()))


def merged_state(refresh: bool = True) -> dict:
    """两台服务器的 state 合并：同一镜两边都有记录时取进度更靠前的那台（done > best_effort > rendering > pending > 其它）。
    hosts.json 的“集→机”是出片分工，出片机会中途换（11-02 ep07 / ep09 改到 gpu33），不能只信它；每条记 _host 供取片"""
    out: dict = {}
    for h in hosts_all():
        try:
            st = refresh_state(h) if refresh else local_state(h)
        except Exception:  # noqa: BLE001 — 连不上就用本机上次拉回的
            st = local_state(h)
        for k, v in st.items():
            if k not in out or RANK.get(v.get("status"), 0) > RANK.get(out[k].get("status"), 0):
                out[k] = dict(v, _host=h)
    return out


def plan(ep: int, state: dict, *, best_effort_video: bool) -> list[dict]:
    """每镜入选来源（纯读 state，不拉文件）：kind = video | best_effort | placeholder，file = 视频或首帧相对路径"""
    script = json.loads(RUNS.script_path(RUN_ID, ROOT).read_text(encoding="utf-8"))   # OVERSIGHT-F P1-4：按剧取导入稿（K-OPS-F24）
    ep_shots = next(e for e in script["episodes"] if int(e["number"]) == ep)["shots"]
    name = f"ep{ep:02d}"
    out = []
    for sh in ep_shots:
        idx = int(sh["index"])
        key = f"{name}-S{idx}"
        s = state.get(key) or {}
        status, chosen = s.get("status"), s.get("chosen")
        r = next((x for x in s.get("renders", []) if x.get("variant") == chosen and x.get("file")), None)
        row = {"shot": key, "index": idx, "state": status, "chosen": chosen, "host": s.get("_host")}
        if r and (status == "done" or (best_effort_video and status == "best_effort")):
            n = [x.get("variant") for x in s.get("renders", []) if x.get("file")].index(chosen) + 1
            row.update(kind="video" if status == "done" else "best_effort", file=r["file"],
                       verdict=(r.get("score") or {}).get("verdict"), recipe=r.get("recipe"), seed=r.get("seed"),
                       version_no=n, origin=f"{RECIPE_ZH.get(r.get('recipe'), '出片')} · 第 {n} 版",
                       origin_detail=f"{r.get('recipe')} · 变体 {chosen} · seed {r.get('seed')}")
        elif own_active_video(key):   # W46：视频不经 vidgen state（W38 直推 / register_takes 已登记）→ 本剧 takes.json 当前视频
            v, n = own_active_video(key)
            row.update(kind="video", file=v, version_no=n, origin=f"takes.json 当前视频 · 第 {n} 版", origin_detail=f"active.video={n}")
        else:
            ff = next((x.get("first_frame") for x in reversed(s.get("renders", [])) if x.get("first_frame")), None)
            if not ff:   # W41：state 里没有首帧 → 本剧 takes.json 当前首帧（只认本剧渲染前缀，C-14）
                ff = own_active_first(key)
            if not ff:   # 再没有 → 本机 images/frames 最新一张
                c = sorted((RUN / "images/frames" / name).glob(f"{key}_*.png"))   # 兜底：按文件名取最后一张（不猜 mtime）
                ff = str(c[-1].relative_to(ROOT)).replace("\\", "/") if c else None
            row.update(kind="placeholder", file=ff, reason=f"state={status}，没有可用视频" if status else "还没有任何记录")
        out.append(row)
    return out


def own_active_first(sid: str, stage: str = "image") -> str | None:
    """本剧 takes.json 的当前首帧（data/ 下相对路径 → 仓库相对 data/...）；文件不在本剧前缀 renders/<剧>/ 下 = 不用（跨剧版本）"""
    ep, s = sid.split("-")
    rd = RUNS.renders_dir(RUN_ID, ROOT)
    d = read_json(rd / ep / s / "takes.json", {}) or {}
    n = (d.get("active") or {}).get(stage)
    t = next((x for x in d.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
    if not t or not t.get("file"):
        return None
    prefix = str(rd.relative_to(ROOT / "data")).replace("\\", "/").rstrip("/") + "/"
    f = str(t["file"]).replace("\\", "/")
    if not f.startswith(prefix) or not (ROOT / "data" / f).is_file():
        return None
    return "data/" + f


def _trim_le6(p: Path) -> Path:
    """W46（总调度 05:1x）：单镜视频进合成前裁到 ≤ 6.0 s（C-08，tools/series10_video/clip_trim.py，与 night finalize 同一份）；裁失败 = 用原片"""
    import importlib.util as u
    try:
        sp = u.spec_from_file_location("clip_trim_as", ROOT / "tools/series10_video/clip_trim.py")
        m = u.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m.trim_le(p)
    except Exception as e:  # noqa: BLE001  # arch-ok: 预览合成不因裁剪失败中断；成片层由 night 硬规矩 C-08 挡
        print(f"WARN 裁到 6 s 失败（用原片）：{p.name}：{e!r}"[:300], file=sys.stderr)
        return p


def _relp(p: Path) -> str:
    """仓库相对路径；--out-dir 在仓库外（沙箱 / 试跑）就给绝对路径（原来 relative_to 直接 ValueError，W46 实测）"""
    p = Path(p).resolve()
    try:
        return str(p.relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def own_active_video(sid: str) -> tuple[str, int] | None:
    """W46：本剧 takes.json active.video（只认本剧前缀、文件在）→ (仓库相对路径, 版本号)"""
    f = own_active_first(sid, "video")
    if not f:
        return None
    ep, s = sid.split("-")
    d = read_json(RUNS.renders_dir(RUN_ID, ROOT) / ep / s / "takes.json", {}) or {}
    return f, int((d.get("active") or {}).get("video") or 0)


def label_still(path: Path, text: str, sub: str = "PREVIEW PLACEHOLDER") -> Path:
    """W46 部分预览：缺视频的镜 = 黑场 + 镜号字样（总调度 04:2x 令；只给预览，不进成片）。1080×1920 PNG"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1080, 1920), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    try:
        big, small = ImageFont.load_default(size=150), ImageFont.load_default(size=48)
    except TypeError:          # Pillow < 10.1：load_default 不收 size
        big = small = ImageFont.load_default()
    for t, f, y in ((text, big, 820), (sub, small, 1010)):
        w = dr.textbbox((0, 0), t, font=f)[2]
        dr.text(((1080 - w) // 2, y), t, fill=(200, 200, 200), font=f)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def signature(rows: list[dict]) -> str:
    return hashlib.sha1(json.dumps([(r["shot"], r["kind"], r.get("file")) for r in rows]).encode()).hexdigest()[:16]


def compose(ep: int, sources: dict, work: Path, variant: str, *, preview: bool = False, cut_edit: dict | None = None,
            dialogue_source: str = "h3", bgm: bool = True, cache_dir: Path | None = None, run: str | None = None) -> tuple[dict, int]:
    """配音 + 配乐 + 转场 + 响度的唯一合成入口（assemble_series 预览 / 成片版和 CUTEDIT 的 cut_export 共用，11-02 对齐）。
    sources = {镜号: {kind: video|still|black, path, origin, ...}}；cut_edit = cut_project 归一后的覆写（None = 不变）；
    preview=True：不叫远程克隆 TTS（会在服务器上排队等空闲卡），没缓存的克隆音色句子用本机 Kokoro 临时音顶，
    只写 data/cache/tts_preview 临时缓存，不污染正式缓存。返回 (timeline, 临时音句数)"""
    sys.path.insert(0, str(ROOT / "services/post"))
    from ns_post.assemble import Settings, assemble_episode, load_episode  # noqa: E402
    from ns_post.tts import KokoroBackend, RoutedTts, SenseVoiceAsr, Voice, load_voice_config  # noqa: E402

    from ns_post import run_media as RM  # noqa: E402  OVERSIGHT-F P1-13a：配乐 / 音色按剧取（V2 只认 music_v2.json / voices_v2.json）
    run = run or RUN_ID
    cfg = load_voice_config(run=run)
    try:
        mdir = RM.music_dir(run, ROOT)
        RM.check_episode_music(run, ep, mdir, ((cut_edit or {}).get("bgm") or {}).get("file"), ROOT)
    except RM.V2MediaError:
        if bgm:
            raise
        mdir = ROOT / "data/music" / run     # W46：不配乐（--no-bgm）时曲库缺 / 校验不过不挡合成（服务器没有 data/music/v2_style）
    kokoro = KokoroBackend(cfg, num_threads=4)
    tts, cache_dir, n_cached = kokoro, Path(cache_dir or ROOT / "data/cache/tts"), 0
    if preview:
        main = ROOT / "data/cache/tts"
        cache_dir = ROOT / "data/cache/tts_preview"
        shutil.rmtree(cache_dir, ignore_errors=True)   # 自己的临时缓存目录，每次重建
        shutil.copytree(main, cache_dir) if main.is_dir() else cache_dir.mkdir(parents=True)
        n_cached = len(list(cache_dir.glob("*.wav")))

        class _FallbackTts:
            name = "kokoro-preview-fallback"

            def synthesize(self, items):
                for text, v, path in items:
                    male = (cfg["characters"].get(v.speaker) or {}).get("gender") == "male"
                    kokoro.synthesize([(text, Voice(v.speaker, 58 if male else 3, "", v.speed), path)])
        tts = RoutedTts(kokoro, cfg, remote=_FallbackTts())
    settings = Settings(threads=8, bgm=bgm, deliver_4k="off", dialogue_source=dialogue_source,
                        music_dir=str(mdir))
    episode = load_episode(RUNS.script_path(run, ROOT), ep)   # OVERSIGHT-F P1-4c：按剧取导入稿（成片 / 预览 / CUTEDIT 都走这里）
    tl = assemble_episode(episode, work, tts=tts, cache_dir=cache_dir, asr=SenseVoiceAsr(cfg, num_threads=4),
                          settings=settings, voices_cfg=cfg, allow_laptop_video=False,
                          keep_work=bool(os.environ.get("ASM_KEEP_WORK")), sources=sources, variant=variant,
                          cut_edit=cut_edit)
    return tl, (len(list(cache_dir.glob("*.wav"))) - n_cached if preview else 0)


def write_srt(tl: dict, path: Path) -> None:
    cues = sorted((s for s in tl["speech"] if s.get("start_s") is not None), key=lambda s: s["start_s"])
    nl = "\n"
    blocks = [f"{i}{nl}{srt_time(s['start_s'])} --> {srt_time(s['end_s'])}{nl}{s['text']}{nl}" for i, s in enumerate(cues, 1)]
    path.write_text(nl.join(blocks), encoding="utf-8")


def build(ep: int, variant: str = "v1", *, preview: bool = False, pull_on: bool = True,
          dialogue_source: str = "h3", bgm: bool = True, cut_edit: dict | None = None,
          sources: dict | None = None, out_dir: Path | None = None, partial: bool = False, out_name: str | None = None) -> dict:
    """out_dir：W41 试跑把预览写到沙箱（不写生产 _final/，免得 retro_tick 当成“整集预览已出”）。
    partial（W46，总调度 04:2x）：不等全集，缺视频的镜一律黑场 + 镜号字样（不用首帧缓推），out_name 定产物名"""
    name = f"ep{ep:02d}"
    state = merged_state(pull_on)
    rows = plan(ep, state, best_effort_video=preview)
    own_sources = sources is None
    sources = {} if own_sources else sources
    for r in rows:
        f = r.get("file")
        if f and pull_on and not (ROOT / f).is_file() and (r.get("host") or host_of(ep)):
            try:
                pull(r.get("host") or host_of(ep), f)
            except RuntimeError:
                pass
        p = ROOT / f if f else None
        if partial and r["kind"] == "placeholder":
            lab = label_still(Path(out_dir or ROOT / "data/cache") / "_labels" / f"{r['shot']}.png", r["shot"])
            r.update(file=None, reason=(r.get("reason") or "") + "；部分预览：黑场 + 镜号")
            sources[r["index"]] = {"kind": "still", "origin": "占位 · 黑场镜号（部分预览）", "path": lab, "placeholder": True}
        elif p and p.is_file():
            if r["kind"] == "placeholder":
                sources[r["index"]] = {"kind": "still", "origin": "占位 · 首帧缓推", "path": p, "placeholder": True}
            else:
                sources[r["index"]] = {"kind": "video", "origin": r["origin"],
                                       "path": _trim_le6(p), "path_4k": None}
        else:
            r.update(kind="placeholder", reason=(r.get("reason") or "文件缺失") + "；无首帧 → 黑场", file=None)
            sources[r["index"]] = {"kind": "black", "origin": None, "path": None, "missing": True,
                                   "missing_reason": r["reason"]}
    sig = signature(rows)

    out_dir = Path(out_dir) if out_dir else RUNS.renders_dir(RUN_ID, ROOT) / name / "_final"     # I-8：V2 成片写 V2 目录，不写进 V1 冻结树
    work = out_dir / "_asm"
    work.mkdir(parents=True, exist_ok=True)
    stem_var = "preview" if preview else variant
    t0 = time.time()
    tl, n_fb = compose(ep, sources, work, stem_var, preview=preview, cut_edit=cut_edit,
                       dialogue_source=dialogue_source, bgm=bgm)
    produced = ROOT / next(iter(tl["deliveries"].values()))["file"]
    base = out_name or ("preview_latest" if preview else f"{name}_{variant}")
    final = out_dir / f"{base}.mp4"
    tmp = out_dir / f"{base}.mp4.tmp"
    shutil.copyfile(produced, tmp)
    os.replace(tmp, final)
    if not preview:
        shutil.copyfile(next(iter(work.glob(f"*{variant}.timeline.json"))), out_dir / f"{name}_{variant}.timeline.json")

    write_srt(tl, out_dir / f"{base}.srt")

    by_idx = {int(s["index"]): s for s in tl["shots"]}
    for r in rows:
        t = by_idx.get(r["index"], {})
        r.update(start_s=t.get("start_s"), duration_s=t.get("duration_s"), audio=t.get("audio"))
    n_ph = sum(1 for r in rows if r["kind"] == "placeholder")
    n_be = sum(1 for r in rows if r["kind"] == "best_effort")
    manifest = {"episode": name, "variant": stem_var, "preview": preview, "built_at": time.time(),
                "built_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"), "build_s": round(time.time() - t0, 1),
                "signature": sig, "output": _relp(final),
                "srt": _relp(out_dir / f"{base}.srt"),
                "complete": n_ph == 0 and n_be == 0, "video_shots": len(rows) - n_ph - n_be,
                "best_effort_shots": n_be, "placeholder_shots": n_ph, "duration_s": tl["duration_s"],
                "bgm": tl["bgm"].get("file") or tl["bgm"].get("reason"), "loudness": tl["loudness"]["measured"],
                "tts_fallback_lines": n_fb, "subtitles": "sidecar .srt（不烧录，L-002）", "warnings": tl["warnings"], "shots": rows}
    write_json(out_dir / f"{base}_manifest.json", manifest)
    return manifest


# ---------------- 巡检（infra_watchdog 调用） ----------------

SWEEP_BREAKER_N = 3      # 逻辑纪律补丁 v3 §2e：同集连续重拼 ≥ N 次且输入指纹集合没变 → 停拼报警
SWEEP_SEEN_MAX = 8


def _alarm(ep: int, why: str) -> None:
    """熔断报警：登记卡点（data/pipeline/issues.jsonl）；登记失败只打印"""
    try:
        sys.path.insert(0, str(ROOT / "tools/master"))
        import report_issue as RI
        RI.report(run=RUN_ID, episode=int(ep), step="预览重拼熔断", who="assemble_series.sweep", what=why, blocking=False,
                  fix_hint="查两台视频 state 合并为何摇摆（state_<host>.json 拉取 / 分片合并），修好后指纹出现新值即自动解除")
    except Exception as e:  # noqa: BLE001
        print(f"[assemble_series] 熔断报警没登记上：{e!r}", file=sys.stderr)


def sweep(now: float | None = None, eps=range(1, N_EPS + 1), refresh: bool = True) -> list[int]:
    """哪集的入选来源指纹和预览 manifest 不同 → 记 sig_now（API 判过期）；距上次拼 ≥ MIN_GAP_S 且没有别的集在拼 → 重拼最多一集。
    返回本次拼了哪些集。防抖：同一集 10 分钟内最多一次；全局同一时刻只拼一集（BUILD_LOCK）"""
    now = time.time() if now is None else now
    st = read_json(SWEEP_STATE, {}) or {}
    st.setdefault("eps", {})
    try:
        merged = merged_state(refresh)
    except Exception as e:  # noqa: BLE001
        # 逻辑纪律补丁 v3 §2e：拉取失败不得用旧副本算指纹（旧副本 + 两台摇摆 = 指纹永不对齐 = 每 600 s 重拼）→ 本拍不判
        st["last_error"] = repr(e)[:200]
        st["checked_at"] = now
        write_json(SWEEP_STATE, st)
        return []
    todo = []
    for e in eps:
        rows = plan(e, merged, best_effort_video=True)
        sig = signature(rows)
        cur = read_json(RUNS.renders_dir(RUN_ID, ROOT) / f"ep{e:02d}/_final/preview_latest_manifest.json", {}) or {}
        info = st["eps"].setdefault(str(e), {})
        info["sig_now"] = sig
        info["stale"] = cur.get("signature") != sig
        info["built_at"] = cur.get("built_at")
        if info.get("breaker") and sig not in (info.get("seen_sigs") or []):
            info.pop("breaker", None)                    # 来了从没见过的新输入 → 熔断自动解除
            info["streak"] = 0
        if info.get("breaker"):
            continue
        if info["stale"] and now - float(cur.get("built_at") or 0) >= MIN_GAP_S and now - float(info.get("last_try") or 0) >= MIN_GAP_S:
            todo.append(e)
    st["checked_at"] = now
    write_json(SWEEP_STATE, st)
    built = []
    for e in todo[:1]:
        lock = read_json(BUILD_LOCK, {}) or {}
        if now - float(lock.get("t") or 0) < 1200:
            break
        write_json(BUILD_LOCK, {"t": now, "ep": e})
        st["eps"][str(e)].update(building=True, build_started=now, eta_s=EST_BUILD_S, last_try=now)
        write_json(SWEEP_STATE, st)
        info = st["eps"][str(e)]
        sig = info.get("sig_now")
        seen = list(info.get("seen_sigs") or [])
        info["streak"] = (int(info.get("streak") or 0) + 1) if sig in seen else 1   # 连续重拼且输入指纹没出现新值
        info["seen_sigs"] = (seen + ([sig] if sig not in seen else []))[-SWEEP_SEEN_MAX:]
        if info["streak"] >= SWEEP_BREAKER_N:
            info["breaker"] = True
            write_json(SWEEP_STATE, st)
            write_json(BUILD_LOCK, {"t": 0})
            _alarm(e, f"连续 {info['streak']} 次重拼，输入指纹集合没变（{sorted(set(info['seen_sigs']))[:4]}）：停拼等人查")
            break
        try:
            build(e, preview=True)
            built.append(e)
        except Exception as ex:  # noqa: BLE001
            st["eps"][str(e)]["error"] = repr(ex)[:300]
        finally:
            st["eps"][str(e)]["building"] = False
            write_json(SWEEP_STATE, st)
            write_json(BUILD_LOCK, {"t": 0})
    return built


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--preview", action="store_true", help="整集当前最新预览（尽力版也放进去）→ preview_latest.mp4")
    ap.add_argument("--variant", default="v1")
    ap.add_argument("--no-pull", action="store_true", help="不连服务器，用本机已有的 state / 片")
    ap.add_argument("--dialogue-source", default="h3", choices=("tts", "h3"))
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--out-dir", default=None, help="产物目录（默认 data/renders/<剧>/epNN/_final；试跑写沙箱用）")
    ap.add_argument("--partial", action="store_true", help="W46 部分预览：缺视频的镜 = 黑场 + 镜号字样（配 --preview --out-dir --out-name）")
    ap.add_argument("--out-name", default=None, help="产物文件名（不含 .mp4），默认 preview_latest / epNN_<v>")
    a = ap.parse_args()
    if a.sweep:
        print("built:", sweep(refresh=not a.no_pull))
        return 0
    eps = list(range(1, N_EPS + 1)) if a.all else [int(re.sub(r"\D", "", a.episode))]
    for ep in eps:
        m = build(ep, a.variant, preview=a.preview, pull_on=not a.no_pull, dialogue_source=a.dialogue_source,
                  bgm=not a.no_bgm, out_dir=Path(a.out_dir) if a.out_dir else None, partial=a.partial, out_name=a.out_name)
        print(json.dumps({"ep": ep, **{k: m[k] for k in ("output", "complete", "video_shots", "best_effort_shots",
                                                          "placeholder_shots", "duration_s")}}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
