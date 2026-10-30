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


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episodes", nargs="+", type=_ep)
    ap.add_argument("--script", default=str(ROOT / "data" / "import" / "script_v2.json"))
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
    ap.add_argument("--4k", dest="uhd", choices=("auto", "on", "off"), default="auto",
                    help="2160x3840 delivery: auto = when any gpu3 takes/video_NNN_4k.mp4 exists")
    ap.add_argument("--color-match", action=argparse.BooleanOptionalAction, default=None,
                    help="per-shot colour correction to the locked keyframes (<clip>_cc.mp4); default = "
                         "config/render_quality.json post.color_match (on, per_episode switch)")
    ap.add_argument("--upscale-4k", choices=("off", "print", "run"), default="off",
                    help="optional gpu3 SeedVR2 4K per clip (scripts/upscale_4k.py shot): print the commands or run them")
    ap.add_argument("--keep-work", action="store_true")
    a = ap.parse_args()

    cfg = load_voice_config()
    tts = FakeTts() if a.fake_tts else KokoroBackend(cfg, num_threads=a.threads)
    asr = None if (a.no_asr or a.fake_tts) else SenseVoiceAsr(cfg, num_threads=a.threads)
    settings = Settings(threads=a.x264_threads, target_lufs=a.lufs, h3_gain_db=a.h3_gain_db, bgm=not a.no_bgm,
                        deliver_4k=a.uhd, color_match=a.color_match)
    for ep in a.episodes:
        episode = load_episode(Path(a.script), ep)
        if a.lines_only or a.tts_only:
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
                              allow_laptop_video=a.allow_laptop_video, keep_work=a.keep_work)
        print(json.dumps({k: tl[k] for k in ("deliveries", "duration_s", "tail_hold_s", "timings")},
                         ensure_ascii=False, indent=1))
        print("loudness:", tl["loudness"]["measured"], "| bgm:", tl["bgm"].get("file") or tl["bgm"].get("reason"))
        print("shots:", ", ".join(f"S{s['index']}={s['kind']}/{s.get('audio')}" for s in tl["shots"]))
        print(f"{len(tl['speech'])} spoken lines, {len(tl['warnings'])} warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
