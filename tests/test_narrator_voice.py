"""VOICE 2026-10-31：旁白音色 QAg（项目方原话“oag音色”“QAg（深夜电台·温柔）”“采取”）。

- config：narrator 角色 + voiceover_speaker；参考音频 sha256 与 config 一致；
- speakers：独白默认说话人读配置（不再写死 lin_wan），对白里的“她”仍是林晚；
- tts：narrator → 克隆引擎 Voice；RoutedTts 只把旁白送远程、Kokoro 句子留本机；RemoteCloneBackend 用 mock runner
  （不碰网络 / GPU）走完上传 → 运行 → 取回；失败时报错而不是悄悄换回旧音色。
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.speakers import resolve_episode  # noqa: E402
from ns_post.tts import (FakeTts, RemoteCloneBackend, RoutedTts, TtsError, Voice, clip_key,  # noqa: E402
                         default_voiceover_speaker, load_voice_config, synthesize_cached, voice_for, write_tone)


def _ep(vo="味道会散的。"):
    return {"number": 99, "shots": [{"index": 1, "dialogue": [{"speaker_note": "她", "text": "你好。"}],
                                     "voiceover": {"note": "林晚内心", "text": vo}}]}


def test_config_narrator_is_owner_choice_and_ref_is_pinned():
    cfg = load_voice_config()
    n = cfg["characters"]["narrator"]
    assert cfg["voiceover_speaker"] == "narrator"
    assert n["engine"] == "cosyvoice3_zs" and n["owner_decision"]["at"] == "2026-10-31"
    assert "QAg" in n["owner_decision"]["quote"]
    ref = ROOT / n["ref_wav"]
    assert hashlib.sha256(ref.read_bytes()).hexdigest() == n["ref_sha256"]
    meta = json.loads((ROOT / n["asset"]).read_text(encoding="utf-8"))
    assert meta["ref_sha256"] == n["ref_sha256"] and 8 <= meta["ref_seconds"] <= 15
    assert meta["consistency_test"]["chosen"].startswith("cosyvoice3_zs")
    # GPU0/1 是 H3 出片道，旁白只允许错峰用 GPU2
    assert cfg["remote_tts"]["gpus"] == [2]


def test_voiceover_default_reads_config_dialogue_lead_unchanged():
    lines = resolve_episode(_ep())
    assert [(ln.kind, ln.speaker) for ln in lines] == [("dialogue", "lin_wan"), ("voiceover", "narrator")]
    assert resolve_episode(_ep(), narrator="lin_wan")[1].speaker == "lin_wan"
    assert resolve_episode(_ep(), {"ep99-S1#vo": "lin_wan"})[1].speaker == "lin_wan"
    assert default_voiceover_speaker({"characters": {"lin_wan": {}}}) == "lin_wan"
    assert default_voiceover_speaker({"voiceover_speaker": "ghost", "characters": {"lin_wan": {}}}) == "lin_wan"


def _kokoro_voice(cfg):
    """一个 Kokoro 音色（VOICE10 起 series10 人物都走克隆引擎、旧 Kokoro 条目可能被归档，测试自己造一个）"""
    c = {**cfg, "characters": {**cfg["characters"], "_kok": {"name": "测", "sid": 36, "voice": "zf_067", "speed": 1.0}}}
    return voice_for(c, "_kok")[0]


def test_voice_for_narrator_is_clone_engine_with_ref_sha_in_cache_key():
    cfg = load_voice_config()
    v = voice_for(cfg, "narrator", voiceover=True)[0]
    assert v.engine == "cosyvoice3_zs" and v.model.endswith(cfg["characters"]["narrator"]["ref_sha256"][:16])
    assert v.id == "cosyvoice3_zs:narrator_qag"
    lw = _kokoro_voice(cfg)
    assert lw.engine == "kokoro" and lw.id.startswith("kokoro:")
    other = Voice(v.speaker, v.sid, v.name, v.speed, "cosyvoice3_zs:0000000000000000", v.engine)
    assert clip_key("x", v, "kokoro") != clip_key("x", other, "kokoro")


class _Rec:
    def __init__(self):
        self.calls = []

    def synthesize(self, items):
        self.calls.append(items)
        for t, v, p in items:
            write_tone(p, 0.5, 220.0)


def test_routed_tts_splits_by_engine(tmp_path):
    cfg = load_voice_config()
    local, remote = _Rec(), _Rec()
    local.name = "kokoro"
    r = RoutedTts(local, cfg, remote=remote)
    nv, lv = voice_for(cfg, "narrator", voiceover=True)[0], _kokoro_voice(cfg)
    r.synthesize([("a", nv, tmp_path / "a.wav"), ("b", lv, tmp_path / "b.wav")])
    assert [it[0] for it in local.calls[0]] == ["b"] and [it[0] for it in remote.calls[0]] == ["a"]
    assert r.name == "kokoro"


class MockRemote:
    """Pretends to be ssh/scp to gpu36: keeps a fake remote filesystem, runs no command."""

    def __init__(self, ok=True):
        self.cmds, self.files, self.ok = [], {}, ok

    def __call__(self, cmd, timeout):
        self.cmds.append(cmd)
        out, rc = "", 0
        if cmd[0] == "scp":
            src, dst = cmd[-2], cmd[-1]
            if src.startswith("gpu36:"):  # download
                Path(dst).write_bytes(self.files[src.split(":", 1)[1]])
            else:
                self.files[dst.split(":", 1)[1]] = Path(src).read_bytes()
        else:
            c = cmd[-1]
            if c.startswith("sha256sum"):
                f = self.files.get(c.split()[1])
                out = (hashlib.sha256(f).hexdigest() + "  x") if f is not None else ""
            elif "sh run_narrator.sh " in c:
                req = json.loads(self.files[c.split("run_narrator.sh ")[1].split()[0]])
                assert req["engine"] == "cosyvoice3_zs" and req["ref_text"] and req["seed"] == 20261031
                if self.ok:
                    tmp = Path(self.tmp) / "tone.wav"
                    write_tone(tmp, 1.0, 200.0)
                    for it in req["items"]:
                        self.files[it["out"]] = tmp.read_bytes()
                    out = json.dumps({"ok": True, "items": [{"out": i["out"]} for i in req["items"]]})
                else:
                    out, rc = json.dumps({"ok": False, "error": "CUDA OOM"}), 1
        return subprocess.CompletedProcess(cmd, rc, out, "")


def test_remote_clone_backend_with_mock_runner(tmp_path):
    cfg = load_voice_config()
    m = MockRemote()
    m.tmp = tmp_path
    be = RemoteCloneBackend(cfg, runner=m, root=ROOT)
    v = voice_for(cfg, "narrator", voiceover=True)[0]
    paths = synthesize_cached(RoutedTts(FakeTts(), cfg, remote=be), [("第一句。", v), ("第二句。", v)],
                              cache_dir=tmp_path / "cache")
    assert all(p.is_file() and p.stat().st_size > 1000 for p in paths)
    uploaded = set(m.files)
    base = cfg["remote_tts"]["base_dir"]
    assert {f"{base}/narrator_batch.py", f"{base}/run_narrator.sh"} <= uploaded
    assert any(k.startswith(f"{base}/refs/narrator_") for k in uploaded)
    run = [c for c in m.cmds if c[0] == "ssh" and "sh run_narrator.sh " in c[-1]]
    assert len(run) == 1 and "'2' 13500" in run[0][-1]  # 一批两句、只给 GPU2
    # 第二次：全部命中缓存，不再连远端
    n = len(m.cmds)
    synthesize_cached(RoutedTts(FakeTts(), cfg, remote=be), [("第一句。", v)], cache_dir=tmp_path / "cache")
    assert len(m.cmds) == n


def test_remote_failure_raises_not_silent_fallback(tmp_path):
    cfg = load_voice_config()
    m = MockRemote(ok=False)
    m.tmp = tmp_path
    be = RemoteCloneBackend(cfg, runner=m, root=ROOT)
    v = voice_for(cfg, "narrator", voiceover=True)[0]
    with pytest.raises(TtsError):
        be.synthesize([("一句。", v, tmp_path / "x.wav")])


def test_plain_kokoro_backend_is_auto_routed(tmp_path, monkeypatch):
    cfg = load_voice_config()
    seen = {}

    class K(_Rec):
        name = "kokoro"

    import ns_post.tts as T
    rec = _Rec()
    monkeypatch.setattr(T.RoutedTts, "remote", property(lambda self: seen.setdefault("r", rec)))
    k = K()
    v, lw = voice_for(cfg, "narrator", voiceover=True)[0], _kokoro_voice(cfg)
    synthesize_cached(k, [("旁白。", v), ("对白。", lw)], cache_dir=tmp_path)
    assert [it[0] for it in k.calls[0]] == ["对白。"] and [it[0] for it in rec.calls[0]] == ["旁白。"]
