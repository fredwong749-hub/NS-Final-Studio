"""VOICE10 试听页：series10 每位角色抽一句台词，用 config/voices.json 现配的音色合成，供 AUDIT 技术复核（CER / 峰值 / 采样率 / 音色一致）和项目方自己选听。

抽句规则（机械，不评价内容）：按剧本顺序，每个角色取第一句可读字数 ≥ 6 的对白（tts_text 清洗后），台词原文不改。
合成走与成片同一条路径：ns_post.tts.voice_for + synthesize_cached（克隆音色经 RoutedTts → RemoteCloneBackend，gpu36）。
回听：SenseVoice 本机 CER（ns_post.tts.char_error_rate）。只出试听，不改 voices.json。

    python tools/voice10/audition.py [--out data/review_pages/voice10_audition]
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.speakers import resolve_episode  # noqa: E402
from ns_post.tts import (KokoroBackend, SenseVoiceAsr, char_error_rate, load_voice_config, normalize,  # noqa: E402
                         synthesize_cached, voice_for, wav_duration)

CAST = ["lin_wan", "gu_chen", "chen_yu", "ch_a_lan"]


def pick_lines(script: dict, cfg: dict) -> list[dict]:
    got: dict[str, dict] = {}
    for ep in script["episodes"]:
        for ln in resolve_episode(ep, cfg.get("line_overrides") or {}):
            if ln.kind != "dialogue" or ln.speaker in got or ln.speaker not in CAST:
                continue
            if len(normalize(ln.text)) >= 6:
                got[ln.speaker] = {"speaker": ln.speaker, "ep": int(ep["number"]), "key": ln.key, "text": ln.text,
                                   "raw": ln.raw, "note": ln.note}
    return [got[c] for c in CAST if c in got]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/review_pages/voice10_audition")
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    cfg = load_voice_config()
    script = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    lines = pick_lines(script, cfg)
    reqs = [(l["text"], voice_for(cfg, l["speaker"])[0]) for l in lines]
    t0 = time.time()
    paths = synthesize_cached(KokoroBackend(cfg), reqs)
    synth_s = round(time.time() - t0, 1)
    asr = SenseVoiceAsr(cfg).transcribe(paths)
    rows = []
    for l, p, hyp in zip(lines, paths, asr):
        c = cfg["characters"][l["speaker"]]
        dst = out / f"{l['speaker']}_ep{l['ep']:02d}_{l['key'].replace('#', '_')}.wav"
        shutil.copy2(p, dst)
        rows.append({**l, "name": c.get("name"), "voice": c.get("voice"), "engine": c.get("engine"),
                     "file": dst.name, "cache": str(p.relative_to(ROOT)), "dur_s": round(wav_duration(dst), 2),
                     "asr": hyp, "cer": round(char_error_rate(l["text"], hyp), 3)})
    meta = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "synth_s": synth_s, "voices_json_series": cfg.get("series"),
            "rows": rows}
    (out / "audition.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    tr = "\n".join(
        f"<tr><td>{html.escape(r['name'])}<br><small>{html.escape(r['voice'])}（{r['engine']}）</small></td>"
        f"<td>ep{r['ep']:02d} {html.escape(r['key'])}<br><small>{html.escape(r['note'])}</small></td>"
        f"<td>{html.escape(r['text'])}</td><td><audio controls preload=none src=\"{r['file']}\"></audio></td>"
        f"<td>{r['dur_s']} s</td><td>{r['cer']}<br><small>{html.escape(r['asr'])}</small></td></tr>" for r in rows)
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>series10 音色试听</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;margin:16px;background:#fff;color:#111}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}small{{color:#666}}audio{{width:240px}}</style>
<h1>series10 音色试听（VOICE10）</h1>
<p>每位角色按剧本顺序抽第一句可读字数 ≥ 6 的对白（机械规则，台词原文不改），用 config/voices.json 现配音色合成
（与成片同一路径：synthesize_cached → gpu36 Fun-CosyVoice3 复刻）。回听 = 本机 SenseVoice。生成于 {meta['at']}，
合成耗时 {synth_s} s（含缓存命中）。音色由系统按 L-078 自动选，本页供项目方选听；技术复核见 audition.json。</p>
<table><tr><th>角色 / 音色</th><th>出处</th><th>台词（剧本原文清洗后）</th><th>试听</th><th>时长</th><th>回听 CER / ASR</th></tr>
{tr}</table>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps({"out": str(out / "index.html"), "rows": [(r["name"], r["key"], r["cer"], r["dur_s"]) for r in rows],
                      "synth_s": synth_s}, ensure_ascii=False))


if __name__ == "__main__":
    main()
