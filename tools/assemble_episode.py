"""
成集装配（T38）：6 段镜头视频 + TTS 配音（对白/独白🎙）+ H3 声音设计（或 gpu3 分轨 SN/audio/stems.json）
+ 背景音乐（data/music/epXX.wav + epXX.json 提示点）→ data/episodes/epXX_final.mp4（1080×1920；epXX.mp4 为硬链接别名；gpu3 4K 阶段从 _final 取音轨）、epXX_4k.mp4（有 4K 片段时）
+ 时间线 epXX.timeline.json。

    uv run python tools/assemble_episode.py ep01                 # 装配 ep01（缺视频的镜头用当前首帧静帧占位）
    uv run python tools/assemble_episode.py ep01 ep02 --no-asr   # 不做 SenseVoice 回听检查
    uv run python tools/assemble_episode.py ep01 --lines-only    # 只列出每句台词的说话人和音色，不合成
    uv run python tools/assemble_episode.py ep01 --tts-only      # 只合成配音（缓存到 data/cache/tts/）
    uv run python tools/assemble_episode.py ep01                 # 默认逐镜校色到本镜定稿首/尾帧（<clip>_cc.mp4；config/render_quality.json post.color_match，可按集关）
    uv run python tools/assemble_episode.py ep01 --no-color-match # 这次不校色（--color-match 强制开）
    uv run python tools/assemble_episode.py ep02 --upscale-4k print   # 只打印 gpu3 upscale_4k.py 的命令（不跑）
    uv run python tools/assemble_episode.py ep02 --upscale-4k run     # 先在 gpu3 逐镜出 4K（<clip>_4k.mp4）再装配（占 gpu3，需显式要求）
    # AUD：对白用 H3 原声（嘴型同步），TTS 只做独白 + 回听不合格的兜底；用现有时间线的同一批 take 出对照版
    uv run python tools/assemble_episode.py ep02 --dialogue-source h3 --sources-from data/episodes/ep02.timeline.json --variant H3原声

规则：只用 CPU（Kokoro/SenseVoice 走 sherpa-onnx CPU，x264 软件编码）；不读写 GPU；不改 data/renders、
data/renders_gpu3（只读）；不加字幕；1080×1920、24 fps、H.264、响度 -14 LUFS。
音色在 config/voices.json（每个角色一个固定合成音色）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.assemble import Settings, assemble_episode, load_episode  # noqa: E402
from ns_post.speakers import resolve_episode  # noqa: E402
from ns_post.tts import (FakeTts, KokoroBackend, SenseVoiceAsr, load_voice_config, synthesize_cached,  # noqa: E402
                         voice_for)


def _ep(s: str) -> int:
    m = re.fullmatch(r"(?:ep)?0*(\d+)", s.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"not an episode: {s}")
    return int(m.group(1))


def _sources_from(timeline: Path) -> dict[int, dict]:
    """AUD：按已有 timeline.json 的 shots[].file / file_4k 复现同一批 take（相对路径按项目根解析）。"""
    tl = json.loads(timeline.read_text(encoding="utf-8"))
    out = {}
    for sh in tl["shots"]:
        if sh.get("kind") == "still" and sh.get("file"):
            # FIX-VID D8：night 给没出片的镜（阻断 / 过期 / 等闸门）的首帧静帧占位 → 合成器缓推（PLACEHOLDER_PUSH），时间线标 missing
            p = Path(sh["file"]) if Path(sh["file"]).is_absolute() else ROOT / sh["file"]
            if p.is_file():
                out[int(sh["index"])] = {"kind": "still", "origin": sh.get("origin"), "path": str(p),
                                         "missing": True, "missing_reason": sh.get("origin") or "没有合格视频版本"}
            continue
        if sh.get("kind") != "video" or not sh.get("file"):
            continue
        p = Path(sh["file"]) if Path(sh["file"]).is_absolute() else ROOT / sh["file"]
        p4 = sh.get("file_4k")
        p4 = (Path(p4) if Path(p4).is_absolute() else ROOT / p4) if p4 else None
        if not p.is_file():
            raise SystemExit(f"--sources-from: {p} 不存在")
        out[int(sh["index"])] = {"kind": "video", "origin": sh.get("origin"), "path": p,
                                 "path_4k": p4 if p4 and p4.is_file() else None}
    return out


def guard_asset_pack_run() -> str | None:
    """OVERSIGHT-F 第 14 轮：本工具是 V1 的手动合成（--script 指定导入稿、配乐 / 音色走 V1 默认）。当前剧是资产包模式（V2）
    → 返回拒绝原因（main 退出 2），提示改用 tools/assemble_series.py（按剧取导入稿 / 配乐 / 音色）"""
    from ns_post import run_media as RM
    from ns_post.tts import _current_run
    run = _current_run()
    if RM.is_asset_pack_run(run, ROOT):
        return (f"当前剧 {run} 是资产包模式（V2）：tools/assemble_episode.py 只给 V1 用，"
                f"请改用 tools/assemble_series.py（按剧取导入稿、配乐曲库 config/music_v2.json、音色 config/voices_v2.json）")
    return None


def resolve_run_inputs(run: str, a) -> str | None:
    """W16 / REVIEW-G4b P0-1：显式 --run 时按剧解析输入（C-14，不写 V1/V2 分支）：导入稿 = runs.script_path(run)、
    音色 = load_voice_config(run=run)（资产包剧只认 voices_v2.json）、配乐 = run_media.music_dir(run)。
    资产包剧的画面只认 --sources-from（night 由 producer→takes.json 汇成的 manifest 生成，L-151 一本账）；
    没给 → 返回拒绝原因（find_source 只认 V1 data/renders，不能拿来顶）。就地改 a，返回 None = 可以合成"""
    from ns_post import run_media as RM
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.autopilot import runs as RUNS
    pack = RM.is_asset_pack_run(run, ROOT)
    if pack and not a.sources_from:
        return f"剧 {run} 是资产包模式：--run 合成必须给 --sources-from（按 takes.json 汇出的时间轴），不按 V1 data/renders 找片"
    if a.script is None:
        a.script = str(RUNS.script_path(run, ROOT))
    if a.music_dir is None and not a.no_bgm and pack:
        a.music_dir = str(RM.music_dir(run, ROOT))
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episodes", nargs="+", type=_ep)
    ap.add_argument("--run", default=None,
                    help="按剧合成（导入稿 / 音色 / 配乐按剧取；night.py 传 --run）；不给 = 旧行为，当前剧是资产包模式时拒绝")
    ap.add_argument("--script", default=None, help="导入稿（默认：按剧取 runs.script_path；--run 给了用该剧，否则当前剧）")
    ap.add_argument("--out", default=str(ROOT / "data" / "episodes"))
    ap.add_argument("--no-asr", action="store_true", help="skip the SenseVoice round-trip check")
    ap.add_argument("--fake-tts", action="store_true", help="tones instead of speech (pipeline test)")
    ap.add_argument("--lines-only", action="store_true")
    ap.add_argument("--tts-only", action="store_true")
    ap.add_argument("--threads", type=int, default=4, help="CPU threads for TTS/ASR")
    ap.add_argument("--x264-threads", type=int, default=8)
    ap.add_argument("--lufs", type=float, default=-14.0)
    ap.add_argument("--h3-gain-db", type=float, default=-3.0, help="H3 sound-design bed level")
    ap.add_argument("--allow-laptop-video", action="store_true",
                    help="use data/renders videos when gpu3 has none (default: placeholder stills; rule 7)")
    ap.add_argument("--no-bgm", action="store_true", help="skip the data/music/epXX BGM layer")
    ap.add_argument("--music-dir", default=None,
                    help="BGM10：配乐目录（默认 data/music = 旧剧；series10 用 data/music/series10，tools/bgm/agent.py 产出）")
    ap.add_argument("--4k", dest="uhd", choices=("auto", "on", "off"), default="auto",
                    help="2160x3840 delivery: auto = when any gpu3 takes/video_NNN_4k.mp4 exists")
    ap.add_argument("--color-match", action=argparse.BooleanOptionalAction, default=None,
                    help="per-shot colour correction to the locked keyframes (<clip>_cc.mp4); default = "
                         "config/render_quality.json post.color_match (on, per_episode switch)")
    ap.add_argument("--upscale-4k", choices=("off", "print", "run"), default="off",
                    help="optional gpu3 SeedVR2 4K per clip (scripts/upscale_4k.py shot): print the commands or run them")
    ap.add_argument("--keep-work", action="store_true")
    # AUD（2026-10-31）
    ap.add_argument("--dialogue-source", choices=("tts", "h3"), default=None,
                    help="对白来源：tts = 现状；h3 = H3 原声（嘴型同步），TTS 只做独白和回听不合格的兜底；"
                         "默认 = config/render_quality.json post.dialogue_source")
    ap.add_argument("--h3-max-cer", type=float, default=0.35, help="H3 原声回听 CER 上限，超过即该镜 TTS 兜底")
    ap.add_argument("--vo-max-tempo", type=float, default=1.0,
                    help="独白放不下本镜时最多提速到 ×N（1.0 = 不提速，现状）")
    ap.add_argument("--h3-music", choices=("keep", "duck_under_bgm"), default=None,
                    help="H3 自带配乐：keep = 现状；duck_under_bgm = BGM 全程铺，H3 轨在无对白处压 --h3-music-duck-db；"
                         "默认 = config/render_quality.json post.h3_music.default（FIX 2026-10-31 接上）")
    ap.add_argument("--h3-music-duck-db", type=float, default=None,
                    help="默认 = config/render_quality.json post.h3_music.duck_db")
    # FIX（ep02_iter v0）合成硬规则：默认全部读 config/render_quality.json post.edit_rules；这里只给对照用的开关
    ap.add_argument("--take-policy", choices=("locked_qc", "active_legacy"), default=None,
                    help="locked_qc（默认）= 只用定稿且运动质检不是 fail 的版本，没有就标缺；active_legacy = 旧行为（对照）")
    ap.add_argument("--skin-guard", dest="skin_guard", action="store_true", default=None)
    ap.add_argument("--no-skin-guard", dest="skin_guard", action="store_false")
    ap.add_argument("--variant", default="", help="对照版后缀：<stem>_<variant>.mp4 / .timeline.json，不覆盖原版")
    ap.add_argument("--sources-from", default=None,
                    help="用这份 timeline.json 里每镜的 file / file_4k（同一批 take），不按 takes.json 当前版本找")
    a = ap.parse_args()
    why = resolve_run_inputs(a.run, a) if a.run else guard_asset_pack_run()
    if why:
        print(why, file=sys.stderr)
        return 2
    if a.script is None:   # 没给 --run：当前剧（guard 已保证不是资产包剧）的导入稿，按 runs.script_path 取（不写死路径）
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.autopilot import runs as RUNS
        a.script = str(RUNS.script_path(None, ROOT))

    cfg = load_voice_config(run=a.run) if a.run else load_voice_config()
    tts = FakeTts() if a.fake_tts else KokoroBackend(cfg, num_threads=a.threads)
    asr = None if (a.no_asr or a.fake_tts) else SenseVoiceAsr(cfg, num_threads=a.threads)
    settings = Settings(threads=a.x264_threads, target_lufs=a.lufs, h3_gain_db=a.h3_gain_db, bgm=not a.no_bgm,
                        deliver_4k=a.uhd, color_match=a.color_match, dialogue_source=a.dialogue_source,
                        h3_max_cer=a.h3_max_cer, vo_max_tempo=a.vo_max_tempo, h3_music=a.h3_music,
                        h3_music_duck_db=a.h3_music_duck_db, take_policy=a.take_policy, skin_guard=a.skin_guard,
                        music_dir=a.music_dir)
    sources = _sources_from(Path(a.sources_from)) if a.sources_from else None
    for ep in a.episodes:
        episode = load_episode(Path(a.script), ep)
        if a.lines_only or a.tts_only:
            if a.run:   # W16：按剧的说话人表 / 旁白（与 ns_post.assemble 合成路径同口径）
                from ns_post.speakers import Cast
                from ns_post.tts import default_voiceover_speaker
                lines = resolve_episode(episode, cfg.get("line_overrides"), narrator=default_voiceover_speaker(cfg),
                                        cast=Cast.from_cfg(cfg))
            else:
                lines = resolve_episode(episode, cfg.get("line_overrides"))
            for ln in lines:
                vs = voice_for(cfg, ln.speaker, voiceover=ln.kind == "voiceover")
                print(f"ep{ep:02d}-{ln.key:7} {ln.kind:9} {ln.speaker:12} "
                      f"{','.join(f'{v.name}/sid{v.sid}' for v in vs):22} {ln.text}   [{ln.how}]")
            if a.tts_only:
                reqs = [(ln.text, v) for ln in lines for v in voice_for(cfg, ln.speaker,
                                                                          voiceover=ln.kind == "voiceover")]
                paths = synthesize_cached(tts, reqs)
                print(f"{len(paths)} clips in data/cache/tts/")
            continue
        if a.upscale_4k != "off":
            from ns_post.assemble import find_source
            from ns_post.upscale4k import upscale
            for shot in episode["shots"]:
                src = find_source(ep, int(shot["index"]), allow_laptop_video=a.allow_laptop_video)
                if src["kind"] == "video" and not src.get("path_4k"):
                    upscale(Path(src["path"]), ep, int(shot["index"]), execute=a.upscale_4k == "run")
        tl = assemble_episode(episode, Path(a.out), tts=tts, asr=asr, settings=settings, voices_cfg=cfg,
                              allow_laptop_video=a.allow_laptop_video, keep_work=a.keep_work, sources=sources,
                              variant=a.variant)
        print(json.dumps({k: tl[k] for k in ("deliveries", "duration_s", "tail_hold_s", "timings")},
                         ensure_ascii=False, indent=1))
        print("loudness:", tl["loudness"]["measured"], "| bgm:", tl["bgm"].get("file") or tl["bgm"].get("reason"))
        print("shots:", ", ".join(f"S{s['index']}={s['kind']}/{s.get('audio')}" for s in tl["shots"]))
        print(f"{len(tl['speech'])} spoken lines, {len(tl['warnings'])} warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
